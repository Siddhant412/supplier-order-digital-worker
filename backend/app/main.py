from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from app.dependencies import briefing_service, erp, evaluation_runner, policies, profiles, store, workflow_engine
from app.domain.models import (
    ApprovalRequest,
    EvaluationRun,
    ExecutionTraceStep,
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
from app.services.execution_trace import build_execution_trace
from app.services.observability import compute_metrics, configure_json_logging, log_event, metrics_to_prometheus


configure_json_logging()
logger = logging.getLogger("procureops.api")

app = FastAPI(title="ProcureOps AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request, call_next):
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((perf_counter() - started) * 1000, 2)
        log_event(
            logger,
            logging.ERROR,
            "request_failed",
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
        )
        raise
    duration_ms = round((perf_counter() - started) * 1000, 2)
    log_event(
        logger,
        logging.INFO,
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.get("/health")
def health() -> dict[str, object]:
    readiness = readiness_status()
    return {"status": "ok" if readiness["ready"] else "degraded", "store": store.__class__.__name__, **readiness}


@app.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, object]:
    readiness = readiness_status()
    if not readiness["ready"]:
        raise HTTPException(status_code=503, detail=readiness)
    return readiness


def readiness_status() -> dict[str, object]:
    checks: dict[str, bool] = {}
    try:
        store.list_workflows()
        checks["store"] = True
    except Exception:
        checks["store"] = False
    try:
        profiles.list()
        checks["profiles"] = True
    except Exception:
        checks["profiles"] = False
    try:
        policies.get_active()
        checks["policies"] = True
    except Exception:
        checks["policies"] = False
    return {"ready": all(checks.values()), "checks": checks}


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


@app.get("/api/workflows/{workflow_id}/execution-trace", response_model=list[ExecutionTraceStep])
def get_workflow_execution_trace(workflow_id: str) -> list[ExecutionTraceStep]:
    try:
        workflow = store.get_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found.") from exc
    return build_execution_trace(workflow)


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
        {"source": brief.source, "model": brief.model, "metadata": brief.metadata},
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
    return compute_metrics(store.list_workflows())


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    return metrics_to_prometheus(compute_metrics(store.list_workflows()))
