from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, String, Text, Integer, Boolean, Float, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def uid(): return str(uuid4())
def now(): return datetime.now(timezone.utc).timestamp()
class Base(DeclarativeBase): pass
J = JSON().with_variant(JSONB(), "postgresql")

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    external_company_id: Mapped[str | None] = mapped_column(String(100), unique=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(24), default="auditor")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_provider: Mapped[str] = mapped_column(String(24), default="local", server_default="local")
    external_user_id: Mapped[str | None] = mapped_column(String(100))
    external_email: Mapped[str | None] = mapped_column(String(254))
    __table_args__ = (UniqueConstraint("auth_provider", "external_user_id", "organization_id", name="uq_user_external_membership"),)

class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf: Mapped[str] = mapped_column(String(100))
    expires: Mapped[float] = mapped_column(Float)

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(64), index=True)
    created: Mapped[float] = mapped_column(Float, default=now)

class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    period: Mapped[str] = mapped_column(String(7))
    source_mode: Mapped[str] = mapped_column(String(20))
    source_system: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    rejections: Mapped[list] = mapped_column(J, default=list)
    created_at: Mapped[float] = mapped_column(Float, default=now)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    side: Mapped[str] = mapped_column(String(20))
    original_name: Mapped[str] = mapped_column(Text)
    patient_name: Mapped[str] = mapped_column(String(300))
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("batch_id", "side", "sha256"),)

class Pair(Base):
    __tablename__ = "pairs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    original_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), unique=True)
    modified_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), unique=True)
    patient_name: Mapped[str] = mapped_column(String(300))
    confirmed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))

class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    partial_scope: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    report_key: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[float | None] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    __table_args__ = (UniqueConstraint("batch_id", "idempotency_key"),)

class RunCase(Base):
    __tablename__ = "run_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    patient_name: Mapped[str] = mapped_column(String(300))
    original_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    modified_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    comparison: Mapped[dict | None] = mapped_column(J)

class Review(Base):
    __tablename__ = "finding_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("run_cases.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    finding_id: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now)

class ManualFinding(Base):
    __tablename__ = "manual_findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("run_cases.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    data: Mapped[dict] = mapped_column(J)
    created_at: Mapped[float] = mapped_column(Float, default=now)

class Improvement(Base):
    __tablename__ = "improvement_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("run_cases.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    finding_id: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    expected_benefit: Mapped[str] = mapped_column(Text)
    source_system: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    created_at: Mapped[float] = mapped_column(Float, default=now)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[float] = mapped_column(Float, default=now)

def connect(settings):
    settings.validate()
    engine = create_engine(settings.database_url, pool_pre_ping=True, **({"connect_args": {"check_same_thread": False}} if settings.testing and settings.database_url.startswith("sqlite") else {}))
    return engine, sessionmaker(bind=engine, expire_on_commit=False, info={"settings": settings})

def event(db, user, action, target):
    db.add(AuditEvent(user_id=user.id if user else None, action=action, target_id=str(target)))
