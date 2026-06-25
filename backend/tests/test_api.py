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


def test_api_updates_and_publishes_profile_draft():
    client = TestClient(app)

    profiles = client.get("/api/profiles").json()
    published = next(profile for profile in profiles if profile["status"] == "PUBLISHED")

    update_response = client.patch(
        f"/api/profiles/{published['profile_id']}",
        json={"date_qualifiers": {**published["date_qualifiers"], "999": "promised_delivery_date"}},
    )

    assert update_response.status_code == 200
    draft = update_response.json()
    assert draft["status"] == "DRAFT"
    assert draft["version"] == published["version"] + 1

    publish_response = client.post(f"/api/profiles/{draft['profile_id']}/publish")

    assert publish_response.status_code == 200
    active = publish_response.json()
    assert active["status"] == "PUBLISHED"
    assert active["date_qualifiers"]["999"] == "promised_delivery_date"

    restore_response = client.patch(
        f"/api/profiles/{active['profile_id']}",
        json={"date_qualifiers": published["date_qualifiers"]},
    )
    restored_draft = restore_response.json()
    client.post(f"/api/profiles/{restored_draft['profile_id']}/publish")


def test_api_runs_evaluations():
    client = TestClient(app)

    response = client.post("/api/evaluations/run")

    assert response.status_code == 200
    run = response.json()
    assert run["total"] >= 4
    assert run["passed"] + run["failed"] == run["total"]

    list_response = client.get("/api/evaluations/runs")
    assert list_response.status_code == 200
    assert any(item["run_id"] == run["run_id"] for item in list_response.json())


def test_api_updates_and_publishes_policy_draft():
    client = TestClient(app)

    policies = client.get("/api/policies").json()
    published = next(policy for policy in policies if policy["status"] == "PUBLISHED")

    update_response = client.patch(
        f"/api/policies/{published['policy_id']}",
        json={"maximum_delivery_delay_days": 0, "policy_version": "strict-delay-test"},
    )

    assert update_response.status_code == 200
    draft = update_response.json()
    assert draft["status"] == "DRAFT"
    assert draft["version"] == published["version"] + 1

    publish_response = client.post(f"/api/policies/{draft['policy_id']}/publish")

    assert publish_response.status_code == 200
    active = publish_response.json()
    assert active["status"] == "PUBLISHED"
    assert active["maximum_delivery_delay_days"] == 0
    assert active["policy_version"] == "strict-delay-test"

    restore_response = client.patch(
        f"/api/policies/{active['policy_id']}",
        json={
            "exact_match_auto_approve": published["exact_match_auto_approve"],
            "maximum_price_increase_percent": published["maximum_price_increase_percent"],
            "maximum_delivery_delay_days": published["maximum_delivery_delay_days"],
            "maximum_order_value": published["maximum_order_value"],
            "require_no_stockout_impact": published["require_no_stockout_impact"],
            "policy_version": published["policy_version"],
        },
    )
    restored_draft = restore_response.json()
    client.post(f"/api/policies/{restored_draft['policy_id']}/publish")
