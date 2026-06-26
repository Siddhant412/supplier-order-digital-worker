from pathlib import Path

from sqlalchemy import create_engine

from app.domain.models import IngestRequest, WorkflowRecord, WorkflowStatus, new_id
from app.services.database import AuditEventRow, DatabaseWorkflowStore, WorkflowRow
from app.services.mock_erp import MockERPAdapter
from app.services.policies import PolicyConfigRepository
from app.services.profiles import TradingPartnerProfileRepository
from app.services.workflow import WorkflowEngine


ROOT = Path(__file__).resolve().parents[2]


def make_store() -> DatabaseWorkflowStore:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    store = DatabaseWorkflowStore.from_engine(engine)
    store.initialize()
    return store


def test_database_store_persists_workflow_and_audit():
    store = make_store()
    workflow = WorkflowRecord(
        workflow_id=new_id("WF"),
        correlation_id=new_id("CORR"),
        status=WorkflowStatus.RECEIVED,
        raw_payload_hash="hash",
    )

    store.save_workflow(workflow)
    store.add_audit(workflow, "TEST_EVENT", "Stored test event.")

    loaded = store.get_workflow(workflow.workflow_id)
    assert loaded.workflow_id == workflow.workflow_id
    assert loaded.audit_events[0].event_type == "TEST_EVENT"

    with store.session_factory() as session:
        row = session.get(WorkflowRow, workflow.workflow_id)
        audit_rows = session.query(AuditEventRow).filter_by(workflow_id=workflow.workflow_id).all()
        assert row is not None
        assert row.data["audit_events"] == []
        assert len(audit_rows) == 1
        assert audit_rows[0].event_type == "TEST_EVENT"


def test_database_store_persists_idempotency_and_erp_update_keys():
    store = make_store()

    store.index_idempotency_key("SUP-100:PO-1042:0001", "WF-1")
    store.mark_erp_update("SUP-100:PO-1042:0001:erp-update", "WF-1")

    assert store.find_by_idempotency_key("SUP-100:PO-1042:0001") == "WF-1"
    assert store.has_erp_update("SUP-100:PO-1042:0001:erp-update")


def test_database_store_supports_workflow_duplicate_detection():
    store = make_store()
    engine = WorkflowEngine(store, MockERPAdapter(), TradingPartnerProfileRepository(), PolicyConfigRepository())
    edi_text = (ROOT / "sample-data" / "edi" / "exact-match.edi").read_text()

    first = engine.start(IngestRequest(edi_text=edi_text))
    second = engine.start(IngestRequest(edi_text=edi_text))

    assert first.status == WorkflowStatus.COMPLETED
    assert second.status == WorkflowStatus.COMPLETED
    assert second.duplicate_of == first.workflow_id
    assert second.erp_update_command is None
