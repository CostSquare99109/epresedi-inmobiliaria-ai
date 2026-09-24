"""Admin authentication: JWT tokens, password hashing, permissions."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from jose import jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.database.models import AdminRole, AdminUser

log = get_logger(__name__)


class TokenData(BaseModel):
    sub: str
    email: str
    role: str
    exp: int


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def hash_password(password: str) -> str:
    """Hash password with PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"pbkdf2_sha256${100_000}${salt.hex()}${key.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify PBKDF2 password hash."""
    try:
        algo, iterations_str, salt_hex, key_hex = password_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return secrets.compare_digest(derived, key)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    s = get_settings()
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, s.JWT_SECRET, algorithm=s.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    s = get_settings()
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=s.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, s.JWT_SECRET, algorithm=s.JWT_ALGORITHM)


def decode_token(token: str) -> TokenData | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.JWT_SECRET, algorithms=[s.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return TokenData(
            sub=payload.get("sub", ""),
            email=payload.get("email", ""),
            role=payload.get("role", ""),
            exp=payload.get("exp", 0),
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.JWTError:
        return None


def decode_refresh_token(token: str) -> TokenData | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.JWT_SECRET, algorithms=[s.JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return TokenData(
            sub=payload.get("sub", ""),
            email=payload.get("email", ""),
            role=payload.get("role", ""),
            exp=payload.get("exp", 0),
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.JWTError:
        return None


async def get_admin_user(session: AsyncSession, user_id: str) -> AdminUser | None:
    import uuid as uuid_mod

    try:
        uid = user_id if isinstance(user_id, uuid_mod.UUID) else uuid_mod.UUID(str(user_id))
    except (ValueError, AttributeError):
        return None
    return await session.get(AdminUser, uid)


async def authenticate_admin(email: str, password: str) -> AdminUser | None:
    async with AsyncSessionLocal() as session:
        stmt = select(AdminUser).where(AdminUser.email == email, AdminUser.is_active.is_(True))
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user and verify_password(password, user.password_hash):
            return user
    return None


async def create_admin_user(
    email: str,
    name: str,
    password: str,
    role: AdminRole = AdminRole.ASESOR,
) -> AdminUser:
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(AdminUser).where(AdminUser.email == email))).scalar_one_or_none()
        if existing:
            raise ValueError("Email ya registrado")
        user = AdminUser(
            email=email,
            name=name,
            password_hash=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.flush()
        await session.commit()
        await session.refresh(user)
        return user


# Permission matrix
PERMISSIONS = {
    AdminRole.SUPERADMIN: [
        "properties.*",
        "images.*",
        "leads.*",
        "appointments.*",
        "documents.*",
        "conversations.*",
        "users.*",
        "settings.*",
        "content.*",
        "audit.*",
    ],
    AdminRole.ADMIN: [
        "properties.read",
        "properties.create",
        "properties.update",
        "properties.delete",
        "properties.status",
        "images.*",
        "leads.read",
        "leads.update",
        "appointments.read",
        "appointments.create",
        "appointments.update",
        "appointments.cancel",
        "documents.*",
        "settings.read",
        "content.*",
        "audit.read",
    ],
    AdminRole.EDITOR: [
        "properties.read",
        "properties.create",
        "properties.update",
        "properties.status",
        "images.*",
        "leads.read",
        "leads.update",
        "appointments.read",
        "appointments.create",
        "documents.read",
        "documents.create",
        "content.*",
    ],
    AdminRole.ASESOR: [
        "properties.read",
        "images.read",
        "leads.read",
        "leads.update",
        "appointments.read",
        "appointments.create",
    ],
}


async def count_active_superadmins(session: AsyncSession) -> int:
    from sqlalchemy import func

    return (await session.execute(
        select(func.count()).select_from(AdminUser).where(
            AdminUser.role == AdminRole.SUPERADMIN, AdminUser.is_active.is_(True)
        )
    )).scalar() or 0


def has_permission(role: AdminRole, permission: str) -> bool:
    allowed = PERMISSIONS.get(role, [])
    if "*" in allowed:
        return True
    for p in allowed:
        if p.endswith(".*"):
            if permission.startswith(p[:-1]):
                return True
        if p == permission:
            return True
    return False


async def require_admin_user(request: Request) -> AdminUser:
    """Dependency to get the current admin user from Bearer header or JWT cookie.

    The JWT issued by POST /auth/login is the single source of authority:
    there is no legacy token fallback that could bypass RBAC.
    """
    token = ""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("admin_access_token", "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    async with AsyncSessionLocal() as session:
        user = await get_admin_user(session, token_data.sub)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo")
        return user


def require_permission(permission: str):
    """Dependency factory to check permission."""
    async def _check(request: Request, user: AdminUser = Depends(require_admin_user)) -> AdminUser:
        if not has_permission(user.role, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permiso requerido: {permission}")
        return user
    return _check


async def log_admin_action(
    admin_user_id: str | None,
    action: str,
    entity: str,
    entity_id: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    result: str = "success",
    error_message: str | None = None,
) -> None:
    from app.database.models import AdminAuditLog

    async with AsyncSessionLocal() as session:
        log_entry = AdminAuditLog(
            admin_user_id=admin_user_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            audit_metadata=metadata or {},
            ip_address=ip_address,
            user_agent=user_agent,
            result=result,
            error_message=error_message,
        )
        session.add(log_entry)
        await session.commit()