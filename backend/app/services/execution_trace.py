from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.models import AuditEvent, ExecutionTraceStep, PolicyDecisionType, WorkflowRecord, WorkflowStatus


TraceStatus = Literal["completed", "waiting", "blocked", "failed", "skipped"]
TraceOwner = Literal["deterministic", "llm", "human", "system"]


@dataclass(frozen=True)
class TraceDefinition:
    step_id: str
    label: str
    langgraph_node: str | None
    owner: TraceOwner
    event_types: tuple[str, ...]


TRACE_DEFINITIONS = (
    TraceDefinition("ingest", "Receive supplier confirmation", None, "system", ("WORKFLOW_RECEIVED",)),
    TraceDefinition("parse", "Parse X12 855 syntax", "parse_edi_syntax", "deterministic", ("EDI_SYNTAX_PARSED",)),
    TraceDefinition(
        "interpret",
        "Interpret EDI semantics",
        "interpret_edi_semantics",
        "deterministic",
        ("EDI_SEMANTICS_INTERPRETED", "DUPLICATE_DETECTED", "MANUAL_REVIEW_REQUIRED", "DEAD_LETTER"),
    ),
    TraceDefinition(
        "retrieve_po",
        "Retrieve purchase order",
        "retrieve_purchase_order",
        "deterministic",
        ("PURCHASE_ORDER_RETRIEVED", "ERP_LOOKUP_RETRY", "ERP_LOOKUP_RETRY_EXHAUSTED"),
    ),
    TraceDefinition("compare", "Compare confirmation to PO", "compare_lines", "deterministic", ("LINES_COMPARED",)),
    TraceDefinition("impact", "Assess inventory impact", "assess_impact", "deterministic", ("IMPACT_ASSESSED",)),
    TraceDefinition("policy", "Evaluate policy guardrails", "evaluate_policy", "deterministic", ("POLICY_DECISION_RECORDED",)),
    TraceDefinition(
        "approval",
        "Human approval gate",
        "wait_for_approval",
        "human",
        (
            "AWAITING_APPROVAL",
            "APPROVAL_RECORDED",
            "APPROVAL_REJECTED",
            "CLARIFICATION_REQUESTED",
            "MANUAL_REVIEW_REJECTED",
            "MANUAL_REVIEW_CLARIFICATION_REQUESTED",
        ),
    ),
    TraceDefinition(
        "erp_update",
        "Apply ERP update",
        "apply_erp_update",
        "deterministic",
        ("ERP_UPDATED", "ERP_UPDATE_SKIPPED"),
    ),
    TraceDefinition(
        "notify",
        "Notify supplier",
        "notify_supplier",
        "deterministic",
        ("SUPPLIER_NOTIFIED", "SUPPLIER_NOTIFICATION_FAILED", "SUPPLIER_NOTIFICATION_RETRY_STARTED"),
    ),
    TraceDefinition("brief", "Generate operator brief", None, "llm", ("OPERATOR_BRIEF_GENERATED",)),
    TraceDefinition("complete", "Complete workflow", "complete", "system", ("WORKFLOW_COMPLETED",)),
)

BLOCKING_STATUSES = {
    WorkflowStatus.MANUAL_REVIEW,
    WorkflowStatus.DEAD_LETTER,
    WorkflowStatus.REJECTED,
    WorkflowStatus.CLARIFICATION_REQUESTED,
}

FAILED_EVENTS = {"ERP_LOOKUP_RETRY_EXHAUSTED", "SUPPLIER_NOTIFICATION_FAILED"}


def build_execution_trace(workflow: WorkflowRecord) -> list[ExecutionTraceStep]:
    events_by_type = _events_by_type(workflow.audit_events)
    return [_build_step(definition, workflow, events_by_type) for definition in TRACE_DEFINITIONS]


def _build_step(
    definition: TraceDefinition,
    workflow: WorkflowRecord,
    events_by_type: dict[str, list[AuditEvent]],
) -> ExecutionTraceStep:
    event = _latest_event(definition.event_types, events_by_type)
    owner = _owner(definition, event)
    status = _status(definition, workflow, event)
    return ExecutionTraceStep(
        step_id=definition.step_id,
        label=definition.label,
        langgraph_node=definition.langgraph_node,
        owner=owner,
        status=status,
        event_type=event.event_type if event else None,
        summary=_summary(definition, workflow, event, status),
        occurred_at=event.occurred_at if event else None,
        metadata=event.metadata if event else {},
    )


def _events_by_type(events: list[AuditEvent]) -> dict[str, list[AuditEvent]]:
    grouped: dict[str, list[AuditEvent]] = {}
    for event in events:
        grouped.setdefault(event.event_type, []).append(event)
    return grouped


def _latest_event(event_types: tuple[str, ...], events_by_type: dict[str, list[AuditEvent]]) -> AuditEvent | None:
    matches = [event for event_type in event_types for event in events_by_type.get(event_type, [])]
    if not matches:
        return None
    return max(matches, key=lambda event: (event.occurred_at, event.event_id))


def _owner(definition: TraceDefinition, event: AuditEvent | None) -> TraceOwner:
    if definition.step_id == "brief" and event:
        source = event.metadata.get("source")
        if source == "deterministic":
            return "deterministic"
    return definition.owner


def _status(definition: TraceDefinition, workflow: WorkflowRecord, event: AuditEvent | None) -> TraceStatus:
    if event and event.event_type in FAILED_EVENTS:
        return "failed"
    if definition.step_id == "approval":
        return _approval_status(workflow, event)
    if definition.step_id == "erp_update":
        return _erp_update_status(workflow, event)
    if definition.step_id == "notify":
        return _notification_status(workflow, event)
    if definition.step_id == "brief" and event is None:
        return "skipped"
    if event:
        if definition.step_id == "interpret" and workflow.status in {WorkflowStatus.MANUAL_REVIEW, WorkflowStatus.DEAD_LETTER}:
            return "blocked"
        return "completed"
    if _workflow_blocked_before(definition.step_id, workflow):
        return "skipped"
    return "skipped"


def _approval_status(workflow: WorkflowRecord, event: AuditEvent | None) -> TraceStatus:
    if workflow.status == WorkflowStatus.AWAITING_APPROVAL:
        return "waiting"
    if event and event.event_type == "AWAITING_APPROVAL":
        return "waiting"
    if event:
        return "completed"
    if workflow.policy_decision and workflow.policy_decision.decision == PolicyDecisionType.AUTO_APPROVE:
        return "skipped"
    if workflow.status in BLOCKING_STATUSES:
        return "blocked"
    return "skipped"


def _erp_update_status(workflow: WorkflowRecord, event: AuditEvent | None) -> TraceStatus:
    if event:
        return "completed"
    if workflow.status == WorkflowStatus.AWAITING_APPROVAL:
        return "waiting"
    if workflow.status in BLOCKING_STATUSES:
        return "blocked"
    return "skipped"


def _notification_status(workflow: WorkflowRecord, event: AuditEvent | None) -> TraceStatus:
    if event and event.event_type == "SUPPLIER_NOTIFICATION_FAILED":
        return "failed"
    if event:
        return "completed"
    if workflow.status == WorkflowStatus.RETRY_PENDING:
        return "waiting"
    if workflow.status in {WorkflowStatus.AWAITING_APPROVAL, *BLOCKING_STATUSES}:
        return "skipped"
    return "skipped"


def _workflow_blocked_before(step_id: str, workflow: WorkflowRecord) -> bool:
    blocked_after_interpretation = {"retrieve_po", "compare", "impact", "policy", "approval", "erp_update", "notify", "complete"}
    if workflow.status in {WorkflowStatus.MANUAL_REVIEW, WorkflowStatus.DEAD_LETTER} and step_id in blocked_after_interpretation:
        return True
    return workflow.status in {WorkflowStatus.REJECTED, WorkflowStatus.CLARIFICATION_REQUESTED} and step_id in {
        "erp_update",
        "complete",
    }


def _summary(
    definition: TraceDefinition,
    workflow: WorkflowRecord,
    event: AuditEvent | None,
    status: TraceStatus,
) -> str:
    if event:
        return event.summary
    if definition.step_id == "approval" and workflow.policy_decision:
        if workflow.policy_decision.decision == PolicyDecisionType.AUTO_APPROVE:
            return "Policy allowed the workflow to continue without human approval."
        if status == "waiting":
            return "Policy requires human approval before ERP mutation."
    if definition.step_id == "erp_update" and status == "waiting":
        return "ERP update is paused until the approval gate is resolved."
    if definition.step_id == "brief":
        return "Optional operator brief has not been generated for this workflow."
    if status == "blocked":
        return "Workflow is blocked before this step."
    return "Step was not reached in this workflow path."
