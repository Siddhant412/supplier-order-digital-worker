import json
import logging

from app.domain.models import AuditEvent, OperatorBrief, WorkflowRecord, WorkflowStatus, new_id
from app.services.observability import JsonFormatter, compute_metrics, metrics_to_prometheus


def make_workflow(status: WorkflowStatus) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=new_id("WF"),
        correlation_id=new_id("CORR"),
        status=status,
        raw_payload_hash="hash",
    )


def test_compute_metrics_tracks_retries_and_llm_fallbacks():
    completed = make_workflow(WorkflowStatus.COMPLETED)
    completed.audit_events.append(
        AuditEvent(
            workflow_id=completed.workflow_id,
            event_type="SUPPLIER_NOTIFICATION_RETRY_STARTED",
            correlation_id=completed.correlation_id,
            actor_type="system",
            summary="Retry.",
        )
    )
    completed.operator_brief = OperatorBrief(
        workflow_id=completed.workflow_id,
        summary="Summary",
        risk_assessment="Risk",
        recommended_action="Action",
        supplier_message_draft="Draft",
        source="deterministic",
        metadata={"fallback_reason": "ValueError"},
    )
    manual = make_workflow(WorkflowStatus.MANUAL_REVIEW)

    metrics = compute_metrics([completed, manual])

    assert metrics["total_workflows"] == 2
    assert metrics["retry_workflow_count"] == 1
    assert metrics["retry_recovered_count"] == 1
    assert metrics["retry_recovery_rate"] == 1
    assert metrics["llm_fallback_count"] == 1
    assert metrics["llm_fallback_rate"] == 1
    assert metrics["manual_review_rate"] == 0.5
    assert "procureops_llm_fallback_rate 1" in metrics_to_prometheus(metrics)


def test_json_formatter_outputs_structured_log_record():
    record = logging.LogRecord(
        name="procureops.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.props = {"path": "/health", "status_code": 200}

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "procureops.test"
    assert payload["message"] == "request_completed"
    assert payload["path"] == "/health"
    assert payload["status_code"] == 200
