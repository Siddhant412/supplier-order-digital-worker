from pathlib import Path

from app.domain.models import ApprovalRequest, IngestRequest, WorkflowStatus
from app.services.mock_erp import MockERPAdapter
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore
from app.services.workflow import WorkflowEngine


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def make_engine() -> WorkflowEngine:
    return WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository())


def test_exact_match_completes_without_approval():
    engine = make_engine()

    workflow = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))

    assert workflow.status == WorkflowStatus.COMPLETED
    assert workflow.policy_decision is not None
    assert workflow.policy_decision.decision == "AUTO_APPROVE"
    assert workflow.erp_update_command is not None
    assert workflow.supplier_response is not None


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
    assert approved.erp_update_command is not None


def test_duplicate_does_not_execute_second_erp_update():
    engine = make_engine()

    first = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))
    second = engine.start(IngestRequest(edi_text=load_sample("exact-match.edi")))

    assert first.status == WorkflowStatus.COMPLETED
    assert second.status == WorkflowStatus.COMPLETED
    assert second.duplicate_of == first.workflow_id
    assert second.erp_update_command is None
