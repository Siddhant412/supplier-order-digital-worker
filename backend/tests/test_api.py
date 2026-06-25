from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def test_api_ingests_risky_workflow_and_approval_resumes_execution():
    client = TestClient(app)

    ingest_response = client.post("/api/ingest", json={"edi_text": load_sample("risky-change.edi")})

    assert ingest_response.status_code == 200
    workflow = ingest_response.json()
    assert workflow["status"] == "AWAITING_APPROVAL"
    assert workflow["policy_decision"]["decision"] == "REQUIRE_APPROVAL"
    assert workflow["erp_update_command"] is None

    approve_response = client.post(
        f"/api/workflows/{workflow['workflow_id']}/approve",
        json={"approved_by": "operator@procureops.local", "comments": "Approved in API test."},
    )

    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "COMPLETED"
    assert approved["erp_update_command"] is not None
