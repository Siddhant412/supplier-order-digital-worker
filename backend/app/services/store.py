from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import AuditEvent, WorkflowRecord, WorkflowStatus, utc_now


@dataclass
class InMemoryStore:
    workflows: dict[str, WorkflowRecord] = field(default_factory=dict)
    idempotency_index: dict[str, str] = field(default_factory=dict)
    erp_update_index: set[str] = field(default_factory=set)

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
