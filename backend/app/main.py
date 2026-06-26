from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.dependencies import briefing_service, erp, evaluation_runner, policies, profiles, store, workflow_engine
from app.domain.models import (
    ApprovalRequest,
    EvaluationRun,
    IngestRequest,
    OperatorBrief,
    PolicyConfig,
    PolicyCreateRequest,
    PolicyUpdateRequest,
    ProfileCreateRequest,
    ProfileUpdateRequest,
    TradingPartnerProfile,
    WorkflowRecord,
)


app = FastAPI(title="ProcureOps AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "store": store.__class__.__name__}


@app.post("/api/ingest", response_model=WorkflowRecord)
def ingest(request: IngestRequest) -> WorkflowRecord:
    try:
        return workflow_engine.start(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/workflows", response_model=list[WorkflowRecord])
def list_workflows() -> list[WorkflowRecord]:
    return store.list_workflows()


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowRecord)
def get_workflow(workflow_id: str) -> WorkflowRecord:
    try:
        return store.get_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found.") from exc


@app.post("/api/workflows/{workflow_id}/approve", response_model=WorkflowRecord)
def approve_workflow(workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
    try:
        return workflow_engine.approve(workflow_id, request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflows/{workflow_id}/reject", response_model=WorkflowRecord)
def reject_workflow(workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
    try:
        return workflow_engine.reject(workflow_id, request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflows/{workflow_id}/request-clarification", response_model=WorkflowRecord)
def request_workflow_clarification(workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
    try:
        return workflow_engine.request_clarification(workflow_id, request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflows/{workflow_id}/retry-notification", response_model=WorkflowRecord)
def retry_workflow_notification(workflow_id: str) -> WorkflowRecord:
    try:
        return workflow_engine.retry_notification(workflow_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflows/{workflow_id}/reprocess", response_model=WorkflowRecord)
def reprocess_workflow(workflow_id: str) -> WorkflowRecord:
    try:
        return workflow_engine.reprocess(workflow_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflows/{workflow_id}/brief", response_model=OperatorBrief)
def generate_operator_brief(workflow_id: str) -> OperatorBrief:
    try:
        workflow = store.get_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found.") from exc
    brief = briefing_service.generate(workflow)
    workflow.operator_brief = brief
    store.add_audit(
        workflow,
        "OPERATOR_BRIEF_GENERATED",
        "Operator brief generated from workflow facts.",
        {"source": brief.source, "model": brief.model},
    )
    return brief


@app.get("/api/profiles")
def list_profiles() -> list[TradingPartnerProfile]:
    return profiles.list()


@app.get("/api/profiles/{profile_id}", response_model=TradingPartnerProfile)
def get_profile(profile_id: str) -> TradingPartnerProfile:
    try:
        return profiles.get_by_id(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found.") from exc


@app.post("/api/profiles", response_model=TradingPartnerProfile)
def create_profile(request: ProfileCreateRequest) -> TradingPartnerProfile:
    return profiles.create(request)


@app.patch("/api/profiles/{profile_id}", response_model=TradingPartnerProfile)
def update_profile(profile_id: str, request: ProfileUpdateRequest) -> TradingPartnerProfile:
    try:
        return profiles.update(profile_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found.") from exc


@app.post("/api/profiles/{profile_id}/publish", response_model=TradingPartnerProfile)
def publish_profile(profile_id: str) -> TradingPartnerProfile:
    try:
        return profiles.publish(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found.") from exc


@app.post("/api/profiles/{profile_id}/archive", response_model=TradingPartnerProfile)
def archive_profile(profile_id: str) -> TradingPartnerProfile:
    try:
        return profiles.archive(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found.") from exc


@app.get("/api/policies", response_model=list[PolicyConfig])
def list_policies() -> list[PolicyConfig]:
    return policies.list()


@app.get("/api/policies/{policy_id}", response_model=PolicyConfig)
def get_policy(policy_id: str) -> PolicyConfig:
    try:
        return policies.get_by_id(policy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy not found.") from exc


@app.post("/api/policies", response_model=PolicyConfig)
def create_policy(request: PolicyCreateRequest) -> PolicyConfig:
    return policies.create(request)


@app.patch("/api/policies/{policy_id}", response_model=PolicyConfig)
def update_policy(policy_id: str, request: PolicyUpdateRequest) -> PolicyConfig:
    try:
        return policies.update(policy_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy not found.") from exc


@app.post("/api/policies/{policy_id}/publish", response_model=PolicyConfig)
def publish_policy(policy_id: str) -> PolicyConfig:
    try:
        return policies.publish(policy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy not found.") from exc


@app.post("/api/policies/{policy_id}/archive", response_model=PolicyConfig)
def archive_policy(policy_id: str) -> PolicyConfig:
    try:
        return policies.archive(policy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy not found.") from exc


@app.get("/api/mock-erp/purchase-orders/{po_number}")
def get_purchase_order(po_number: str):
    try:
        return erp.get_purchase_order(po_number)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Purchase order not found.") from exc


@app.post("/api/mock-erp/reset")
def reset_mock_erp() -> dict[str, str]:
    erp.reset()
    return {"status": "reset"}


@app.post("/api/evaluations/run", response_model=EvaluationRun)
def run_evaluations() -> EvaluationRun:
    try:
        return evaluation_runner.run_all()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/evaluations/runs", response_model=list[EvaluationRun])
def list_evaluation_runs() -> list[EvaluationRun]:
    return store.list_evaluation_runs()


@app.get("/api/evaluations/runs/{run_id}", response_model=EvaluationRun)
def get_evaluation_run(run_id: str) -> EvaluationRun:
    try:
        return store.get_evaluation_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Evaluation run not found.") from exc


@app.get("/api/metrics")
def metrics() -> dict:
    workflows = store.list_workflows()
    total = len(workflows)
    auto_completed = [
        workflow
        for workflow in workflows
        if workflow.policy_decision and workflow.policy_decision.decision == "AUTO_APPROVE"
    ]
    awaiting = [workflow for workflow in workflows if workflow.status == "AWAITING_APPROVAL"]
    manual = [workflow for workflow in workflows if workflow.status == "MANUAL_REVIEW"]
    completed = [workflow for workflow in workflows if workflow.status == "COMPLETED"]
    retry_pending = [workflow for workflow in workflows if workflow.status == "RETRY_PENDING"]
    dead_letter = [workflow for workflow in workflows if workflow.status == "DEAD_LETTER"]
    rejected = [workflow for workflow in workflows if workflow.status == "REJECTED"]
    clarification = [workflow for workflow in workflows if workflow.status == "CLARIFICATION_REQUESTED"]
    failed_notifications = [
        workflow for workflow in workflows if workflow.supplier_response and workflow.supplier_response.status == "failed"
    ]
    workflows_with_approval = [workflow for workflow in workflows if workflow.approval_history]
    return {
        "total_workflows": total,
        "completed": len(completed),
        "automatic_processing_rate": (len(auto_completed) / total) if total else 0,
        "human_review_rate": ((len(awaiting) + len(manual) + len(clarification)) / total) if total else 0,
        "awaiting_approval": len(awaiting),
        "manual_review": len(manual),
        "retry_pending": len(retry_pending),
        "dead_letter": len(dead_letter),
        "rejected": len(rejected),
        "clarification_requested": len(clarification),
        "failed_notifications": len(failed_notifications),
        "approval_action_count": sum(len(workflow.approval_history) for workflow in workflows),
        "workflows_with_approval_rate": (len(workflows_with_approval) / total) if total else 0,
        "false_autonomous_action_rate": 0,
    }
