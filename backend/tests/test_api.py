from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def unique_control(edi_text: str, original: str, replacement: str) -> str:
    return edi_text.replace(original, replacement)


def test_api_ingests_risky_workflow_and_approval_resumes_execution():
    client = TestClient(app)

    ingest_response = client.post("/api/ingest", json={"edi_text": load_sample("risky-change.edi")})

    assert ingest_response.status_code == 200
    workflow = ingest_response.json()
    assert workflow["status"] == "AWAITING_APPROVAL"
    assert workflow["policy_decision"]["decision"] == "REQUIRE_APPROVAL"
    assert workflow["erp_update_command"] is None
    assert workflow["operator_brief"] is not None
    assert workflow["operator_brief"]["supplier_message_draft"]

    approve_response = client.post(
        f"/api/workflows/{workflow['workflow_id']}/approve",
        json={"approved_by": "operator@procureops.local", "comments": "Approved in API test."},
    )

    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "COMPLETED"
    assert approved["erp_update_command"] is not None


def test_api_exposes_workflow_execution_trace():
    client = TestClient(app)
    client.post("/api/mock-erp/reset")

    edi_text = unique_control(load_sample("risky-change.edi"), "0002", "0122")
    ingest_response = client.post("/api/ingest", json={"edi_text": edi_text})
    workflow = ingest_response.json()

    trace_response = client.get(f"/api/workflows/{workflow['workflow_id']}/execution-trace")

    assert trace_response.status_code == 200
    trace = trace_response.json()
    steps_by_id = {step["step_id"]: step for step in trace}
    step_order = [step["step_id"] for step in trace]
    assert steps_by_id["parse"]["langgraph_node"] == "parse_edi_syntax"
    assert steps_by_id["interpret"]["langgraph_node"] == "interpret_edi_semantics"
    assert steps_by_id["investigate"]["langgraph_node"] == "investigate_risk"
    assert steps_by_id["investigate"]["status"] == "completed"
    assert steps_by_id["approval"]["owner"] == "human"
    assert steps_by_id["approval"]["status"] == "waiting"
    assert step_order.index("approval") < step_order.index("brief") < step_order.index("erp_update")
    assert steps_by_id["erp_update"]["status"] == "waiting"
    assert steps_by_id["notify"]["status"] == "skipped"

    approve_response = client.post(
        f"/api/workflows/{workflow['workflow_id']}/approve",
        json={"approved_by": "operator@procureops.local", "comments": "Approved for trace test."},
    )
    assert approve_response.status_code == 200

    completed_trace = client.get(f"/api/workflows/{workflow['workflow_id']}/execution-trace").json()
    completed_by_id = {step["step_id"]: step for step in completed_trace}
    assert completed_by_id["approval"]["status"] == "completed"
    assert completed_by_id["erp_update"]["status"] == "completed"
    assert completed_by_id["notify"]["status"] == "completed"
    assert completed_by_id["complete"]["status"] == "completed"
    client.post("/api/mock-erp/reset")


def test_api_previews_edi_without_creating_workflow():
    client = TestClient(app)
    before_count = len(client.get("/api/workflows").json())

    preview_response = client.post("/api/edi/preview", json={"edi_text": load_sample("risky-change.edi")})
    workflows_after_preview = client.get("/api/workflows").json()

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["summary"]["purchase_order_number"] == "PO-1042"
    assert preview["summary"]["supplier_id"] == "SUP-100"
    assert preview["summary"]["control_number"] == "0002"
    assert preview["summary"]["validation_status"] == "VALID"
    assert preview["confirmation"]["lines"][0]["supplier_part_number"] == "ACME-M100"
    assert preview["confirmation"]["lines"][0]["quantity"] == 450
    assert len(workflows_after_preview) == before_count


def test_api_preview_surfaces_semantic_review_findings():
    client = TestClient(app)

    preview_response = client.post("/api/edi/preview", json={"edi_text": load_sample("unsupported-qualifier.edi")})

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["summary"]["validation_status"] == "MANUAL_REVIEW_REQUIRED"
    assert "Unsupported or ambiguous date qualifier: 999." in preview["confirmation"]["errors"]


def test_api_requests_clarification_with_edited_supplier_response():
    client = TestClient(app)

    edi_text = unique_control(load_sample("risky-change.edi"), "0002", "0012")
    edi_text = edi_text.replace("12.50", "13.25").replace("ACK*IQ*450*EA*067*20260715", "ACK*IQ*400*EA*067*20260720")
    ingest_response = client.post("/api/ingest", json={"edi_text": edi_text})

    assert ingest_response.status_code == 200
    workflow = ingest_response.json()
    assert workflow["status"] == "AWAITING_APPROVAL"

    clarify_response = client.post(
        f"/api/workflows/{workflow['workflow_id']}/request-clarification",
        json={
            "approved_by": "operator@procureops.local",
            "comments": "Need delivery clarification.",
            "supplier_response_subject": "Clarification requested",
            "supplier_response_body": "Please confirm the earliest partial delivery date.",
        },
    )

    assert clarify_response.status_code == 200
    clarified = clarify_response.json()
    assert clarified["status"] == "CLARIFICATION_REQUESTED"
    assert clarified["erp_update_command"] is None
    assert clarified["supplier_response"]["subject"] == "Clarification requested"
    assert clarified["supplier_response"]["body"] == "Please confirm the earliest partial delivery date."
    assert clarified["approval_history"][-1]["decision"] == "CLARIFICATION_REQUESTED"


def test_api_generates_operator_brief_and_audit_event():
    client = TestClient(app)

    edi_text = unique_control(load_sample("risky-change.edi"), "0002", "0092")
    ingest_response = client.post("/api/ingest", json={"edi_text": edi_text})
    workflow = ingest_response.json()

    brief_response = client.post(f"/api/workflows/{workflow['workflow_id']}/brief")

    assert brief_response.status_code == 200
    brief = brief_response.json()
    assert brief["workflow_id"] == workflow["workflow_id"]
    assert brief["source"] in {"deterministic", "llm"}
    assert brief["summary"]
    assert brief["risk_assessment"]
    assert brief["recommended_action"]
    assert brief["supplier_message_draft"]

    workflow_response = client.get(f"/api/workflows/{workflow['workflow_id']}")
    updated = workflow_response.json()
    assert updated["operator_brief"]["workflow_id"] == workflow["workflow_id"]
    assert any(event["event_type"] == "OPERATOR_BRIEF_GENERATED" for event in updated["audit_events"])


def test_api_rejects_manual_review_without_erp_update():
    client = TestClient(app)

    edi_text = unique_control(load_sample("unsupported-qualifier.edi"), "0003", "0193")
    ingest_response = client.post("/api/ingest", json={"edi_text": edi_text})
    workflow = ingest_response.json()

    assert workflow["status"] == "MANUAL_REVIEW"

    reject_response = client.post(
        f"/api/workflows/{workflow['workflow_id']}/reject",
        json={
            "approved_by": "operator@procureops.local",
            "comments": "Unsupported date qualifier cannot be accepted.",
        },
    )

    assert reject_response.status_code == 200
    rejected = reject_response.json()
    assert rejected["status"] == "REJECTED"
    assert rejected["erp_update_command"] is None
    assert rejected["supplier_response"]["status"] == "sent"
    assert any(event["event_type"] == "MANUAL_REVIEW_REJECTED" for event in rejected["audit_events"])


def test_api_creates_profile_and_policy_drafts():
    client = TestClient(app)
    suffix = uuid4().hex[:6].upper()

    profile_response = client.post(
        "/api/profiles",
        json={
            "supplier_id": f"SUP-{suffix}",
            "transaction_type": "855",
            "edi_version": "004010",
            "date_qualifiers": {"067": "promised_delivery_date"},
            "ack_codes": {"IA": "accepted"},
            "repeated_ack_policy": "manual_review",
            "unknown_qualifier_policy": "manual_review",
        },
    )
    policy_response = client.post(
        "/api/policies",
        json={
            "policy_version": f"draft-{suffix}",
            "maximum_price_increase_percent": 2,
            "maximum_delivery_delay_days": 1,
            "maximum_order_value": 2500,
            "exact_match_auto_approve": True,
            "require_no_stockout_impact": True,
        },
    )

    assert profile_response.status_code == 200
    assert profile_response.json()["status"] == "DRAFT"
    assert policy_response.status_code == 200
    assert policy_response.json()["status"] == "DRAFT"


def test_api_resets_mock_erp_seed_state():
    client = TestClient(app)
    client.post("/api/mock-erp/reset")
    edi_text = unique_control(load_sample("risky-change.edi"), "0002", uuid4().hex[:4].upper())
    workflow = client.post("/api/ingest", json={"edi_text": edi_text}).json()
    approved = client.post(
        f"/api/workflows/{workflow['workflow_id']}/approve",
        json={"approved_by": "operator@procureops.local", "comments": "Mutate mock ERP for reset test."},
    ).json()

    assert approved["status"] == "COMPLETED"
    changed_po = client.get("/api/mock-erp/purchase-orders/PO-1042").json()
    assert changed_po["lines"][0]["quantity"] == 450

    reset_response = client.post("/api/mock-erp/reset")
    reset_po = client.get("/api/mock-erp/purchase-orders/PO-1042").json()

    assert reset_response.status_code == 200
    assert reset_response.json()["status"] == "reset"
    assert reset_po["lines"][0]["quantity"] == 500


def test_api_exposes_mock_erp_operational_context():
    client = TestClient(app)
    client.post("/api/mock-erp/reset")

    context_response = client.get("/api/mock-erp/context")
    purchase_orders_response = client.get("/api/mock-erp/purchase-orders")

    assert context_response.status_code == 200
    context = context_response.json()
    po = context["purchase_orders"][0]
    assert po["purchase_order_number"] == "PO-1042"
    assert po["supplier_id"] == "SUP-100"
    assert po["lines"][0]["part_number"] == "MOTOR-100"
    assert po["lines"][0]["quantity"] == 500
    assert context["suppliers"][0]["part_aliases"]["ACME-M100"] == "MOTOR-100"
    assert any(position["part_number"] == "MOTOR-100" for position in context["inventory"])
    assert "MOTOR-100" in context["alternate_suppliers"]

    assert purchase_orders_response.status_code == 200
    assert purchase_orders_response.json()[0]["purchase_order_number"] == "PO-1042"


def test_api_exposes_liveness_readiness_and_metrics():
    client = TestClient(app)

    live_response = client.get("/live")
    ready_response = client.get("/ready")
    metrics_response = client.get("/api/metrics")
    prometheus_response = client.get("/metrics")

    assert live_response.status_code == 200
    assert live_response.json()["status"] == "ok"
    assert ready_response.status_code == 200
    assert ready_response.json()["ready"] is True
    metrics = metrics_response.json()
    assert metrics_response.status_code == 200
    assert "average_workflow_duration_seconds" in metrics
    assert "retry_recovery_rate" in metrics
    assert "llm_fallback_rate" in metrics
    assert prometheus_response.status_code == 200
    assert "procureops_total_workflows" in prometheus_response.text
    assert "procureops_llm_fallback_rate" in prometheus_response.text


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
