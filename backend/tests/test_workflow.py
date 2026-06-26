from pathlib import Path

from app.domain.models import ApprovalRequest, IngestRequest, ProfileUpdateRequest, WorkflowStatus
from app.services.mock_erp import MockERPAdapter
from app.services.notification import NotificationService
from app.services.policies import PolicyConfigRepository
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore
from app.services.workflow import WorkflowEngine


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def make_engine() -> WorkflowEngine:
    return WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository(), PolicyConfigRepository())


def test_exact_match_completes_without_approval():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))

    assert workflow.status == WorkflowStatus.COMPLETED
    assert workflow.policy_decision is not None
    assert workflow.policy_decision.decision == "AUTO_APPROVE"
    assert workflow.erp_update_command is not None
    assert workflow.supplier_response is not None


def test_small_delivery_delay_within_policy_completes_without_approval():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("small-delay.edi")))

    assert workflow.status == WorkflowStatus.COMPLETED
    assert workflow.policy_decision is not None
    assert workflow.policy_decision.decision == "AUTO_APPROVE"
    assert workflow.erp_update_command is not None


def test_risky_change_waits_for_approval_then_completes():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))

    assert workflow.status == WorkflowStatus.AWAITING_APPROVAL
    assert workflow.policy_decision is not None
    assert workflow.policy_decision.decision == "REQUIRE_APPROVAL"
    assert workflow.erp_update_command is None

    approved = engine.approve(workflow.workflow_id, ApprovalRequest(comments="Approved for test."))

    assert approved.status == WorkflowStatus.COMPLETED
    assert approved.approval is not None
    assert approved.approval_history[-1].decision == "APPROVED"
    assert approved.erp_update_command is not None


def test_approval_uses_edited_supplier_response():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))
    approved = engine.approve(
        workflow.workflow_id,
        ApprovalRequest(
            comments="Approved with supplier commitment.",
            supplier_response_subject="Edited approval subject",
            supplier_response_body="Edited approval body.",
        ),
    )

    assert approved.status == WorkflowStatus.COMPLETED
    assert approved.supplier_response is not None
    assert approved.supplier_response.subject == "Edited approval subject"
    assert approved.supplier_response.body == "Edited approval body."
    assert approved.supplier_response.status == "sent"
    assert any(event.event_type == "APPROVAL_RECORDED" for event in approved.audit_events)


def test_reject_sends_supplier_response_without_erp_update():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))
    rejected = engine.reject(
        workflow.workflow_id,
        ApprovalRequest(
            comments="Price and quantity change rejected.",
            supplier_response_body="Please resubmit using the original quantity and price.",
        ),
    )

    assert rejected.status == WorkflowStatus.REJECTED
    assert rejected.approval is not None
    assert rejected.approval.decision == "REJECTED"
    assert rejected.approval_history[-1].decision == "REJECTED"
    assert rejected.erp_update_command is None
    assert rejected.supplier_response is not None
    assert rejected.supplier_response.body == "Please resubmit using the original quantity and price."
    assert rejected.supplier_response.status == "sent"
    assert any(event.event_type == "APPROVAL_REJECTED" for event in rejected.audit_events)


def test_request_clarification_sends_supplier_response_without_erp_update():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))
    clarified = engine.request_clarification(
        workflow.workflow_id,
        ApprovalRequest(
            comments="Confirm whether line 1 can be partially expedited.",
            supplier_response_body="Can you confirm an expedited partial delivery for line 1?",
        ),
    )

    assert clarified.status == WorkflowStatus.CLARIFICATION_REQUESTED
    assert clarified.approval is not None
    assert clarified.approval.decision == "CLARIFICATION_REQUESTED"
    assert clarified.approval_history[-1].decision == "CLARIFICATION_REQUESTED"
    assert clarified.erp_update_command is None
    assert clarified.supplier_response is not None
    assert clarified.supplier_response.body == "Can you confirm an expedited partial delivery for line 1?"
    assert clarified.supplier_response.status == "sent"
    assert any(event.event_type == "CLARIFICATION_REQUESTED" for event in clarified.audit_events)


def test_manual_review_can_request_clarification_without_erp_update():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("unsupported-qualifier.edi")))

    assert workflow.status == WorkflowStatus.MANUAL_REVIEW
    clarified = engine.request_clarification(
        workflow.workflow_id,
        ApprovalRequest(
            comments="Unsupported qualifier needs supplier confirmation.",
            supplier_response_body="Please resubmit the acknowledgment using a supported delivery-date qualifier.",
        ),
    )

    assert clarified.status == WorkflowStatus.CLARIFICATION_REQUESTED
    assert clarified.erp_update_command is None
    assert clarified.supplier_response is not None
    assert clarified.supplier_response.status == "sent"
    assert clarified.supplier_response.body == "Please resubmit the acknowledgment using a supported delivery-date qualifier."
    assert any(event.event_type == "MANUAL_REVIEW_CLARIFICATION_REQUESTED" for event in clarified.audit_events)


def test_dead_letter_can_be_rejected_without_erp_update_or_known_supplier():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("malformed.edi")))

    assert workflow.status == WorkflowStatus.DEAD_LETTER
    rejected = engine.reject(
        workflow.workflow_id,
        ApprovalRequest(comments="Malformed EDI cannot be processed."),
    )

    assert rejected.status == WorkflowStatus.REJECTED
    assert rejected.erp_update_command is None
    assert rejected.supplier_response is not None
    assert rejected.supplier_response.recipient == "manual-review@example.local"
    assert rejected.supplier_response.status == "sent"
    assert any(event.event_type == "MANUAL_REVIEW_REJECTED" for event in rejected.audit_events)


def test_manual_review_reprocesses_after_profile_update():
    profiles = TradingPartnerProfileRepository()
    engine = WorkflowEngine(InMemoryStore(), MockERPAdapter(), profiles, PolicyConfigRepository())

    workflow = engine.start(IngestRequest(edi_text=load_sample("unsupported-qualifier.edi")))

    assert workflow.status == WorkflowStatus.MANUAL_REVIEW
    published = next(profile for profile in profiles.list() if profile.status == "PUBLISHED")
    draft = profiles.update(
        published.profile_id,
        ProfileUpdateRequest(date_qualifiers={**published.date_qualifiers, "999": "promised_delivery_date"}),
    )
    profiles.publish(draft.profile_id)

    reprocessed = engine.reprocess(workflow.workflow_id)

    assert reprocessed.status == WorkflowStatus.COMPLETED
    assert reprocessed.duplicate_of is None
    assert reprocessed.policy_decision is not None
    assert reprocessed.policy_decision.decision == "AUTO_APPROVE"
    assert reprocessed.erp_update_command is not None
    original = engine.store.get_workflow(workflow.workflow_id)
    assert any(event.event_type == "WORKFLOW_REPROCESSED" for event in original.audit_events)


def test_duplicate_does_not_execute_second_erp_update():
    engine = make_engine()

    first = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))
    second = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))

    assert first.status == WorkflowStatus.COMPLETED
    assert second.status == WorkflowStatus.COMPLETED
    assert second.duplicate_of == first.workflow_id
    assert second.erp_update_command is None


def test_malformed_input_routes_to_dead_letter():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("malformed.edi")))

    assert workflow.status == WorkflowStatus.DEAD_LETTER
    assert workflow.confirmation is not None
    assert workflow.confirmation.validation_status == "REJECTED"
    assert workflow.erp_update_command is None
    assert any(event.event_type == "DEAD_LETTER" for event in workflow.audit_events)


def test_temporary_erp_lookup_outage_retries_and_completes():
    engine = WorkflowEngine(
        InMemoryStore(),
        MockERPAdapter(transient_lookup_failures={"PO-1042": 1}),
        TradingPartnerProfileRepository(),
        PolicyConfigRepository(),
    )

    workflow = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))

    assert workflow.status == WorkflowStatus.COMPLETED
    assert any(event.event_type == "ERP_LOOKUP_RETRY" for event in workflow.audit_events)


def test_notification_failure_retries_without_second_erp_update():
    engine = WorkflowEngine(
        InMemoryStore(),
        MockERPAdapter(),
        TradingPartnerProfileRepository(),
        PolicyConfigRepository(),
        notifications=NotificationService(fail_once_control_numbers={"0001"}),
    )

    workflow = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))

    assert workflow.status == WorkflowStatus.RETRY_PENDING
    assert workflow.erp_update_command is not None
    assert workflow.supplier_response is not None
    assert workflow.supplier_response.status == "failed"
    assert sum(1 for event in workflow.audit_events if event.event_type == "ERP_UPDATED") == 1

    retried = engine.retry_notification(workflow.workflow_id)

    assert retried.status == WorkflowStatus.COMPLETED
    assert retried.supplier_response is not None
    assert retried.supplier_response.status == "sent"
    assert sum(1 for event in retried.audit_events if event.event_type == "ERP_UPDATED") == 1
    assert any(event.event_type == "SUPPLIER_NOTIFICATION_RETRY_STARTED" for event in retried.audit_events)


def test_rejected_notification_retry_returns_to_rejected_without_erp_update():
    engine = WorkflowEngine(
        InMemoryStore(),
        MockERPAdapter(),
        TradingPartnerProfileRepository(),
        PolicyConfigRepository(),
        notifications=NotificationService(fail_once_control_numbers={"0002"}),
    )

    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))
    rejected = engine.reject(workflow.workflow_id, ApprovalRequest(comments="Rejected for test."))

    assert rejected.status == WorkflowStatus.RETRY_PENDING
    assert rejected.erp_update_command is None
    assert rejected.supplier_response is not None
    assert rejected.supplier_response.status == "failed"

    retried = engine.retry_notification(workflow.workflow_id)

    assert retried.status == WorkflowStatus.REJECTED
    assert retried.erp_update_command is None
    assert retried.supplier_response is not None
    assert retried.supplier_response.status == "sent"
