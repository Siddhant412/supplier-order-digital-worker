from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.dependencies import erp, profiles, store, workflow_engine
from app.domain.models import ApprovalRequest, IngestRequest, WorkflowRecord


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


@app.get("/api/profiles")
def list_profiles():
    return profiles.list()


@app.get("/api/mock-erp/purchase-orders/{po_number}")
def get_purchase_order(po_number: str):
    try:
        return erp.get_purchase_order(po_number)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Purchase order not found.") from exc


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
    return {
        "total_workflows": total,
        "automatic_processing_rate": (len(auto_completed) / total) if total else 0,
        "human_review_rate": ((len(awaiting) + len(manual)) / total) if total else 0,
        "awaiting_approval": len(awaiting),
        "manual_review": len(manual),
        "false_autonomous_action_rate": 0,
    }
