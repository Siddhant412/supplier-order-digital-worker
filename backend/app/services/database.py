from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import DateTime, String, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from app.domain.models import AuditEvent, WorkflowRecord, WorkflowStatus, utc_now


class Base(DeclarativeBase):
    pass


def json_column():
    return JSON().with_variant(JSONB, "postgresql")


class WorkflowRow(Base):
    __tablename__ = "workflows"

    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload_hash: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(json_column())


class IdempotencyKeyRow(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ERPUpdateKeyRow(Base):
    __tablename__ = "erp_update_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DatabaseWorkflowStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @classmethod
    def from_engine(cls, engine: Engine) -> "DatabaseWorkflowStore":
        store = cls.__new__(cls)
        store.engine = engine
        store.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        return store

    def initialize(self, attempts: int = 20, delay_seconds: float = 1.0) -> None:
        last_error: OperationalError | None = None
        for _ in range(attempts):
            try:
                Base.metadata.create_all(self.engine)
                return
            except OperationalError as exc:
                last_error = exc
                time.sleep(delay_seconds)
        if last_error:
            raise last_error

    def save_workflow(self, workflow: WorkflowRecord) -> WorkflowRecord:
        workflow.updated_at = utc_now()
        with self.session_factory() as session:
            row = session.get(WorkflowRow, workflow.workflow_id)
            payload = workflow.model_dump(mode="json")
            if row is None:
                row = WorkflowRow(
                    workflow_id=workflow.workflow_id,
                    status=workflow.status.value,
                    created_at=workflow.created_at,
                    updated_at=workflow.updated_at,
                    raw_payload_hash=workflow.raw_payload_hash,
                    idempotency_key=workflow.idempotency_key,
                    duplicate_of=workflow.duplicate_of,
                    data=payload,
                )
                session.add(row)
            else:
                row.status = workflow.status.value
                row.updated_at = workflow.updated_at
                row.idempotency_key = workflow.idempotency_key
                row.duplicate_of = workflow.duplicate_of
                row.data = payload
            session.commit()
        return workflow

    def get_workflow(self, workflow_id: str) -> WorkflowRecord:
        with self.session_factory() as session:
            row = session.get(WorkflowRow, workflow_id)
            if row is None:
                raise KeyError(workflow_id)
            return WorkflowRecord.model_validate(row.data)

    def list_workflows(self) -> list[WorkflowRecord]:
        with self.session_factory() as session:
            rows = session.scalars(select(WorkflowRow).order_by(WorkflowRow.created_at.desc())).all()
            return [WorkflowRecord.model_validate(row.data) for row in rows]

    def index_idempotency_key(self, key: str, workflow_id: str) -> None:
        with self.session_factory() as session:
            existing = session.get(IdempotencyKeyRow, key)
            if existing is not None:
                return
            session.add(IdempotencyKeyRow(key=key, workflow_id=workflow_id))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()

    def find_by_idempotency_key(self, key: str) -> str | None:
        with self.session_factory() as session:
            row = session.get(IdempotencyKeyRow, key)
            return row.workflow_id if row else None

    def has_erp_update(self, key: str) -> bool:
        with self.session_factory() as session:
            return session.get(ERPUpdateKeyRow, key) is not None

    def mark_erp_update(self, key: str, workflow_id: str) -> None:
        with self.session_factory() as session:
            if session.get(ERPUpdateKeyRow, key) is not None:
                return
            session.add(ERPUpdateKeyRow(key=key, workflow_id=workflow_id))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()

    def add_audit(
        self,
        workflow: WorkflowRecord,
        event_type: str,
        summary: str,
        metadata: dict | None = None,
        actor_type: str = "system",
    ) -> AuditEvent:
        event = AuditEvent(
            workflow_id=workflow.workflow_id,
            event_type=event_type,
            correlation_id=workflow.correlation_id,
            actor_type=actor_type,  # type: ignore[arg-type]
            summary=summary,
            metadata=metadata or {},
        )
        workflow.audit_events.append(event)
        self.save_workflow(workflow)
        return event

    def set_status(self, workflow: WorkflowRecord, status: WorkflowStatus, summary: str) -> None:
        workflow.status = status
        self.add_audit(workflow, f"WORKFLOW_{status.value}", summary)
