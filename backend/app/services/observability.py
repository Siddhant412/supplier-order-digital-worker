from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.domain.models import WorkflowRecord, WorkflowStatus


TERMINAL_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.REJECTED,
    WorkflowStatus.CLARIFICATION_REQUESTED,
    WorkflowStatus.DEAD_LETTER,
    WorkflowStatus.FAILED,
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "props", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_json_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_procureops_json_logging", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root._procureops_json_logging = True  # type: ignore[attr-defined]


def log_event(logger: logging.Logger, level: int, message: str, **props: Any) -> None:
    logger.log(level, message, extra={"props": props})


def compute_metrics(workflows: list[WorkflowRecord]) -> dict[str, Any]:
    total = len(workflows)
    completed = [workflow for workflow in workflows if workflow.status == WorkflowStatus.COMPLETED]
    terminal = [workflow for workflow in workflows if workflow.status in TERMINAL_STATUSES]
    auto_completed = [
        workflow
        for workflow in workflows
        if workflow.policy_decision and workflow.policy_decision.decision == "AUTO_APPROVE"
    ]
    awaiting = [workflow for workflow in workflows if workflow.status == WorkflowStatus.AWAITING_APPROVAL]
    manual = [workflow for workflow in workflows if workflow.status == WorkflowStatus.MANUAL_REVIEW]
    retry_pending = [workflow for workflow in workflows if workflow.status == WorkflowStatus.RETRY_PENDING]
    dead_letter = [workflow for workflow in workflows if workflow.status == WorkflowStatus.DEAD_LETTER]
    rejected = [workflow for workflow in workflows if workflow.status == WorkflowStatus.REJECTED]
    clarification = [workflow for workflow in workflows if workflow.status == WorkflowStatus.CLARIFICATION_REQUESTED]
    failed_notifications = [
        workflow for workflow in workflows if workflow.supplier_response and workflow.supplier_response.status == "failed"
    ]
    workflows_with_approval = [workflow for workflow in workflows if workflow.approval_history]
    retry_workflows = [workflow for workflow in workflows if _has_retry_event(workflow)]
    recovered_retries = [
        workflow
        for workflow in retry_workflows
        if workflow.status != WorkflowStatus.RETRY_PENDING
        and not (workflow.supplier_response and workflow.supplier_response.status == "failed")
    ]
    llm_briefs = [workflow.operator_brief for workflow in workflows if workflow.operator_brief is not None]
    llm_fallbacks = [
        brief
        for brief in llm_briefs
        if brief.source == "deterministic" and brief.metadata.get("fallback_reason")
    ]

    return {
        "total_workflows": total,
        "completed": len(completed),
        "terminal_workflows": len(terminal),
        "automatic_processing_rate": _rate(len(auto_completed), total),
        "human_review_rate": _rate(len(awaiting) + len(manual) + len(clarification), total),
        "manual_review_rate": _rate(len(manual), total),
        "dead_letter_rate": _rate(len(dead_letter), total),
        "awaiting_approval": len(awaiting),
        "manual_review": len(manual),
        "retry_pending": len(retry_pending),
        "dead_letter": len(dead_letter),
        "rejected": len(rejected),
        "clarification_requested": len(clarification),
        "failed_notifications": len(failed_notifications),
        "approval_action_count": sum(len(workflow.approval_history) for workflow in workflows),
        "workflows_with_approval_rate": _rate(len(workflows_with_approval), total),
        "retry_attempt_count": sum(_retry_event_count(workflow) for workflow in workflows),
        "retry_workflow_count": len(retry_workflows),
        "retry_recovered_count": len(recovered_retries),
        "retry_recovery_rate": _rate(len(recovered_retries), len(retry_workflows)),
        "llm_brief_count": len(llm_briefs),
        "llm_fallback_count": len(llm_fallbacks),
        "llm_fallback_rate": _rate(len(llm_fallbacks), len(llm_briefs)),
        "average_workflow_duration_seconds": _average_duration_seconds(terminal),
        "average_approval_wait_seconds": _average_approval_wait_seconds(workflows),
        "failed_tool_call_count": sum(_failed_tool_event_count(workflow) for workflow in workflows),
        "false_autonomous_action_rate": 0,
    }


def metrics_to_prometheus(metrics: dict[str, Any]) -> str:
    lines = [
        "# HELP procureops_metric ProcureOps workflow metric.",
        "# TYPE procureops_metric gauge",
    ]
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, bool):
            numeric = int(value)
        elif isinstance(value, int | float):
            numeric = value
        else:
            continue
        lines.append(f"procureops_{key} {numeric}")
    return "\n".join(lines) + "\n"


def _rate(numerator: int, denominator: int) -> float:
    return (numerator / denominator) if denominator else 0


def _average(values: list[float]) -> float:
    return (sum(values) / len(values)) if values else 0


def _average_duration_seconds(workflows: list[WorkflowRecord]) -> float:
    return _average([(workflow.updated_at - workflow.created_at).total_seconds() for workflow in workflows])


def _average_approval_wait_seconds(workflows: list[WorkflowRecord]) -> float:
    waits: list[float] = []
    for workflow in workflows:
        awaiting_events = [event for event in workflow.audit_events if event.event_type == "AWAITING_APPROVAL"]
        if not awaiting_events or not workflow.approval_history:
            continue
        waits.append((workflow.approval_history[0].approved_at - awaiting_events[0].occurred_at).total_seconds())
    return _average(waits)


def _retry_event_count(workflow: WorkflowRecord) -> int:
    return sum(
        1
        for event in workflow.audit_events
        if event.event_type in {"ERP_LOOKUP_RETRY", "SUPPLIER_NOTIFICATION_RETRY_STARTED"}
    )


def _has_retry_event(workflow: WorkflowRecord) -> bool:
    return _retry_event_count(workflow) > 0


def _failed_tool_event_count(workflow: WorkflowRecord) -> int:
    return sum(1 for event in workflow.audit_events if event.event_type.endswith("_FAILED"))
