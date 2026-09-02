"""SQLAlchemy tables. Nested shapes live in a `data` JSON column (dumps of the
pydantic models in core/models.py); columns exist for everything we filter on."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SeekerRow(Base):
    __tablename__ = "seekers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    external_ref: Mapped[str] = mapped_column(String(255), default="")
    consent_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProfileRow(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seeker_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("seeker_id", "version"),)


class PreferencesRow(Base):
    __tablename__ = "preferences"
    seeker_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class PostingRow(Base):
    __tablename__ = "postings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    canonical_url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64))
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)


class MatchRow(Base):
    __tablename__ = "matches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    seeker_id: Mapped[str] = mapped_column(String(32), index=True)
    posting_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    rerank_score: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("seeker_id", "posting_id"),)


class ResumeRow(Base):
    __tablename__ = "resumes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    seeker_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8))
    posting_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)


class ApplicationRow(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    seeker_id: Mapped[str] = mapped_column(String(32), index=True)
    posting_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("seeker_id", "posting_id"),)


class AuditRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    seeker_id: Mapped[str] = mapped_column(String(32), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(32), index=True)
    event: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(128))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class LLMUsageRow(Base):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seeker_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    component: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    seeker_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    application_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    status: Mapped[str] = mapped_column(String(24), index=True, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(String(2048), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class DeadLetterRow(Base):
    __tablename__ = "dead_letters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    seeker_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    application_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(String(2048), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class DomainThrottleRow(Base):
    __tablename__ = "domain_throttles"
    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
