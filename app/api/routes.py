"""Internal API: health, inventory CRUD, documents, leads, appointments, audit.

Admin endpoints require the X-Admin-Token header (ADMIN_TOKEN in .env)."""
from __future__ import annotations

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.files import image_path_or_none, save_property_image
from app.rag import ingest as rag_ingest
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.database.models import AiEvent, Appointment, Conversation, Document, DocumentStatus, Lead, Message, Property
from app.properties import repository as prop_repo

app = FastAPI(title="inmobiliaria-ai", version="0.1.0")

_ORCH: dict = {"orchestrator": None}


def set_orchestrator(o) -> None:
    _ORCH["orchestrator"] = o


def require_admin(request: Request) -> None:
    s = get_settings()
    if request.headers.get("X-Admin-Token", "") != s.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


class PropertyIn(BaseModel):
    title: str
    property_type: str
    price: float
    operation: str = "SALE"
    description: str = ""
    currency: str = "COP"
    city: str = ""
    neighborhood: str = ""
    address: str = ""
    area_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    parking_spaces: int | None = None
    features: list[str] = Field(default_factory=list)
    project_id: str | None = None
    status: str = "AVAILABLE"


class PropertyPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    price: float | None = None
    currency: str | None = None
    city: str | None = None
    neighborhood: str | None = None
    address: str | None = None
    area_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    parking_spaces: int | None = None
    features: list[str] | None = None
    status: str | None = None
    property_type: str | None = None
    operation: str | None = None


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

@app.get("/properties")
async def list_properties(status: str | None = None, city: str | None = None, limit: int = 50, offset: int = 0):
    async with AsyncSessionLocal() as session:
        stmt = select(Property).order_by(Property.created_at.desc()).limit(min(limit, 200)).offset(offset)
        if status:
            stmt = stmt.where(Property.status == status)
        if city:
            stmt = stmt.where(Property.city.ilike(f"%{city}%"))
        props = (await session.execute(stmt)).scalars().all()
    return {"count": len(props), "properties": [p.to_dict() for p in props]}


@app.get("/properties/{property_id}")
async def get_property(property_id: str):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        return prop.to_dict()


@app.post("/properties", dependencies=[Depends(require_admin)])
async def create_property(data: PropertyIn):
    async with AsyncSessionLocal() as session:
        try:
            prop = await prop_repo.create_property(session, data.model_dump())
            await session.commit()
        except ValueError as e:
            raise HTTPException(422, str(e))
        return prop.to_dict()


@app.patch("/properties/{property_id}", dependencies=[Depends(require_admin)])
async def patch_property(property_id: str, data: PropertyPatch):
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.update_property(session, property_id, data.model_dump(exclude_none=True))
        if prop is None:
            raise HTTPException(404, "property not found")
        await session.commit()
        return prop.to_dict()


@app.delete("/properties/{property_id}", dependencies=[Depends(require_admin)])
async def delete_property(property_id: str):
    async with AsyncSessionLocal() as session:
        ok = await prop_repo.delete_property(session, property_id)
        if not ok:
            raise HTTPException(404, "property not found")
        await session.commit()
        return {"deleted": ok}


@app.post("/properties/{property_id}/images", dependencies=[Depends(require_admin)])
async def upload_image(property_id: str, file: UploadFile = File(...)):
    data = await file.read()
    async with AsyncSessionLocal() as session:
        prop = await prop_repo.get_property(session, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
    try:
        path = save_property_image(str(prop.id), data, file.filename or "img.jpg")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"saved": path}


@app.get("/properties/{property_id}/images")
async def list_images(property_id: str):
    from app.api.files import list_property_images

    return {"images": list_property_images(property_id)}


@app.get("/properties/{property_id}/images/{filename}")
async def get_image(property_id: str, filename: str):
    path = image_path_or_none(property_id, filename)
    if path is None:
        raise HTTPException(404, "image not found")
    return FileResponse(path)

# ------------------------------------------------------------------ documents
@app.get("/documents")
async def list_documents():
    async with AsyncSessionLocal() as session:
        docs = (await session.execute(select(Document).order_by(Document.created_at.desc()))).scalars().all()
    return {"count": len(docs), "documents": [d.to_dict() for d in docs]}


@app.post("/documents", dependencies=[Depends(require_admin)])
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    document_type: str = Form("general"),
):
    data = await file.read()
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


@app.post("/documents/{document_id}/process", dependencies=[Depends(require_admin)])
async def process_document(document_id: str):
    import uuid as uuid_mod

    async with AsyncSessionLocal() as session:
        try:
            doc = await rag_ingest.process_document(session, uuid_mod.UUID(document_id))
            await session.commit()
        except LookupError:
            raise HTTPException(404, "document not found")
        except Exception as e:
            raise HTTPException(422, f"processing failed: {e}")
        return doc.to_dict()


@app.delete("/documents/{document_id}", dependencies=[Depends(require_admin)])
async def delete_document(document_id: str):
    import os
    import uuid as uuid_mod

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


# ------------------------------------------------------------------ CRM / other
@app.get("/leads", dependencies=[Depends(require_admin)])
async def list_leads():
    from app.crm import service as crm

    async with AsyncSessionLocal() as session:
        leads = await crm.list_leads(session)
    return {"count": len(leads), "leads": [
        {"id": str(l.id), "user_id": l.user_id, "name": l.name, "phone": l.phone,
         "status": l.status.value, "budget": float(l.budget) if l.budget else None,
         "created_at": l.created_at.isoformat()}
        for l in leads
    ]}


@app.get("/appointments", dependencies=[Depends(require_admin)])
async def list_appointments():
    from app.appointments import service as appts

    async with AsyncSessionLocal() as session:
        items = await appts.list_appointments(session, limit=100)
    return {"count": len(items), "appointments": [
        {"id": str(a.id), "property_id": str(a.property_id), "lead_id": str(a.lead_id) if a.lead_id else None,
         "scheduled_at": a.scheduled_at.isoformat(), "status": a.status.value}
        for a in items
    ]}


@app.get("/conversations", dependencies=[Depends(require_admin)])
async def list_conversations(limit: int = 50):
    async with AsyncSessionLocal() as session:
        convs = (await session.execute(
            select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        )).scalars().all()
    out = []
    for c in convs:
        msgs = (await session.execute(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc()).limit(5)
        )).scalars().all()
        out.append({
            "id": str(c.id), "user_id": c.user_id, "summary": c.summary,
            "recent": [{"role": m.role.value, "content": m.content[:200]} for m in reversed(msgs)],
        })
    return {"count": len(out), "conversations": out}


@app.get("/ai-events", dependencies=[Depends(require_admin)])
async def list_ai_events(limit: int = 50):
    async with AsyncSessionLocal() as session:
        events = (await session.execute(
            select(AiEvent).order_by(AiEvent.id.desc()).limit(limit)
        )).scalars().all()
    return {"count": len(events), "events": [
        {"id": e.id, "request_id": e.request_id, "user_id": e.user_id, "intent": e.intent,
         "model": e.model, "tools": e.tool_calls, "latency_ms": e.latency_ms, "status": e.status,
         "created_at": e.created_at.isoformat()}
        for e in events
    ]}


