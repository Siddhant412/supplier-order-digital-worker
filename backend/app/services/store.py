from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import AuditEvent, EvaluationRun, WorkflowRecord, WorkflowStatus, utc_now
from app.services.observability import log_event


logger = logging.getLogger("procureops.audit")


class WorkflowStore(Protocol):
    def save_workflow(self, workflow: WorkflowRecord) -> WorkflowRecord: ...

    def get_workflow(self, workflow_id: str) -> WorkflowRecord: ...

    def list_workflows(self) -> list[WorkflowRecord]: ...

    def index_idempotency_key(self, key: str, workflow_id: str) -> None: ...

    def find_by_idempotency_key(self, key: str) -> str | None: ...

    def has_erp_update(self, key: str) -> bool: ...

    def mark_erp_update(self, key: str, workflow_id: str) -> None: ...

    def save_evaluation_run(self, run: EvaluationRun) -> EvaluationRun: ...

    def get_evaluation_run(self, run_id: str) -> EvaluationRun: ...

    def list_evaluation_runs(self) -> list[EvaluationRun]: ...

    def reset_operational_data(self) -> None: ...

    def add_audit(
        self,
        workflow: WorkflowRecord,
        event_type: str,
        summary: str,
        metadata: dict | None = None,
        actor_type: str = "system",
    ) -> AuditEvent: ...


@dataclass
class InMemoryStore:
    workflows: dict[str, WorkflowRecord] = field(default_factory=dict)
    idempotency_index: dict[str, str] = field(default_factory=dict)
    erp_update_index: set[str] = field(default_factory=set)
    evaluation_runs: dict[str, EvaluationRun] = field(default_factory=dict)

    def save_workflow(self, workflow: WorkflowRecord) -> WorkflowRecord:
        workflow.updated_at = utc_now()
        self.workflows[workflow.workflow_id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> WorkflowRecord:
        return self.workflows[workflow_id]

    def list_workflows(self) -> list[WorkflowRecord]:
        return sorted(self.workflows.values(), key=lambda workflow: workflow.created_at, reverse=True)

    def index_idempotency_key(self, key: str, workflow_id: str) -> None:
        self.idempotency_index[key] = workflow_id

    def find_by_idempotency_key(self, key: str) -> str | None:
        return self.idempotency_index.get(key)

    def has_erp_update(self, key: str) -> bool:
        return key in self.erp_update_index

    def mark_erp_update(self, key: str, workflow_id: str) -> None:
        self.erp_update_index.add(key)

    def save_evaluation_run(self, run: EvaluationRun) -> EvaluationRun:
        self.evaluation_runs[run.run_id] = run
        return run

    def get_evaluation_run(self, run_id: str) -> EvaluationRun:
        return self.evaluation_runs[run_id]

    def list_evaluation_runs(self) -> list[EvaluationRun]:
        return sorted(self.evaluation_runs.values(), key=lambda run: run.created_at, reverse=True)

    def reset_operational_data(self) -> None:
        self.workflows.clear()
        self.idempotency_index.clear()
        self.erp_update_index.clear()
        self.evaluation_runs.clear()

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
