from pathlib import Path

from app.domain.models import ApprovalRequest, IngestRequest
from app.services.briefing import BriefingService
from app.services.mock_erp import MockERPAdapter
from app.services.policies import PolicyConfigRepository
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore
from app.services.workflow import WorkflowEngine


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def test_briefing_service_returns_deterministic_operator_brief_without_api_key():
    engine = WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository(), PolicyConfigRepository())
    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))

    brief = BriefingService(api_key=None).generate(workflow)

    assert brief.workflow_id == workflow.workflow_id
    assert brief.source == "deterministic"
    assert brief.model is None
    assert "Policy decision is REQUIRE_APPROVAL" in brief.summary
    assert brief.risk_assessment
    assert brief.recommended_action
    assert brief.supplier_message_draft
    assert brief.metadata["fallback_reason"] == "openai_api_key_not_configured"


class FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.last_input = None

    def create(self, **kwargs):
        self.last_input = kwargs["input"]
        return FakeResponse(self.output_text)


class FakeClient:
    def __init__(self, output_text: str) -> None:
        self.responses = FakeResponses(output_text)


def test_briefing_service_accepts_strict_llm_json_and_redacts_facts():
    engine = WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository(), PolicyConfigRepository())
    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))
    workflow = engine.approve(workflow.workflow_id, ApprovalRequest())
    fake_client = FakeClient(
        """
        {
          "summary": "Summary text.",
          "risk_assessment": "Risk text.",
          "recommended_action": "Action text.",
          "supplier_message_draft": "Draft text."
        }
        """
    )

    service = BriefingService(
        api_key="test-key",
        client_factory=lambda api_key, timeout: fake_client,
        timeout_seconds=3,
    )
    brief = service.generate(workflow)

    assert brief.source == "llm"
    assert brief.summary == "Summary text."
    assert brief.metadata == {"timeout_seconds": 3, "facts_redacted": True}
    prompt_payload = fake_client.responses.last_input[1]["content"]
    assert "operator@procureops.local" not in prompt_payload
    assert "orders@acme.example" not in prompt_payload


def test_briefing_service_falls_back_on_malformed_llm_json():
    engine = WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository(), PolicyConfigRepository())
    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))
    fake_client = FakeClient('{"summary": "missing required fields"}')

    brief = BriefingService(api_key="test-key", client_factory=lambda api_key, timeout: fake_client).generate(workflow)

    assert brief.source == "deterministic"
    assert brief.metadata["fallback_reason"] == "ValueError"


def test_briefing_service_rejects_premature_approval_supplier_draft():
    engine = WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository(), PolicyConfigRepository())
    workflow = engine.start(IngestRequest(edi_text=load_sample("risky-change.edi")))
    fake_client = FakeClient(
        """
        {
          "summary": "Summary text.",
          "risk_assessment": "Risk text.",
          "recommended_action": "Action text.",
          "supplier_message_draft": "Thank you. The approved confirmation has been recorded."
        }
        """
    )

    brief = BriefingService(api_key="test-key", client_factory=lambda api_key, timeout: fake_client).generate(workflow)

    assert brief.source == "deterministic"
    assert "approved confirmation has been recorded" not in brief.supplier_message_draft.lower()
    assert "quantity" in brief.supplier_message_draft
    assert brief.metadata["fallback_reason"] == "ValueError"
