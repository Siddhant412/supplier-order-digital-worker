from pathlib import Path

from sqlalchemy import create_engine

from app.domain.models import IngestRequest, ProfileStatus, ProfileUpdateRequest, WorkflowStatus
from app.services.database import DatabaseTradingPartnerProfileRepository, DatabaseWorkflowStore
from app.services.mock_erp import MockERPAdapter
from app.services.policies import PolicyConfigRepository
from app.services.profiles import TradingPartnerProfileRepository
from app.services.workflow import WorkflowEngine


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def test_profile_update_creates_draft_and_publish_replaces_active_profile():
    profiles = TradingPartnerProfileRepository()
    published = profiles.get("SUP-100", "855", "004010")
    assert published is not None

    draft = profiles.update(
        published.profile_id,
        ProfileUpdateRequest(date_qualifiers={**published.date_qualifiers, "999": "promised_delivery_date"}),
    )

    assert draft.status == ProfileStatus.DRAFT
    assert draft.version == published.version + 1
    assert profiles.get("SUP-100", "855", "004010").profile_id == published.profile_id

    active = profiles.publish(draft.profile_id)

    assert active.status == ProfileStatus.PUBLISHED
    assert profiles.get("SUP-100", "855", "004010").profile_id == active.profile_id
    assert profiles.get_by_id(published.profile_id).status == ProfileStatus.ARCHIVED


def test_published_profile_change_affects_new_workflow_interpretation():
    profiles = TradingPartnerProfileRepository()
    published = profiles.get("SUP-100", "855", "004010")
    assert published is not None

    before = WorkflowEngine(
        DatabaseWorkflowStore.from_engine(create_engine("sqlite+pysqlite:///:memory:")),
        MockERPAdapter(),
        profiles,
        PolicyConfigRepository(),
    )
    before.store.initialize()
    manual = before.start(IngestRequest(edi_text=load_sample("unsupported-qualifier.edi")))
    assert manual.status == WorkflowStatus.MANUAL_REVIEW

    draft = profiles.update(
        published.profile_id,
        ProfileUpdateRequest(date_qualifiers={**published.date_qualifiers, "999": "promised_delivery_date"}),
    )
    profiles.publish(draft.profile_id)

    after_store = DatabaseWorkflowStore.from_engine(create_engine("sqlite+pysqlite:///:memory:"))
    after_store.initialize()
    after = WorkflowEngine(after_store, MockERPAdapter(), profiles, PolicyConfigRepository())
    workflow = after.start(IngestRequest(edi_text=load_sample("unsupported-qualifier.edi")))

    assert workflow.status == WorkflowStatus.COMPLETED
    assert workflow.confirmation is not None
    assert workflow.confirmation.trading_partner_profile_id == draft.profile_id


def test_database_profile_repository_seeds_and_publishes_versions():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repo = DatabaseTradingPartnerProfileRepository.from_engine(engine)
    repo.initialize()
    published = repo.get("SUP-100", "855", "004010")
    assert published is not None

    draft = repo.update(
        published.profile_id,
        ProfileUpdateRequest(ack_codes={**published.ack_codes, "ZZ": "accepted"}),
    )
    assert draft.status == ProfileStatus.DRAFT

    active = repo.publish(draft.profile_id)

    assert active.status == ProfileStatus.PUBLISHED
    assert repo.get("SUP-100", "855", "004010").profile_id == active.profile_id
    assert repo.get_by_id(published.profile_id).status == ProfileStatus.ARCHIVED
