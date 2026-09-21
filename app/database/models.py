"""Domain models. Schema is managed by Alembic migrations (migrations/versions)."""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:
        return self.value


def sa_enum(enum_cls, **kw):
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        **kw,
    )


# ----------------------------------------------------------------- enums
class PropertyType(StrEnum):
    HOUSE = "casa"
    APARTMENT = "apartamento"
    LOT = "lote"
    STORE = "local"
    OFFICE = "oficina"
    FARM = "finca"
    PROJECT = "proyecto"


class Operation(StrEnum):
    SALE = "SALE"
    RENT = "RENT"
    # future: TEMPORARY_RENT, PROJECT


class PropertyStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    INACTIVE = "INACTIVE"


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class Role(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class LeadStatus(StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    INTERESTED = "INTERESTED"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    NEGOTIATION = "NEGOTIATION"
    CLOSED = "CLOSED"
    LOST = "LOST"


class AppointmentStatus(StrEnum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class AdminRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    EDITOR = "editor"
    ASESOR = "asesor"


# ----------------------------------------------------------------- Admin
class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[AdminRole] = mapped_column(sa_enum(AdminRole), default=AdminRole.ASESOR)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "name": self.name,
            "role": self.role.value,
            "is_active": self.is_active,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="success")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CmsContentType(StrEnum):
    TEXT = "text"
    HTML = "html"
    JSON = "json"
    IMAGE = "image"
    NUMBER = "number"
    BOOLEAN = "boolean"


class CmsContent(Base):
    __tablename__ = "cms_content"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[CmsContentType] = mapped_column(sa_enum(CmsContentType))
    value: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    group: Mapped[str] = mapped_column(String(50), default="general")
    is_public: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "key": self.key,
            "type": self.type.value,
            "value": self.value,
            "label": self.label,
            "description": self.description,
            "group": self.group,
            "is_public": self.is_public,
        }


class SystemSettingType(StrEnum):
    TEXT = "text"
    HTML = "html"
    JSON = "json"
    NUMBER = "number"
    BOOLEAN = "boolean"


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[SystemSettingType] = mapped_column(sa_enum(SystemSettingType))
    value: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="general")
    is_editable: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "key": self.key,
            "type": self.type.value,
            "value": self.value,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "is_editable": self.is_editable,
        }


# ----------------------------------------------------------------- inventory
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    properties: Mapped[list[Property]] = relationship(back_populates="project")


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        Index("ix_properties_price", "price"),
        Index("ix_properties_city", "city"),
        Index("ix_properties_type", "property_type"),
        Index("ix_properties_operation", "operation"),
        Index("ix_properties_bedrooms", "bedrooms"),
        Index("ix_properties_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    property_type: Mapped[PropertyType] = mapped_column(sa_enum(PropertyType))
    operation: Mapped[Operation] = mapped_column(sa_enum(Operation), default=Operation.SALE)
    price: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="COP")
    city: Mapped[str] = mapped_column(String(80), default="")
    neighborhood: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(240), default="")
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking_spaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[PropertyStatus] = mapped_column(
        sa_enum(PropertyStatus), default=PropertyStatus.AVAILABLE, index=True
    )
    features: Mapped[list] = mapped_column(JSONB, default=list)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    # full-text search over title/description/neighborhood/city (generated)
    search_vector: Mapped[object | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('spanish', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('spanish', coalesce(neighborhood, '')), 'B') || "
            "setweight(to_tsvector('spanish', coalesce(city, '')), 'B') || "
            "setweight(to_tsvector('spanish', coalesce(description, '')), 'C')",
            persisted=True,
        ),
    )
    # semantic column for pgvector (dim fixed by migration; must match EMBEDDING_DIM)
    title_embedding: Mapped[object | None] = mapped_column(HALFVEC(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    project: Mapped[Project | None] = relationship(back_populates="properties", lazy="selectin")

    def to_dict(self) -> dict:
        project_name = None
        # Safely access project.name without triggering lazy load on detached instances
        try:
            if self.project is not None:
                project_name = self.project.name
        except Exception:
            # DetachedInstanceError or similar - project not loaded and session closed
            pass
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "description": self.description,
            "property_type": self.property_type.value,
            "operation": self.operation.value,
            "price": float(self.price) if self.price is not None else None,
            "currency": self.currency,
            "city": self.city,
            "neighborhood": self.neighborhood,
            "address": self.address,
            "area_m2": float(self.area_m2) if self.area_m2 is not None else None,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "parking_spaces": self.parking_spaces,
            "status": self.status.value,
            "features": self.features or [],
            "project": project_name,
            "latitude": float(self.latitude) if self.latitude is not None else None,
            "longitude": float(self.longitude) if self.longitude is not None else None,
        }


# ----------------------------------------------------------------- RAG
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(300), default="")
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    document_type: Mapped[str] = mapped_column(String(40), default="general")
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        sa_enum(DocumentStatus), default=DocumentStatus.PENDING
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    embedding_version: Mapped[str] = mapped_column(String(80), default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "title": self.title,
            "filename": self.filename,
            "file_hash": self.file_hash,
            "document_type": self.document_type,
            "status": self.status.value,
            "version": self.version,
            "embedding_version": self.embedding_version,
            "chunk_count": self.chunk_count,
            "error": self.error,
            "size_bytes": self.size_bytes,
            "property_id": str(self.property_id) if self.property_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_chunks_document", "document_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_type: Mapped[str] = mapped_column(String(40), default="general")
    filename: Mapped[str] = mapped_column(String(300), default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(HALFVEC(2048), nullable=True)
    chunk_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    document: Mapped[Document] = relationship(back_populates="chunks")


# ----------------------------------------------------------------- users / memory
class AppUser(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(120), default="")
    first_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    preference: Mapped[UserPreference | None] = relationship(
        back_populates="user", uselist=False
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    city: Mapped[str] = mapped_column(String(80), default="")
    property_type: Mapped[str] = mapped_column(String(40), default="")
    operation: Mapped[str] = mapped_column(String(20), default="")
    min_budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    goal: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    user: Mapped[AppUser] = relationship(back_populates="preference")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation", "conversation_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[Role] = mapped_column(sa_enum(Role))
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiEvent(Base):
    __tablename__ = "ai_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(32), default="")
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    intent: Mapped[str] = mapped_column(String(40), default="")
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    tool_calls: Mapped[list] = mapped_column(JSONB, default=list)
    retrieved_property_ids: Mapped[list] = mapped_column(JSONB, default=list)
    retrieved_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list)
    response: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ----------------------------------------------------------------- CRM
class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "property_id", name="uq_user_property"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), default="")
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[LeadStatus] = mapped_column(
        sa_enum(LeadStatus), default=LeadStatus.NEW, index=True
    )
    budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[object] = mapped_column(JSONB, default=dict)
    description: Mapped[str] = mapped_column(String(240), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointments_slot", "property_id", "scheduled_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE")
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[AppointmentStatus] = mapped_column(
        sa_enum(AppointmentStatus), default=AppointmentStatus.REQUESTED, index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )



