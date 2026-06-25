from pathlib import Path

from sqlalchemy import create_engine

from app.domain.models import IngestRequest, PolicyUpdateRequest, ProfileStatus, WorkflowStatus
from app.services.database import DatabasePolicyConfigRepository
from app.services.mock_erp import MockERPAdapter
from app.services.policies import PolicyConfigRepository
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore
from app.services.workflow import WorkflowEngine


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def test_policy_update_creates_draft_and_publish_replaces_active_policy():
    policies = PolicyConfigRepository()
    published = policies.get_active()

    draft = policies.update(published.policy_id, PolicyUpdateRequest(exact_match_auto_approve=False))

    assert draft.status == ProfileStatus.DRAFT
    assert draft.version == published.version + 1
    assert policies.get_active().policy_id == published.policy_id

    active = policies.publish(draft.policy_id)

    assert active.status == ProfileStatus.PUBLISHED
    assert policies.get_active().policy_id == active.policy_id
    assert policies.get_by_id(published.policy_id).status == ProfileStatus.ARCHIVED


def test_draft_policy_does_not_affect_workflow_until_published():
    policies = PolicyConfigRepository()
    published = policies.get_active()
    draft = policies.update(published.policy_id, PolicyUpdateRequest(exact_match_auto_approve=False))

    before = WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository(), policies)
    before_workflow = before.start(IngestRequest(edi_text=load_sample("exact-match.edi")))
    assert before_workflow.status == WorkflowStatus.COMPLETED
    assert before_workflow.policy_decision is not None
    assert before_workflow.policy_decision.policy_id == published.policy_id

    policies.publish(draft.policy_id)
    after = WorkflowEngine(InMemoryStore(), MockERPAdapter(), TradingPartnerProfileRepository(), policies)
    after_workflow = after.start(IngestRequest(edi_text=load_sample("exact-match.edi")))

    assert after_workflow.status == WorkflowStatus.AWAITING_APPROVAL
    assert after_workflow.policy_decision is not None
    assert after_workflow.policy_decision.policy_id == draft.policy_id


def test_database_policy_repository_seeds_and_publishes_versions():
    repo = DatabasePolicyConfigRepository.from_engine(create_engine("sqlite+pysqlite:///:memory:"))
    repo.initialize()
    published = repo.get_active()

    draft = repo.update(published.policy_id, PolicyUpdateRequest(maximum_delivery_delay_days=0))
    assert draft.status == ProfileStatus.DRAFT

    active = repo.publish(draft.policy_id)

    assert active.status == ProfileStatus.PUBLISHED
    assert repo.get_active().policy_id == active.policy_id
    assert repo.get_by_id(published.policy_id).status == ProfileStatus.ARCHIVED
