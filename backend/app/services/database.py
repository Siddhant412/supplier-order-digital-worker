from __future__ import annotations

import logging
import time
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, create_engine, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from app.domain.models import (
    AuditEvent,
    EvaluationRun,
    PolicyConfig,
    PolicyCreateRequest,
    PolicyUpdateRequest,
    ProfileCreateRequest,
    ProfileStatus,
    ProfileUpdateRequest,
    TradingPartnerProfile,
    WorkflowRecord,
    WorkflowStatus,
    new_id,
    utc_now,
)
from app.services.observability import log_event
from app.services.profiles import seed_profile
from app.services.policies import seed_policy


logger = logging.getLogger("procureops.audit")


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


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_type: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(String(1024))
    metadata_json: Mapped[dict] = mapped_column(json_column())


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


class TradingPartnerProfileRow(Base):
    __tablename__ = "trading_partner_profiles"

    profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), index=True)
    transaction_type: Mapped[str] = mapped_column(String(16), index=True)
    edi_version: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict] = mapped_column(json_column())


class EvaluationRunRow(Base):
    __tablename__ = "evaluation_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    total: Mapped[int] = mapped_column(Integer)
    passed: Mapped[int] = mapped_column(Integer)
    failed: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(json_column())


class PolicyConfigRow(Base):
    __tablename__ = "policy_configs"

    policy_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict] = mapped_column(json_column())


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
            payload = self._workflow_payload(workflow)
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
            return self._workflow_from_row(session, row)

    def list_workflows(self) -> list[WorkflowRecord]:
        with self.session_factory() as session:
            rows = session.scalars(select(WorkflowRow).order_by(WorkflowRow.created_at.desc())).all()
            return [self._workflow_from_row(session, row) for row in rows]

    def index_idempotency_key(self, key: str, workflow_id: str) -> None:
        with self.session_factory() as session:
            existing = session.get(IdempotencyKeyRow, key)
            if existing is not None:
                existing.workflow_id = workflow_id
                session.commit()
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

    def save_evaluation_run(self, run: EvaluationRun) -> EvaluationRun:
        with self.session_factory() as session:
            row = session.get(EvaluationRunRow, run.run_id)
            payload = run.model_dump(mode="json")
            if row is None:
                row = EvaluationRunRow(
                    run_id=run.run_id,
                    status=run.status.value,
                    created_at=run.created_at,
                    total=run.total,
                    passed=run.passed,
                    failed=run.failed,
                    data=payload,
                )
                session.add(row)
            else:
                row.status = run.status.value
                row.total = run.total
                row.passed = run.passed
                row.failed = run.failed
                row.data = payload
            session.commit()
        return run

    def get_evaluation_run(self, run_id: str) -> EvaluationRun:
        with self.session_factory() as session:
            row = session.get(EvaluationRunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            return EvaluationRun.model_validate(row.data)

    def list_evaluation_runs(self) -> list[EvaluationRun]:
        with self.session_factory() as session:
            rows = session.scalars(select(EvaluationRunRow).order_by(EvaluationRunRow.created_at.desc())).all()
            return [EvaluationRun.model_validate(row.data) for row in rows]

    def reset_operational_data(self) -> None:
        with self.session_factory() as session:
            for table in (
                AuditEventRow,
                IdempotencyKeyRow,
                ERPUpdateKeyRow,
                EvaluationRunRow,
                WorkflowRow,
            ):
                session.execute(delete(table))
            session.commit()

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
        with self.session_factory() as session:
            for audit_event in workflow.audit_events:
                if session.get(AuditEventRow, audit_event.event_id) is None:
                    session.add(self._row_from_audit_event(audit_event))
            session.commit()
        log_event(
            logger,
            logging.INFO,
            "audit_event_recorded",
            workflow_id=event.workflow_id,
            event_id=event.event_id,
            event_type=event.event_type,
            actor_type=event.actor_type,
            correlation_id=event.correlation_id,
        )
        self.save_workflow(workflow)
        return event

    def set_status(self, workflow: WorkflowRecord, status: WorkflowStatus, summary: str) -> None:
        workflow.status = status
        self.add_audit(workflow, f"WORKFLOW_{status.value}", summary)

    def _workflow_payload(self, workflow: WorkflowRecord) -> dict:
        payload = workflow.model_dump(mode="json")
        payload["audit_events"] = []
        return payload

    def _workflow_from_row(self, session: Session, row: WorkflowRow) -> WorkflowRecord:
        workflow = WorkflowRecord.model_validate(row.data)
        audit_events = self._audit_events_for_workflow(session, workflow.workflow_id)
        if audit_events:
            workflow.audit_events = audit_events
        return workflow

    def _audit_events_for_workflow(self, session: Session, workflow_id: str) -> list[AuditEvent]:
        rows = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.workflow_id == workflow_id)
            .order_by(AuditEventRow.occurred_at.asc(), AuditEventRow.event_id.asc())
        ).all()
        return [
            AuditEvent(
                event_id=row.event_id,
                workflow_id=row.workflow_id,
                event_type=row.event_type,
                occurred_at=row.occurred_at,
                correlation_id=row.correlation_id,
                actor_type=row.actor_type,  # type: ignore[arg-type]
                summary=row.summary,
                metadata=row.metadata_json,
            )
            for row in rows
        ]

    def _row_from_audit_event(self, event: AuditEvent) -> AuditEventRow:
        return AuditEventRow(
            event_id=event.event_id,
            workflow_id=event.workflow_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            correlation_id=event.correlation_id,
            actor_type=event.actor_type,
            summary=event.summary[:1024],
            metadata_json=event.metadata,
        )


class DatabaseTradingPartnerProfileRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @classmethod
    def from_engine(cls, engine: Engine) -> "DatabaseTradingPartnerProfileRepository":
        repo = cls.__new__(cls)
        repo.engine = engine
        repo.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        return repo

    def initialize(self, attempts: int = 20, delay_seconds: float = 1.0) -> None:
        last_error: OperationalError | None = None
        for _ in range(attempts):
            try:
                Base.metadata.create_all(self.engine)
                self._seed_if_empty()
                return
            except OperationalError as exc:
                last_error = exc
                time.sleep(delay_seconds)
        if last_error:
            raise last_error

    def get(self, supplier_id: str, transaction_type: str, edi_version: str) -> TradingPartnerProfile | None:
        with self.session_factory() as session:
            rows = session.scalars(
                select(TradingPartnerProfileRow)
                .where(
                    TradingPartnerProfileRow.supplier_id == supplier_id,
                    TradingPartnerProfileRow.transaction_type == transaction_type,
                    TradingPartnerProfileRow.edi_version == edi_version,
                    TradingPartnerProfileRow.status == ProfileStatus.PUBLISHED.value,
                )
                .order_by(TradingPartnerProfileRow.version.desc())
            ).all()
            if not rows:
                return None
            return TradingPartnerProfile.model_validate(rows[0].data)

    def get_by_id(self, profile_id: str) -> TradingPartnerProfile:
        with self.session_factory() as session:
            row = session.get(TradingPartnerProfileRow, profile_id)
            if row is None:
                raise KeyError(profile_id)
            return TradingPartnerProfile.model_validate(row.data)

    def list(self) -> list[TradingPartnerProfile]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(TradingPartnerProfileRow).order_by(
                    TradingPartnerProfileRow.supplier_id,
                    TradingPartnerProfileRow.transaction_type,
                    TradingPartnerProfileRow.edi_version,
                    TradingPartnerProfileRow.version.desc(),
                )
            ).all()
            return [TradingPartnerProfile.model_validate(row.data) for row in rows]

    def create(self, request: ProfileCreateRequest) -> TradingPartnerProfile:
        profile = TradingPartnerProfile(
            profile_id=self._new_profile_id(request.supplier_id, request.transaction_type, request.edi_version, 1),
            supplier_id=request.supplier_id,
            transaction_type=request.transaction_type,
            edi_version=request.edi_version,
            version=1,
            status=ProfileStatus.DRAFT,
            date_qualifiers=request.date_qualifiers,
            ack_codes=request.ack_codes,
            repeated_ack_policy=request.repeated_ack_policy,
            unknown_qualifier_policy=request.unknown_qualifier_policy,
        )
        self._save(profile)
        return profile

    def update(self, profile_id: str, request: ProfileUpdateRequest) -> TradingPartnerProfile:
        existing = self.get_by_id(profile_id)
        profile = existing if existing.status == ProfileStatus.DRAFT else self._draft_from(existing)
        if request.date_qualifiers is not None:
            profile.date_qualifiers = request.date_qualifiers
        if request.ack_codes is not None:
            profile.ack_codes = request.ack_codes
        if request.repeated_ack_policy is not None:
            profile.repeated_ack_policy = request.repeated_ack_policy
        if request.unknown_qualifier_policy is not None:
            profile.unknown_qualifier_policy = request.unknown_qualifier_policy
        profile.updated_at = utc_now()
        self._save(profile)
        return profile

    def publish(self, profile_id: str) -> TradingPartnerProfile:
        profile = self.get_by_id(profile_id)
        now = utc_now()
        with self.session_factory() as session:
            rows = session.scalars(
                select(TradingPartnerProfileRow).where(
                    TradingPartnerProfileRow.supplier_id == profile.supplier_id,
                    TradingPartnerProfileRow.transaction_type == profile.transaction_type,
                    TradingPartnerProfileRow.edi_version == profile.edi_version,
                    TradingPartnerProfileRow.status == ProfileStatus.PUBLISHED.value,
                )
            ).all()
            for row in rows:
                if row.profile_id == profile.profile_id:
                    continue
                old = TradingPartnerProfile.model_validate(row.data)
                old.status = ProfileStatus.ARCHIVED
                old.archived_at = now
                old.updated_at = now
                self._update_row(row, old)
            row = session.get(TradingPartnerProfileRow, profile.profile_id)
            if row is None:
                raise KeyError(profile.profile_id)
            profile.status = ProfileStatus.PUBLISHED
            profile.published_at = now
            profile.archived_at = None
            profile.updated_at = now
            self._update_row(row, profile)
            session.commit()
        return profile

    def archive(self, profile_id: str) -> TradingPartnerProfile:
        profile = self.get_by_id(profile_id)
        profile.status = ProfileStatus.ARCHIVED
        profile.archived_at = utc_now()
        profile.updated_at = profile.archived_at
        self._save(profile)
        return profile

    def _seed_if_empty(self) -> None:
        with self.session_factory() as session:
            existing = session.scalars(select(TradingPartnerProfileRow).limit(1)).first()
            if existing is not None:
                return
            profile = seed_profile()
            session.add(self._row_from_profile(profile))
            session.commit()

    def _save(self, profile: TradingPartnerProfile) -> None:
        with self.session_factory() as session:
            row = session.get(TradingPartnerProfileRow, profile.profile_id)
            if row is None:
                row = self._row_from_profile(profile)
                session.add(row)
            else:
                self._update_row(row, profile)
            session.commit()

    def _draft_from(self, profile: TradingPartnerProfile) -> TradingPartnerProfile:
        next_version = self._next_version(profile.supplier_id, profile.transaction_type, profile.edi_version)
        return profile.model_copy(
            deep=True,
            update={
                "profile_id": self._new_profile_id(
                    profile.supplier_id,
                    profile.transaction_type,
                    profile.edi_version,
                    next_version,
                ),
                "version": next_version,
                "status": ProfileStatus.DRAFT,
                "published_at": None,
                "archived_at": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
        )

    def _next_version(self, supplier_id: str, transaction_type: str, edi_version: str) -> int:
        with self.session_factory() as session:
            rows = session.scalars(
                select(TradingPartnerProfileRow.version).where(
                    TradingPartnerProfileRow.supplier_id == supplier_id,
                    TradingPartnerProfileRow.transaction_type == transaction_type,
                    TradingPartnerProfileRow.edi_version == edi_version,
                )
            ).all()
            return max(rows or [0]) + 1

    def _new_profile_id(self, supplier_id: str, transaction_type: str, edi_version: str, version: int) -> str:
        return f"{supplier_id}:{transaction_type}:{edi_version}:v{version}-{new_id('PROF').split('-', 1)[1]}"

    def _row_from_profile(self, profile: TradingPartnerProfile) -> TradingPartnerProfileRow:
        return TradingPartnerProfileRow(
            profile_id=profile.profile_id,
            supplier_id=profile.supplier_id,
            transaction_type=profile.transaction_type,
            edi_version=profile.edi_version,
            version=profile.version,
            status=profile.status.value,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            data=profile.model_dump(mode="json"),
        )

    def _update_row(self, row: TradingPartnerProfileRow, profile: TradingPartnerProfile) -> None:
        row.supplier_id = profile.supplier_id
        row.transaction_type = profile.transaction_type
        row.edi_version = profile.edi_version
        row.version = profile.version
        row.status = profile.status.value
        row.updated_at = profile.updated_at
        row.data = profile.model_dump(mode="json")


class DatabasePolicyConfigRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @classmethod
    def from_engine(cls, engine: Engine) -> "DatabasePolicyConfigRepository":
        repo = cls.__new__(cls)
        repo.engine = engine
        repo.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        return repo

    def initialize(self, attempts: int = 20, delay_seconds: float = 1.0) -> None:
        last_error: OperationalError | None = None
        for _ in range(attempts):
            try:
                Base.metadata.create_all(self.engine)
                self._seed_if_empty()
                return
            except OperationalError as exc:
                last_error = exc
                time.sleep(delay_seconds)
        if last_error:
            raise last_error

    def get_active(self) -> PolicyConfig:
        with self.session_factory() as session:
            rows = session.scalars(
                select(PolicyConfigRow)
                .where(PolicyConfigRow.status == ProfileStatus.PUBLISHED.value)
                .order_by(PolicyConfigRow.version.desc())
            ).all()
            if not rows:
                raise KeyError("No published policy found.")
            return PolicyConfig.model_validate(rows[0].data)

    def get_by_id(self, policy_id: str) -> PolicyConfig:
        with self.session_factory() as session:
            row = session.get(PolicyConfigRow, policy_id)
            if row is None:
                raise KeyError(policy_id)
            return PolicyConfig.model_validate(row.data)

    def list(self) -> list[PolicyConfig]:
        with self.session_factory() as session:
            rows = session.scalars(select(PolicyConfigRow).order_by(PolicyConfigRow.version.desc())).all()
            return [PolicyConfig.model_validate(row.data) for row in rows]

    def create(self, request: PolicyCreateRequest) -> PolicyConfig:
        policy = PolicyConfig(
            policy_id=self._new_policy_id(1),
            version=1,
            status=ProfileStatus.DRAFT,
            policy_version=request.policy_version,
            exact_match_auto_approve=request.exact_match_auto_approve,
            maximum_price_increase_percent=request.maximum_price_increase_percent,
            maximum_delivery_delay_days=request.maximum_delivery_delay_days,
            maximum_order_value=request.maximum_order_value,
            require_no_stockout_impact=request.require_no_stockout_impact,
        )
        self._save(policy)
        return policy

    def update(self, policy_id: str, request: PolicyUpdateRequest) -> PolicyConfig:
        existing = self.get_by_id(policy_id)
        policy = existing if existing.status == ProfileStatus.DRAFT else self._draft_from(existing)
        for field, value in request.model_dump(exclude_unset=True).items():
            setattr(policy, field, value)
        policy.updated_at = utc_now()
        self._save(policy)
        return policy

    def publish(self, policy_id: str) -> PolicyConfig:
        policy = self.get_by_id(policy_id)
        now = utc_now()
        with self.session_factory() as session:
            rows = session.scalars(
                select(PolicyConfigRow).where(PolicyConfigRow.status == ProfileStatus.PUBLISHED.value)
            ).all()
            for row in rows:
                if row.policy_id == policy.policy_id:
                    continue
                old = PolicyConfig.model_validate(row.data)
                old.status = ProfileStatus.ARCHIVED
                old.archived_at = now
                old.updated_at = now
                self._update_row(row, old)
            row = session.get(PolicyConfigRow, policy.policy_id)
            if row is None:
                raise KeyError(policy.policy_id)
            policy.status = ProfileStatus.PUBLISHED
            policy.published_at = now
            policy.archived_at = None
            policy.updated_at = now
            if policy.policy_version.startswith("draft-"):
                policy.policy_version = f"policy-v{policy.version}"
            self._update_row(row, policy)
            session.commit()
        return policy

    def archive(self, policy_id: str) -> PolicyConfig:
        policy = self.get_by_id(policy_id)
        policy.status = ProfileStatus.ARCHIVED
        policy.archived_at = utc_now()
        policy.updated_at = policy.archived_at
        self._save(policy)
        return policy

    def _seed_if_empty(self) -> None:
        with self.session_factory() as session:
            existing = session.scalars(select(PolicyConfigRow).limit(1)).first()
            if existing is not None:
                return
            policy = seed_policy()
            session.add(self._row_from_policy(policy))
            session.commit()

    def _save(self, policy: PolicyConfig) -> None:
        with self.session_factory() as session:
            row = session.get(PolicyConfigRow, policy.policy_id)
            if row is None:
                row = self._row_from_policy(policy)
                session.add(row)
            else:
                self._update_row(row, policy)
            session.commit()

    def _draft_from(self, policy: PolicyConfig) -> PolicyConfig:
        version = self._next_version()
        return policy.model_copy(
            deep=True,
            update={
                "policy_id": self._new_policy_id(version),
                "version": version,
                "status": ProfileStatus.DRAFT,
                "policy_version": f"draft-v{version}",
                "published_at": None,
                "archived_at": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
        )

    def _next_version(self) -> int:
        with self.session_factory() as session:
            rows = session.scalars(select(PolicyConfigRow.version)).all()
            return max(rows or [0]) + 1

    def _new_policy_id(self, version: int) -> str:
        return f"POLICY:v{version}-{new_id('POL').split('-', 1)[1]}"

    def _row_from_policy(self, policy: PolicyConfig) -> PolicyConfigRow:
        return PolicyConfigRow(
            policy_id=policy.policy_id,
            version=policy.version,
            status=policy.status.value,
            created_at=policy.created_at,
            updated_at=policy.updated_at,
            data=policy.model_dump(mode="json"),
        )

    def _update_row(self, row: PolicyConfigRow, policy: PolicyConfig) -> None:
        row.version = policy.version
        row.status = policy.status.value
        row.updated_at = policy.updated_at
        row.data = policy.model_dump(mode="json")
