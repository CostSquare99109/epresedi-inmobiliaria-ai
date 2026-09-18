"""Internal API: health, inventory CRUD, documents, leads, appointments,
projects, admin users, business settings, audit log, CSV exports.

Admin auth: JWT issued by POST /auth/login (single source of authority).
Endpoints declare the permission they require via require_permission(...);
the JWT may arrive as an Authorization: Bearer header or as the
admin_access_token cookie. The legacy X-Admin-Token path was removed on
purpose: a shared static token must never bypass RBAC.
"""
from __future__ import annotations

import csv
import io
import uuid as uuid_mod
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from app.api.files import (
    delete_property_image,
    delete_property_storage,
    image_path_or_none,
    list_property_images,
    property_has_images,
    reorder_property_images,
    save_property_image,
    set_property_cover,
)
from app.appointments import service as appts_service
from app.core import bizconfig
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.crm import service as crm_service
from app.database.base import AsyncSessionLocal
from app.database.models import (
    AdminAuditLog,
    AdminRole,
    AdminUser,
    AiEvent,
    Appointment,
    AppointmentStatus,
    AppSetting,
    Conversation,
    Document,
    DocumentStatus,
    Lead,
    LeadStatus,
    Message,
    Operation,
    Project,
    Property,
    PropertyStatus,
    PropertyType,
)
from app.properties import repository as prop_repo
from app.rag import ingest as rag_ingest
from app.security import ratelimit
from app.security.auth import (
    authenticate_admin,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    log_admin_action,
    require_admin_user,
    require_permission,
)

app = FastAPI(title="inmobiliaria-ai", version="0.1.0")

_ORCH: dict = {"orchestrator": None}

log = get_logger(__name__)


def set_orchestrator(o) -> None:
    _ORCH["orchestrator"] = o


# ------------------------------------------------------------------ helpers
async def _audit(
    request: Request,
    user: AdminUser | None,
    action: str,
    entity: str,
    entity_id: str | None = None,
    metadata: dict | None = None,
    result: str = "success",
    error_message: str | None = None,
) -> None:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:300] or None
    try:
        await log_admin_action(
            admin_user_id=str(user.id) if user else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            metadata=metadata,
            ip_address=ip,
            user_agent=ua,
            result=result,
            error_message=error_message,
        )
    except Exception as e:  # pragma: no cover - audit must never break the flow
        log.warning("audit_write_failed action=%s error=%s", action, e)


def _validate_enum_value(value: str, enum_cls, name: str) -> str:
    valid = {m.value for m in enum_cls}
    if value not in valid:
        raise HTTPException(422, f"{name} inválido: {value}. Válidos: {sorted(valid)}")
    return value


def _uuid_or_none(value: str | None) -> uuid_mod.UUID | None:
    if value is None:
        return None
    try:
        return uuid_mod.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _with_images(prop: Property) -> dict:
    return {**prop.to_dict(), "has_images": property_has_images(str(prop.id))}


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


def _token_cookies(response: JSONResponse, access: str, refresh: str) -> None:
    s = get_settings()
    secure = s.APP_ENV == "production"
    response.set_cookie(
        "admin_access_token", access, httponly=True, samesite="lax",
        secure=secure, max_age=s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60, path="/",
    )
    response.set_cookie(
        "admin_refresh_token", refresh, httponly=True, samesite="lax",
        secure=secure, max_age=s.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400, path="/",
    )


@app.post("/auth/login")
async def login(data: LoginIn, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    try:
        await ratelimit.check_rate_limit(f"admin-login:{ip}", limit=10)
    except ratelimit.RateLimited:
        raise HTTPException(429, "Demasiados intentos de acceso. Espera un minuto.")
    user = await authenticate_admin(data.email.strip().lower(), data.password)
    if user is None:
        await _audit(request, None, "login", "auth", metadata={"email": data.email[:80]},
                     result="denied", error_message="credenciales inválidas")
        raise HTTPException(401, "Credenciales inválidas")
    s = get_settings()
    claims = {"sub": str(user.id), "email": user.email, "role": user.role.value, "name": user.name}
    access = create_access_token(claims)
    refresh = create_refresh_token(claims)
    async with AsyncSessionLocal() as session:
        db_user = await session.get(AdminUser, user.id)
        if db_user is not None:
            db_user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
    await _audit(request, user, "login", "auth", str(user.id))
    response = JSONResponse(status_code=200, content={
        "access_token": access, "refresh_token": refresh, "token_type": "bearer",
        "expires_in": s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60, "user": user.to_dict(),
    })
    _token_cookies(response, access, refresh)
    return response


@app.post("/auth/refresh")
async def refresh_token(data: RefreshIn, request: Request) -> JSONResponse:
    token_data = decode_refresh_token(data.refresh_token)
    if token_data is None:
        raise HTTPException(401, "Refresh token inválido o expirado")
    async with AsyncSessionLocal() as session:
        user = await session.get(AdminUser, _uuid_or_none(token_data.sub))
        if user is None or not user.is_active:
            raise HTTPException(401, "Usuario inactivo")
    s = get_settings()
    claims = {"sub": str(user.id), "email": user.email, "role": user.role.value, "name": user.name}
    access = create_access_token(claims)
    new_refresh = create_refresh_token(claims)
    response = JSONResponse(status_code=200, content={
        "access_token": access, "refresh_token": new_refresh, "token_type": "bearer",
        "expires_in": s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60, "user": user.to_dict(),
    })
    _token_cookies(response, access, new_refresh)
    return response


@app.get("/auth/me")
async def me(user: AdminUser = Depends(require_admin_user)) -> dict:
    from app.security.auth import PERMISSIONS, has_permission

    allowed = [p for p in PERMISSIONS.get(user.role, []) if has_permission(user.role, p)]
    return {"user": user.to_dict(), "permissions": allowed}


@app.post("/auth/logout")
async def logout(request: Request, user: AdminUser = Depends(require_admin_user)) -> JSONResponse:
    await _audit(request, user, "logout", "auth", str(user.id))
    response = JSONResponse(status_code=200, content={"ok": True})
    for name in ("admin_access_token", "admin_refresh_token"):
        response.delete_cookie(name, path="/")
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inmobiliaria-ai"}


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    checks: dict[str, object] = {}
    errors: dict[str, str] = {}
    try:
        from sqlalchemy import text

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            await session.execute(text("SELECT '[1,2,3]'::vector"))
        checks["postgres"] = True
        checks["pgvector"] = True
    except Exception as e:
        checks["postgres"] = False
        errors["postgres"] = str(e)[:200]
    from app.workers.queue import redis_healthy

    checks["redis"] = await redis_healthy()
    s = get_settings()
    if s.nvidia_configured:
        try:
            from app.ai.llm import NVIDIAProvider

            await NVIDIAProvider().chat([{"role": "user", "content": "ping"}], max_tokens=5)
            checks["nvidia"] = True
        except Exception as e:
            checks["nvidia"] = False
            errors["nvidia"] = str(e)[:200]
    else:
        checks["nvidia"] = True  # deterministic mode
    try:
        probe = s.storage_dir / ".probe"
        probe.write_text("ok")
        probe.unlink()
        checks["storage"] = True
    except Exception as e:
        checks["storage"] = False
        errors["storage"] = str(e)[:200]
    ok = all(bool(v) for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"ok": ok, "checks": checks, "errors": errors})

# ------------------------------------------------------------------ properties
@app.get("/properties")
async def list_properties(status: str | None = None, city: str | None = None, limit: int = 50, offset: int = 0):
    async with AsyncSessionLocal() as session:
        stmt = select(Property).order_by(Property.created_at.desc()).limit(min(limit, 200)).offset(offset)
        if status:
            stmt = stmt.where(Property.status == status)
        if city:
            stmt = stmt.where(Property.city.ilike(f"%{city}%"))
        props = (await session.execute(stmt)).scalars().all()
    return {"count": len(props), "properties": [_with_images(p) for p in props]}


@app.get("/properties/admin")
async def list_properties_admin(
    status: str | None = None,
    city: str | None = None,
    q: str | None = None,
    property_type: str | None = None,
    operation: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    project_id: str | None = None,
    without_images: bool = False,
    limit: int = 12,
    offset: int = 0,
):
    """Inventario admin: filtros combinados + total real + flag de imágenes."""
    async with AsyncSessionLocal() as session:
        props, total = await prop_repo.list_properties_admin(
            session, status=status, city=city, q=q, property_type=property_type,
            operation=operation, min_price=min_price, max_price=max_price,
            project_id=project_id, limit=limit, offset=offset,
        )
    items = [_with_images(p) for p in props]
    if without_images:
        items = [p for p in items if not p["has_images"]]
        total = len(items)
    return {"count": total, "total": total, "properties": items}


@app.get("/properties/{property_id}")
async def get_property(property_id: str):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        return _with_images(prop)


class PropertyIn(BaseModel):
    title: str = Field(max_length=200)
    property_type: str
    price: float = Field(ge=0)
    operation: str = "SALE"
    description: str = Field(default="", max_length=10000)
    currency: str = Field(default="COP", min_length=3, max_length=3)
    city: str = Field(default="", max_length=80)
    neighborhood: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=240)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    area_m2: float | None = Field(default=None, ge=0)
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    parking_spaces: int | None = Field(default=None, ge=0)
    features: list[str] = Field(default_factory=list)
    project_id: str | None = None
    status: str = "AVAILABLE"


class PropertyPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    city: str | None = Field(default=None, max_length=80)
    neighborhood: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=240)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    area_m2: float | None = Field(default=None, ge=0)
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    parking_spaces: int | None = Field(default=None, ge=0)
    features: list[str] | None = None
    status: str | None = None
    property_type: str | None = None
    operation: str | None = None
    project_id: str | None = None


@app.post("/properties")
async def create_property(
    data: PropertyIn, request: Request,
    user: AdminUser = Depends(require_permission("properties.create")),
):
    _validate_enum_value(data.property_type, PropertyType, "property_type")
    _validate_enum_value(data.operation, Operation, "operation")
    _validate_enum_value(data.status, PropertyStatus, "status")
    async with AsyncSessionLocal() as session:
        if data.project_id:
            project = await session.get(Project, _uuid_or_none(data.project_id))
            if project is None:
                raise HTTPException(422, "Proyecto no encontrado")
        try:
            prop = await prop_repo.create_property(session, data.model_dump())
            await session.commit()
            # Load project relationship before session closes
            if prop.project_id:
                await session.refresh(prop, attribute_names=["project"])
        except ValueError as e:
            raise HTTPException(422, str(e))
    await _audit(request, user, "property.created", "property", str(prop.id),
                 metadata={"code": prop.code, "title": prop.title[:80]})
    return _with_images(prop)


@app.patch("/properties/{property_id}")
async def patch_property(
    property_id: str, data: PropertyPatch, request: Request,
    user: AdminUser = Depends(require_permission("properties.update")),
):
    if data.property_type is not None:
        _validate_enum_value(data.property_type, PropertyType, "property_type")
    if data.operation is not None:
        _validate_enum_value(data.operation, Operation, "operation")
    if data.status is not None:
        _validate_enum_value(data.status, PropertyStatus, "status")
    async with AsyncSessionLocal() as session:
        if data.project_id:
            project = await session.get(Project, _uuid_or_none(data.project_id))
            if project is None:
                raise HTTPException(422, "Proyecto no encontrado")
        prop = await prop_repo.update_property(session, property_id, data.model_dump(exclude_none=True))
        if prop is None:
            raise HTTPException(404, "property not found")
        await session.commit()
        # Load project relationship before session closes
        if prop.project_id:
            await session.refresh(prop, attribute_names=["project"])
    action = "property.status_changed" if data.status is not None else "property.updated"
    await _audit(request, user, action, "property", str(prop.id),
                 metadata={k: (str(v)[:60] if not isinstance(v, list) else v[:10])
                           for k, v in data.model_dump(exclude_none=True).items() if k != "description"})
    return _with_images(prop)


@app.delete("/properties/{property_id}")
async def delete_property(
    property_id: str, request: Request,
    user: AdminUser = Depends(require_permission("properties.delete")),
):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        # Los documentos RAG referenciados se conservan (contexto del asistente):
        # se desvincula la FK (NO ACTION) antes del borrado de la propiedad.
        docs = (await session.execute(
            select(Document).where(Document.property_id == prop.id)
        )).scalars().all()
        for doc in docs:
            doc.property_id = None
        await session.execute(sa_delete(Property).where(Property.id == prop.id))
        await session.commit()
    images_removed = delete_property_storage(str(prop.id))
    await _audit(request, user, "property.deleted", "property", str(prop.id),
                 metadata={"code": prop.code, "title": prop.title[:80],
                           "images_removed": images_removed, "documents_unlinked": len(docs)})
    return {"deleted": True, "images_removed": images_removed, "documents_unlinked": len(docs)}

# ------------------------------------------------------------------ images
@app.post("/properties/{property_id}/images")
async def upload_image(
    request: Request,
    property_id: str,
    file: UploadFile = File(...),
    user: AdminUser = Depends(require_permission("properties.images")),
):
    data = await file.read()
    max_mb = await bizconfig.get_max_upload_mb()
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
    try:
        path = save_property_image(str(prop.id), data, file.filename or "img.jpg", max_mb=max_mb)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await _audit(request, user, "property.image_uploaded", "property", str(prop.id),
                 metadata={"filename": path.rsplit("/", 1)[-1], "bytes": len(data)})
    return {"saved": path.rsplit("/", 1)[-1], "images": list_property_images(str(prop.id))}


@app.get("/properties/{property_id}/images")
async def list_images(property_id: str):
    return {"images": list_property_images(property_id)}


@app.get("/properties/{property_id}/images/{filename}")
async def get_image(property_id: str, filename: str):
    path = image_path_or_none(property_id, filename)
    if path is None:
        raise HTTPException(404, "image not found")
    return FileResponse(path)


@app.delete("/properties/{property_id}/images/{filename}")
async def remove_image(
    property_id: str, filename: str, request: Request,
    user: AdminUser = Depends(require_permission("properties.images")),
):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
    try:
        images = delete_property_image(property_id, filename)
    except ValueError as e:
        raise HTTPException(404, str(e))
    await _audit(request, user, "property.image_deleted", "property", str(prop.id),
                 metadata={"filename": filename})
    return {"deleted": True, "images": images}


@app.post("/properties/{property_id}/images/reorder")
async def reorder_images(
    property_id: str, order: list[str], request: Request,
    user: AdminUser = Depends(require_permission("properties.images")),
):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
    try:
        images = reorder_property_images(property_id, order)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await _audit(request, user, "property.image_reorder", "property", str(prop.id),
                 metadata={"order": images[:20]})
    return {"images": images}


@app.post("/properties/{property_id}/images/{filename}/cover")
async def make_cover(
    property_id: str, filename: str, request: Request,
    user: AdminUser = Depends(require_permission("properties.images")),
):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
    try:
        images = set_property_cover(property_id, filename)
    except ValueError as e:
        raise HTTPException(404, str(e))
    await _audit(request, user, "property.cover_changed", "property", str(prop.id),
                 metadata={"cover": images[0] if images else None})
    return {"images": images}


@app.get("/properties/{property_id}/slots")
async def property_slots(property_id: str, days: int = 7):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        slots = await appts_service.list_available_slots(session, prop.id, days=min(days, 30))
    return {"count": len(slots), "slots": slots}

# ------------------------------------------------------------------ documents
@app.get("/documents")
async def list_documents():
    async with AsyncSessionLocal() as session:
        docs = (await session.execute(select(Document).order_by(Document.created_at.desc()))).scalars().all()
    return {"count": len(docs), "documents": [d.to_dict() for d in docs]}


@app.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    document_type: str = Form("general"),
    user: AdminUser = Depends(require_permission("documents.create")),
):
    data = await file.read()
    max_mb = await bizconfig.get_max_upload_mb()
    try:
        rag_ingest.validate_document(file.filename or "doc.txt", data, max_mb=max_mb)
    except rag_ingest.DocumentValidationError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    async with AsyncSessionLocal() as session:
        try:
            doc, created = await rag_ingest.save_document(
                session, filename=file.filename or "doc.txt", data=data,
                title=title, document_type=document_type,
            )
            await session.commit()
        except rag_ingest.DocumentValidationError as e:
            raise HTTPException(422, f"{e.code}: {e}")
        return {"document": doc.to_dict(), "created": created}


@app.post("/documents/{document_id}/process")
async def process_document(document_id: str):
    async with AsyncSessionLocal() as session:
        try:
            doc = await rag_ingest.process_document(session, uuid_mod.UUID(document_id))
            await session.commit()
        except LookupError:
            raise HTTPException(404, "document not found")
        except Exception as e:
            raise HTTPException(422, f"processing failed: {e}")
        return doc.to_dict()


@app.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    import os

    async with AsyncSessionLocal() as session:
        doc = (await session.execute(
            select(Document).where(Document.id == uuid_mod.UUID(document_id))
        )).scalar_one_or_none()
        if doc is None:
            raise HTTPException(404, "document not found")
        if doc.file_path and os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except OSError:
                pass
        await session.delete(doc)
        await session.commit()
        return {"deleted": True}

# ------------------------------------------------------------------ CRM / leads
def _lead_dict(l: Lead, assigned_name: str | None = None) -> dict:
    return {
        "id": str(l.id), "user_id": l.user_id, "name": l.name, "phone": l.phone,
        "status": l.status.value,
        "budget": float(l.budget) if l.budget is not None else None,
        "notes": l.notes, "preferences": l.preferences or {},
        "assigned_admin_id": str(l.assigned_admin_id) if l.assigned_admin_id else None,
        "assigned_admin_name": assigned_name,
        "created_at": l.created_at.isoformat(), "updated_at": l.updated_at.isoformat(),
    }


@app.get("/leads")
async def list_leads(
    limit: int = 200,
    user: AdminUser = Depends(require_permission("leads.read")),
):
    async with AsyncSessionLocal() as session:
        leads = (await session.execute(
            select(Lead).order_by(Lead.updated_at.desc()).limit(min(limit, 500))
        )).scalars().all()
        admin_ids = {l.assigned_admin_id for l in leads if l.assigned_admin_id}
        admins: dict[str, str] = {}
        if admin_ids:
            rows = (await session.execute(
                select(AdminUser).where(AdminUser.id.in_(admin_ids))
            )).scalars().all()
            admins = {str(a.id): a.name for a in rows}
    return {"count": len(leads), "leads": [
        _lead_dict(l, admins.get(str(l.assigned_admin_id)) if l.assigned_admin_id else None)
        for l in leads
    ]}


@app.get("/conversations")
async def list_conversations(
    limit: int = 100,
    user: AdminUser = Depends(require_permission("conversations.read")),
):
    async with AsyncSessionLocal() as session:
        convs = (await session.execute(
            select(Conversation).order_by(Conversation.updated_at.desc()).limit(min(limit, 200))
        )).scalars().all()
    return {"count": len(convs), "conversations": [
        {
            "id": str(c.id), "user_id": c.user_id, "summary": c.summary,
            "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
        } for c in convs
    ]}


@app.get("/leads/{lead_id}")
async def get_lead(
    lead_id: str,
    user: AdminUser = Depends(require_permission("leads.read")),
):
    async with AsyncSessionLocal() as session:
        lead = (await session.execute(
            select(Lead).where(Lead.id == _uuid_or_none(lead_id))
        )).scalar_one_or_none()
        if lead is None:
            raise HTTPException(404, "lead not found")
        assigned_name = None
        if lead.assigned_admin_id:
            admin = await session.get(AdminUser, lead.assigned_admin_id)
            assigned_name = admin.name if admin else None
        appt_items = (await session.execute(
            select(Appointment).where(Appointment.lead_id == lead.id)
            .order_by(Appointment.scheduled_at.desc()).limit(20)
        )).scalars().all()
    return {
        "lead": _lead_dict(lead, assigned_name),
        "appointments": [
            {"id": str(a.id), "property_id": str(a.property_id),
             "scheduled_at": a.scheduled_at.isoformat(), "status": a.status.value,
             "notes": a.notes}
            for a in appt_items
        ],
    }


class LeadPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    budget: float | None = Field(default=None, ge=0)
    status: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    preferences: dict | None = None
    assigned_admin_id: str | None = None


@app.patch("/leads/{lead_id}")
async def patch_lead(
    lead_id: str, data: LeadPatch, request: Request,
    user: AdminUser = Depends(require_permission("leads.update")),
):
    if data.status is not None:
        _validate_enum_value(data.status, LeadStatus, "status")
    async with AsyncSessionLocal() as session:
        try:
            lead = await crm_service.update_lead(
                session, _uuid_or_none(lead_id), data.model_dump(exclude_none=False)
            )
        except ValueError as e:
            raise HTTPException(422, str(e))
        if lead is None:
            raise HTTPException(404, "lead not found")
        await session.commit()
        assigned_name = None
        if lead.assigned_admin_id:
            admin = await session.get(AdminUser, lead.assigned_admin_id)
            assigned_name = admin.name if admin else None
    action = "lead.status_changed" if data.status is not None else "lead.updated"
    await _audit(request, user, action, "lead", str(lead.id),
                 metadata={k: str(v)[:60] for k, v in data.model_dump(exclude_none=True).items()
                           if k not in ("notes", "preferences")})
    return _lead_dict(lead, assigned_name)

# ------------------------------------------------------------------ appointments
def _appt_dict(a: Appointment) -> dict:
    return {
        "id": str(a.id), "property_id": str(a.property_id),
        "lead_id": str(a.lead_id) if a.lead_id else None,
        "scheduled_at": a.scheduled_at.isoformat(),
        "duration_minutes": a.duration_minutes,
        "status": a.status.value, "notes": a.notes,
        "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
    }


@app.get("/appointments")
async def list_appointments(
    status: str | None = None, limit: int = 200,
    user: AdminUser = Depends(require_permission("appointments.read")),
):
    if status:
        _validate_enum_value(status, AppointmentStatus, "status")
    async with AsyncSessionLocal() as session:
        stmt = select(Appointment).order_by(Appointment.scheduled_at.desc()).limit(min(limit, 500))
        if status:
            stmt = stmt.where(Appointment.status == status)
        items = (await session.execute(stmt)).scalars().all()
    return {"count": len(items), "appointments": [_appt_dict(a) for a in items]}


@app.get("/appointments/{appointment_id}")
async def get_appointment(
    appointment_id: str,
    user: AdminUser = Depends(require_permission("appointments.read")),
):
    async with AsyncSessionLocal() as session:
        appt = await appts_service.get_appointment(session, _uuid_or_none(appointment_id))
        if appt is None:
            raise HTTPException(404, "appointment not found")
    return _appt_dict(appt)


class AppointmentIn(BaseModel):
    property_id: str
    lead_id: str | None = None
    scheduled_at: str
    duration_minutes: int = Field(default=60, ge=15, le=240)
    notes: str = Field(default="", max_length=1000)


@app.post("/appointments")
async def create_appointment(
    data: AppointmentIn, request: Request,
    user: AdminUser = Depends(require_permission("appointments.create")),
):
    try:
        scheduled_at = datetime.fromisoformat(data.scheduled_at)
    except ValueError:
        raise HTTPException(422, "scheduled_at debe ser una fecha ISO válida (ej. 2026-09-20T10:00)")
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, data.property_id)
        if prop is None:
            raise HTTPException(422, "Propiedad no encontrada")
        if data.lead_id:
            lead = (await session.execute(
                select(Lead).where(Lead.id == _uuid_or_none(data.lead_id))
            )).scalar_one_or_none()
            if lead is None:
                raise HTTPException(422, "Lead no encontrado")
        try:
            appt = await appts_service.create_appointment(
                session, property_id=prop.id, lead_id=_uuid_or_none(data.lead_id),
                scheduled_at=scheduled_at, notes=data.notes,
            )
            if appt.lead_id is not None:
                await crm_service.set_lead_status_from_appointment(session, appt.lead_id)
            await session.commit()
        except appts_service.SlotUnavailable as e:
            raise HTTPException(409, str(e))
    await _audit(request, user, "appointment.created", "appointment", str(appt.id),
                 metadata={"property_id": str(appt.property_id), "scheduled_at": appt.scheduled_at.isoformat()})
    return _appt_dict(appt)


class AppointmentPatch(BaseModel):
    status: str | None = None
    scheduled_at: str | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=240)
    notes: str | None = Field(default=None, max_length=1000)


@app.patch("/appointments/{appointment_id}")
async def patch_appointment(
    appointment_id: str, data: AppointmentPatch, request: Request,
    user: AdminUser = Depends(require_permission("appointments.update")),
):
    async with AsyncSessionLocal() as session:
        appt = await appts_service.get_appointment(session, _uuid_or_none(appointment_id))
        if appt is None:
            raise HTTPException(404, "appointment not found")
        if data.status is not None:
            _validate_enum_value(data.status, AppointmentStatus, "status")
            target = AppointmentStatus(data.status)
            allowed = appts_service.APPOINTMENT_TRANSITIONS.get(appt.status, set())
            if target not in allowed:
                raise HTTPException(422, f"Transición inválida: {appt.status.value} → {target.value}")
            appt.status = target
        if data.scheduled_at is not None:
            try:
                scheduled_at = datetime.fromisoformat(data.scheduled_at)
            except ValueError:
                raise HTTPException(422, "scheduled_at debe ser una fecha ISO válida")
            try:
                await appts_service.reschedule_appointment(session, appt.id, scheduled_at)
            except appts_service.SlotUnavailable as e:
                raise HTTPException(409, str(e))
        if data.duration_minutes is not None:
            appt.duration_minutes = data.duration_minutes
        if data.notes is not None:
            appt.notes = data.notes[:1000]
        await session.commit()
    if data.status is not None:
        action = f"appointment.{data.status.lower()}"
    elif data.scheduled_at is not None:
        action = "appointment.rescheduled"
    else:
        action = "appointment.updated"
    await _audit(request, user, action, "appointment", str(appt.id),
                 metadata={k: str(v)[:60] for k, v in data.model_dump(exclude_none=True).items()
                           if k != "notes"})
    return _appt_dict(appt)


@app.delete("/appointments/{appointment_id}")
async def cancel_appointment(
    appointment_id: str, request: Request,
    user: AdminUser = Depends(require_permission("appointments.cancel")),
):
    async with AsyncSessionLocal() as session:
        ok = await appts_service.cancel_appointment(session, _uuid_or_none(appointment_id))
        if not ok:
            raise HTTPException(404, "appointment not found o ya finalizada")
        await session.commit()
    await _audit(request, user, "appointment.cancelled", "appointment", appointment_id)
    return {"cancelled": True}

# ------------------------------------------------------------------ projects
def _project_dict(p: Project, property_count: int | None = None) -> dict:
    out = {
        "id": str(p.id), "name": p.name, "description": p.description, "city": p.city,
        "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
    }
    if property_count is not None:
        out["property_count"] = property_count
    return out


@app.get("/projects")
async def list_projects():
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Project, func.count(Property.id))
            .outerjoin(Property, Property.project_id == Project.id)
            .group_by(Project.id).order_by(Project.created_at.desc())
        )).all()
    return {"count": len(rows), "projects": [_project_dict(p, int(n)) for p, n in rows]}


@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, _uuid_or_none(project_id))
        if project is None:
            raise HTTPException(404, "project not found")
        n = (await session.execute(
            select(func.count()).select_from(Property).where(Property.project_id == project.id)
        )).scalar() or 0
    return _project_dict(project, int(n))


class ProjectIn(BaseModel):
    name: str = Field(max_length=160)
    description: str = Field(default="", max_length=5000)
    city: str = Field(default="", max_length=80)


@app.post("/projects")
async def create_project(
    data: ProjectIn, request: Request,
    user: AdminUser = Depends(require_permission("projects.create")),
):
    async with AsyncSessionLocal() as session:
        exists = (await session.execute(
            select(Project).where(Project.name == data.name.strip())
        )).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(409, f"Ya existe un proyecto llamado «{data.name.strip()}»")
        project = Project(name=data.name.strip(), description=data.description, city=data.city)
        session.add(project)
        await session.commit()
        await session.refresh(project)
    await _audit(request, user, "project.created", "project", str(project.id),
                 metadata={"name": project.name})
    return _project_dict(project, 0)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    city: str | None = Field(default=None, max_length=80)


@app.patch("/projects/{project_id}")
async def patch_project(
    project_id: str, data: ProjectPatch, request: Request,
    user: AdminUser = Depends(require_permission("projects.update")),
):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, _uuid_or_none(project_id))
        if project is None:
            raise HTTPException(404, "project not found")
        if data.name is not None:
            name = data.name.strip()
            exists = (await session.execute(
                select(Project).where(Project.name == name, Project.id != project.id)
            )).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(409, f"Ya existe un proyecto llamado «{name}»")
            project.name = name
        if data.description is not None:
            project.description = data.description
        if data.city is not None:
            project.city = data.city
        await session.commit()
    await _audit(request, user, "project.updated", "project", str(project.id),
                 metadata={k: str(v)[:60] for k, v in data.model_dump(exclude_none=True).items()})
    return _project_dict(project)


@app.delete("/projects/{project_id}")
async def delete_project(
    project_id: str, request: Request,
    user: AdminUser = Depends(require_permission("projects.delete")),
):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, _uuid_or_none(project_id))
        if project is None:
            raise HTTPException(404, "project not found")
        n = (await session.execute(
            select(func.count()).select_from(Property).where(Property.project_id == project.id)
        )).scalar() or 0
        if n > 0:
            raise HTTPException(409, f"El proyecto tiene {n} propiedad(es) asignadas. Desasígnalas antes de eliminarlo.")
        await session.delete(project)
        await session.commit()
    await _audit(request, user, "project.deleted", "project", project_id,
                 metadata={"name": project.name})
    return {"deleted": True}

# ------------------------------------------------------------------ admin users
@app.get("/admin-users")
async def list_admin_users(user: AdminUser = Depends(require_permission("users.manage"))):
    async with AsyncSessionLocal() as session:
        users = (await session.execute(
            select(AdminUser).order_by(AdminUser.created_at.desc())
        )).scalars().all()
    return {"count": len(users), "users": [u.to_dict() for u in users]}


class AdminUserIn(BaseModel):
    email: str = Field(max_length=255)
    name: str = Field(max_length=160)
    password: str = Field(min_length=8, max_length=128)
    role: str


@app.post("/admin-users")
async def create_admin_user(
    data: AdminUserIn, request: Request,
    user: AdminUser = Depends(require_permission("users.manage")),
):
    _validate_enum_value(data.role, AdminRole, "role")
    from app.security.auth import create_admin_user as _create

    async with AsyncSessionLocal() as session:
        try:
            created = await _create(data.email.strip().lower(), data.name.strip(), data.password, AdminRole(data.role))
        except ValueError as e:
            raise HTTPException(409, str(e))
    await _audit(request, user, "user.created", "admin_user", str(created.id),
                 metadata={"email": created.email, "role": created.role.value})
    return created.to_dict()


class AdminUserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


@app.patch("/admin-users/{admin_user_id}")
async def patch_admin_user(
    admin_user_id: str, data: AdminUserPatch, request: Request,
    user: AdminUser = Depends(require_permission("users.manage")),
):
    from app.security.auth import count_active_superadmins, hash_password

    if data.role is not None:
        _validate_enum_value(data.role, AdminRole, "role")
    async with AsyncSessionLocal() as session:
        target = await session.get(AdminUser, _uuid_or_none(admin_user_id))
        if target is None:
            raise HTTPException(404, "user not found")
        is_self = target.id == user.id
        target_is_superadmin = target.role == AdminRole.SUPERADMIN
        if is_self and data.role is not None and AdminRole(data.role) != target.role:
            raise HTTPException(422, "No puedes cambiar tu propio rol. Pide el cambio a otro superadmin.")
        if is_self and data.is_active is False:
            raise HTTPException(422, "No puedes desactivar tu propia cuenta.")
        if target_is_superadmin and (
            (data.role is not None and AdminRole(data.role) != AdminRole.SUPERADMIN)
            or data.is_active is False
        ):
            active_superadmins = await count_active_superadmins(session)
            if active_superadmins <= 1:
                raise HTTPException(422, "No puedes desactivar o degradar al último superadmin activo.")
        if data.name is not None:
            target.name = data.name.strip()
        if data.role is not None:
            target.role = AdminRole(data.role)
        if data.is_active is not None:
            target.is_active = data.is_active
        if data.password is not None:
            target.password_hash = hash_password(data.password)
        await session.commit()
        result = target.to_dict()
    action = "user.password_reset" if data.password is not None else "user.updated"
    await _audit(request, user, action, "admin_user", str(target.id),
                 metadata={"email": target.email,
                           "role": target.role.value,
                           "is_active": target.is_active})
    return result

# ------------------------------------------------------------------ settings
KNOWN_SETTING_KEYS = set(bizconfig.SETTING_DEFAULTS) | set(bizconfig.SETTING_DESCRIPTIONS)


@app.get("/settings")
async def get_app_settings(user: AdminUser = Depends(require_permission("settings.read"))):
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(AppSetting))).scalars().all()
        stored = {r.key: r.value for r in rows}
    return {"settings": [
        {"key": k, "value": stored.get(k, bizconfig.SETTING_DEFAULTS.get(k)),
         "description": bizconfig.SETTING_DESCRIPTIONS.get(k, "")}
        for k in sorted(KNOWN_SETTING_KEYS)
    ]}


class SettingsIn(BaseModel):
    settings: dict[str, object]


@app.put("/settings")
async def put_app_settings(
    data: SettingsIn, request: Request,
    user: AdminUser = Depends(require_permission("settings.manage")),
):
    for key, value in data.settings.items():
        if key not in KNOWN_SETTING_KEYS:
            raise HTTPException(422, f"Clave de configuración desconocida: {key}")
        if key == "appointment_hours":
            if not isinstance(value, list) or not all(isinstance(h, int) and 0 <= h <= 23 for h in value) or not value:
                raise HTTPException(422, "appointment_hours debe ser una lista de horas enteras (0-23)")
        elif key == "max_upload_mb":
            if not isinstance(value, int) or not (1 <= value <= 200):
                raise HTTPException(422, "max_upload_mb debe ser un entero entre 1 y 200")
        elif key == "timezone":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            if not isinstance(value, str) or not value:
                raise HTTPException(422, "timezone debe ser un nombre de zona horaria válido")
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError, KeyError):
                raise HTTPException(422, f"Zona horaria desconocida: {value}")
        elif not isinstance(value, str):
            raise HTTPException(422, f"{key} debe ser texto")
    async with AsyncSessionLocal() as session:
        for key, value in data.settings.items():
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=value,
                                       description=bizconfig.SETTING_DESCRIPTIONS.get(key, "")))
            else:
                row.value = value
        await session.commit()
    bizconfig.invalidate()
    await _audit(request, user, "settings.updated", "setting", None,
                 metadata={"keys": sorted(data.settings.keys())})
    return {"updated": sorted(data.settings.keys())}

# ------------------------------------------------------------------ CMS content
def _cms_dict(c: CmsContent) -> dict:
    return {
        "id": str(c.id), "key": c.key, "type": c.type.value, "value": c.value,
        "label": c.label, "description": c.description, "group": c.group,
        "is_public": c.is_public,
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    }


@app.get("/cms-content")
async def list_cms_content(user: AdminUser = Depends(require_permission("content.read"))):
    async with AsyncSessionLocal() as session:
        contents = (await session.execute(select(CmsContent).order_by(CmsContent.group, CmsContent.key))).scalars().all()
    return {"count": len(contents), "contents": [_cms_dict(c) for c in contents]}


@app.get("/cms-content/{content_id}")
async def get_cms_content(
    content_id: str,
    user: AdminUser = Depends(require_permission("content.read")),
):
    async with AsyncSessionLocal() as session:
        content = await session.get(CmsContent, _uuid_or_none(content_id))
        if content is None:
            raise HTTPException(404, "content not found")
    return _cms_dict(content)


class CmsContentIn(BaseModel):
    key: str = Field(max_length=100)
    type: str
    value: str = ""
    label: str = Field(default="", max_length=200)
    description: str = ""
    group: str = Field(default="general", max_length=50)
    is_public: bool = False


@app.post("/cms-content")
async def create_cms_content(
    data: CmsContentIn, request: Request,
    user: AdminUser = Depends(require_permission("content.create")),
):
    _validate_enum_value(data.type, CmsContentType, "type")
    async with AsyncSessionLocal() as session:
        exists = (await session.execute(select(CmsContent).where(CmsContent.key == data.key.strip()))).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(409, f"Ya existe contenido con clave «{data.key.strip()}»")
        content = CmsContent(
            key=data.key.strip(), type=CmsContentType(data.type), value=data.value,
            label=data.label.strip(), description=data.description, group=data.group.strip(),
            is_public=data.is_public,
        )
        session.add(content)
        await session.commit()
        await session.refresh(content)
    await _audit(request, user, "content.created", "cms_content", str(content.id),
                 metadata={"key": content.key, "type": content.type.value})
    return _cms_dict(content)


class CmsContentPatch(BaseModel):
    key: str | None = Field(default=None, max_length=100)
    type: str | None = None
    value: str | None = None
    label: str | None = Field(default=None, max_length=200)
    description: str | None = None
    group: str | None = Field(default=None, max_length=50)
    is_public: bool | None = None


@app.patch("/cms-content/{content_id}")
async def patch_cms_content(
    content_id: str, data: CmsContentPatch, request: Request,
    user: AdminUser = Depends(require_permission("content.update")),
):
    if data.type is not None:
        _validate_enum_value(data.type, CmsContentType, "type")
    async with AsyncSessionLocal() as session:
        content = await session.get(CmsContent, _uuid_or_none(content_id))
        if content is None:
            raise HTTPException(404, "content not found")
        if data.key is not None:
            key = data.key.strip()
            exists = (await session.execute(
                select(CmsContent).where(CmsContent.key == key, CmsContent.id != content.id)
            )).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(409, f"Ya existe contenido con clave «{key}»")
            content.key = key
        if data.type is not None:
            content.type = CmsContentType(data.type)
        if data.value is not None:
            content.value = data.value
        if data.label is not None:
            content.label = data.label.strip()
        if data.description is not None:
            content.description = data.description
        if data.group is not None:
            content.group = data.group.strip()
        if data.is_public is not None:
            content.is_public = data.is_public
        await session.commit()
    await _audit(request, user, "content.updated", "cms_content", str(content.id),
                 metadata={k: str(v)[:60] for k, v in data.model_dump(exclude_none=True).items()})
    return _cms_dict(content)


@app.delete("/cms-content/{content_id}")
async def delete_cms_content(
    content_id: str, request: Request,
    user: AdminUser = Depends(require_permission("content.delete")),
):
    async with AsyncSessionLocal() as session:
        content = await session.get(CmsContent, _uuid_or_none(content_id))
        if content is None:
            raise HTTPException(404, "content not found")
        key = content.key
        await session.delete(content)
        await session.commit()
    await _audit(request, user, "content.deleted", "cms_content", content_id,
                 metadata={"key": key})
    return {"deleted": True}

# ------------------------------------------------------------------ audit log
@app.get("/audit-log")
async def list_audit_log(
    limit: int = 50, offset: int = 0, action: str | None = None, entity: str | None = None,
    user: AdminUser = Depends(require_permission("audit.read")),
):
    async with AsyncSessionLocal() as session:
        conds = []
        if action:
            conds.append(AdminAuditLog.action == action)
        if entity:
            conds.append(AdminAuditLog.entity == entity)
        stmt = select(AdminAuditLog, AdminUser.email, AdminUser.name).outerjoin(
            AdminUser, AdminUser.id == AdminAuditLog.admin_user_id
        ).order_by(AdminAuditLog.created_at.desc())
        count_stmt = select(func.count()).select_from(AdminAuditLog)
        if conds:
            stmt = stmt.where(*conds)
            count_stmt = count_stmt.where(*conds)
        stmt = stmt.limit(min(limit, 200)).offset(offset)
        rows = (await session.execute(stmt)).all()
        total = (await session.execute(count_stmt)).scalar() or 0
    return {"count": total, "total": total, "events": [
        {
            "id": entry.id, "action": entry.action, "entity": entry.entity,
            "entity_id": entry.entity_id, "metadata": entry.audit_metadata or {},
            "result": entry.result, "error_message": entry.error_message,
            "actor_email": email or "sistema", "actor_name": name,
            "created_at": entry.created_at.isoformat(),
        }
        for entry, email, name in rows
    ]}


@app.get("/ai-events")
async def list_ai_events(
    limit: int = 100, offset: int = 0, status: str | None = None, intent: str | None = None,
    user: AdminUser = Depends(require_permission("audit.read")),
):
    async with AsyncSessionLocal() as session:
        conds = []
        if status:
            conds.append(AiEvent.status == status)
        if intent:
            conds.append(AiEvent.intent == intent)
        stmt = select(AiEvent).order_by(AiEvent.created_at.desc())
        count_stmt = select(func.count()).select_from(AiEvent)
        if conds:
            stmt = stmt.where(*conds)
            count_stmt = count_stmt.where(*conds)
        stmt = stmt.limit(min(limit, 200)).offset(offset)
        rows = (await session.execute(stmt)).scalars().all()
        total = (await session.execute(count_stmt)).scalar() or 0
    return {"count": total, "total": total, "events": [
        {
            "id": e.id, "request_id": e.request_id, "user_id": e.user_id,
            "intent": e.intent, "model": e.model, "tools": e.tool_calls,
            "latency_ms": e.latency_ms, "status": e.status, "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]}


# ------------------------------------------------------------------ CSV exports
def _csv_response(rows: list[dict], headers: list[str], filename: str) -> Response:
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM: Excel detecta UTF-8
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    content = buf.getvalue().encode("utf-8")
    return Response(
        content=content, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/properties.csv")
async def export_properties_csv(
    status: str | None = None, city: str | None = None,
    user: AdminUser = Depends(require_permission("properties.read")),
):
    async with AsyncSessionLocal() as session:
        stmt = select(Property).order_by(Property.created_at.desc()).limit(1000)
        if status:
            stmt = stmt.where(Property.status == status)
        if city:
            stmt = stmt.where(Property.city.ilike(f"%{city}%"))
        props = (await session.execute(stmt)).scalars().all()
    rows = [{
        "code": p.code, "title": p.title, "tipo": p.property_type.value,
        "operacion": p.operation.value, "precio": float(p.price), "moneda": p.currency,
        "ciudad": p.city, "barrio": p.neighborhood, "direccion": p.address,
        "area_m2": float(p.area_m2) if p.area_m2 is not None else "",
        "habitaciones": p.bedrooms if p.bedrooms is not None else "",
        "banos": p.bathrooms if p.bathrooms is not None else "",
        "parqueaderos": p.parking_spaces if p.parking_spaces is not None else "",
        "estado": p.status.value, "caracteristicas": "; ".join(p.features or []),
        "proyecto": p.project.name if p.project else "",
        "creado": p.created_at.isoformat(), "actualizado": p.updated_at.isoformat(),
    } for p in props]
    return _csv_response(rows, list(rows[0].keys()) if rows else ["code"], "propiedades.csv")


@app.get("/export/leads.csv")
async def export_leads_csv(
    status: str | None = None,
    user: AdminUser = Depends(require_permission("leads.read")),
):
    async with AsyncSessionLocal() as session:
        stmt = select(Lead).order_by(Lead.created_at.desc()).limit(1000)
        if status:
            stmt = stmt.where(Lead.status == status)
        leads = (await session.execute(stmt)).scalars().all()
    rows = [{
        "id": str(l.id), "nombre": l.name, "telefono": l.phone, "estado": l.status.value,
        "presupuesto": float(l.budget) if l.budget is not None else "",
        "notas": l.notes, "creado": l.created_at.isoformat(), "actualizado": l.updated_at.isoformat(),
    } for l in leads]
    return _csv_response(rows, list(rows[0].keys()) if rows else ["id"], "leads.csv")


@app.get("/export/appointments.csv")
async def export_appointments_csv(
    status: str | None = None,
    user: AdminUser = Depends(require_permission("appointments.read")),
):
    if status:
        _validate_enum_value(status, AppointmentStatus, "status")
    async with AsyncSessionLocal() as session:
        stmt = select(Appointment).order_by(Appointment.scheduled_at.desc()).limit(1000)
        if status:
            stmt = stmt.where(Appointment.status == status)
        appt_items = (await session.execute(stmt)).scalars().all()
    rows = [{
        "id": str(a.id), "propiedad_id": str(a.property_id),
        "lead_id": str(a.lead_id) if a.lead_id else "",
        "fecha": a.scheduled_at.isoformat(), "duracion_min": a.duration_minutes,
        "estado": a.status.value, "notas": a.notes,
        "creado": a.created_at.isoformat(),
    } for a in appt_items]
    return _csv_response(rows, list(rows[0].keys()) if rows else ["id"], "citas.csv")
