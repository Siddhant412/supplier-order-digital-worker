from __future__ import annotations

import hashlib
from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - fallback keeps local tests usable before deps are installed.
    END = "__end__"
    StateGraph = None

from app.domain.models import (
    ApprovalRecord,
    ApprovalRequest,
    ERPUpdateCommand,
    IngestRequest,
    PolicyDecisionType,
    Supplier,
    SupplierResponse,
    ValidationStatus,
    WorkflowRecord,
    WorkflowStatus,
    new_id,
)
from app.services.comparison import ComparisonEngine
from app.services.edi_interpreter import EDIInterpreter
from app.services.edi_parser import EDIParser
from app.services.erp import ERPAdapter, TransientERPError
from app.services.impact import ImpactAssessmentService
from app.services.notification import NotificationService, TransientNotificationError
from app.services.policy import PolicyEngine
from app.services.policies import PolicyConfigStore
from app.services.profiles import TradingPartnerProfileStore
from app.services.store import WorkflowStore


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    raw_edi: str
    route: str
    reprocess_of: str


class WorkflowEngine:
    def __init__(
        self,
        store: WorkflowStore,
        erp: ERPAdapter,
        profiles: TradingPartnerProfileStore,
        policies: PolicyConfigStore,
        notifications: NotificationService | None = None,
    ) -> None:
        self.store = store
        self.erp = erp
        self.parser = EDIParser()
        self.interpreter = EDIInterpreter(profiles)
        self.comparison = ComparisonEngine()
        self.impact = ImpactAssessmentService(erp)
        self.policies = policies
        self.notifications = notifications or NotificationService()
        self.graph = self._build_graph()

    def start(self, request: IngestRequest) -> WorkflowRecord:
        return self._start(request.edi_text)

    def reprocess(self, workflow_id: str) -> WorkflowRecord:
        original = self.store.get_workflow(workflow_id)
        if original.status not in {
            WorkflowStatus.MANUAL_REVIEW,
            WorkflowStatus.DEAD_LETTER,
            WorkflowStatus.CLARIFICATION_REQUESTED,
            WorkflowStatus.REJECTED,
        }:
            raise ValueError("Only manual review, dead-letter, clarification, or rejected workflows can be reprocessed.")
        if not original.raw_payload:
            raise ValueError("Workflow does not retain a source payload for reprocessing.")
        reprocessed = self._start(original.raw_payload, reprocess_of=workflow_id)
        self.store.add_audit(
            original,
            "WORKFLOW_REPROCESSED",
            "Workflow source payload was reprocessed as a new workflow.",
            {"new_workflow_id": reprocessed.workflow_id},
            actor_type="user",
        )
        return reprocessed

    def _start(self, edi_text: str, reprocess_of: str | None = None) -> WorkflowRecord:
        workflow = WorkflowRecord(
            workflow_id=new_id("WF"),
            correlation_id=new_id("CORR"),
            status=WorkflowStatus.RECEIVED,
            raw_payload_hash=self._hash(edi_text),
            raw_payload=edi_text,
        )
        self.store.save_workflow(workflow)
        self.store.add_audit(
            workflow,
            "WORKFLOW_RECEIVED",
            "Received EDI supplier confirmation."
            if reprocess_of is None
            else "Received EDI supplier confirmation for reprocessing.",
            {"reprocess_of": reprocess_of} if reprocess_of else {},
        )

        state: WorkflowState = {"workflow_id": workflow.workflow_id, "raw_edi": edi_text}
        if reprocess_of:
            state["reprocess_of"] = reprocess_of
        if self.graph:
            self.graph.invoke(state)
        else:
            self._run_without_langgraph(state)
        return self.store.get_workflow(workflow.workflow_id)

    def approve(self, workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.status != WorkflowStatus.AWAITING_APPROVAL:
            raise ValueError("Workflow is not awaiting approval.")
        approval = self._record_human_decision(workflow, "APPROVED", request)
        workflow.status = WorkflowStatus.APPROVED
        self._stage_supplier_response(workflow, request, "approved")
        self.store.add_audit(
            workflow,
            "APPROVAL_RECORDED",
            "Approval recorded; workflow will resume ERP update.",
            approval.model_dump(mode="json") | {"supplier_response_edited": self._has_supplier_response_override(request)},
            actor_type="user",
        )
        state: WorkflowState = {"workflow_id": workflow.workflow_id}
        self._apply_erp_update(state)
        self._notify_supplier(state)
        self._complete(state)
        return self.store.get_workflow(workflow_id)

    def retry_notification(self, workflow_id: str) -> WorkflowRecord:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.status != WorkflowStatus.RETRY_PENDING:
            raise ValueError("Workflow is not waiting for retry.")
        if workflow.supplier_response is None or workflow.supplier_response.status != "failed":
            raise ValueError("Workflow does not have a failed supplier response to retry.")
        self.store.add_audit(
            workflow,
            "SUPPLIER_NOTIFICATION_RETRY_STARTED",
            "Retrying failed supplier notification without repeating ERP update.",
        )
        final_status = self._status_after_notification_retry(workflow)
        self._send_supplier_response(workflow, final_status)
        if final_status == WorkflowStatus.SUPPLIER_NOTIFIED:
            self._complete({"workflow_id": workflow.workflow_id})
        return self.store.get_workflow(workflow_id)

    def reject(self, workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
        workflow = self.store.get_workflow(workflow_id)
        previous_status = workflow.status
        if not self._can_record_negative_decision(workflow.status):
            raise ValueError("Workflow is not awaiting approval or manual review.")
        approval = self._record_human_decision(workflow, "REJECTED", request)
        workflow.status = WorkflowStatus.REJECTED
        self._stage_supplier_response(workflow, request, "rejected")
        event_type = "MANUAL_REVIEW_REJECTED" if previous_status in self._manual_resolution_statuses() else "APPROVAL_REJECTED"
        self.store.add_audit(
            workflow,
            event_type,
            "Manual review rejected; ERP update remains blocked."
            if event_type == "MANUAL_REVIEW_REJECTED"
            else "Supplier changes rejected by approver.",
            approval.model_dump(mode="json")
            | {
                "supplier_response_edited": self._has_supplier_response_override(request),
                "previous_status": previous_status.value,
            },
            actor_type="user",
        )
        self._send_supplier_response(workflow, WorkflowStatus.REJECTED)
        return self.store.get_workflow(workflow_id)

    def request_clarification(self, workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
        workflow = self.store.get_workflow(workflow_id)
        previous_status = workflow.status
        if not self._can_record_negative_decision(workflow.status):
            raise ValueError("Workflow is not awaiting approval or manual review.")
        approval = self._record_human_decision(workflow, "CLARIFICATION_REQUESTED", request)
        workflow.status = WorkflowStatus.CLARIFICATION_REQUESTED
        self._stage_supplier_response(workflow, request, "clarification")
        event_type = (
            "MANUAL_REVIEW_CLARIFICATION_REQUESTED"
            if previous_status in self._manual_resolution_statuses()
            else "CLARIFICATION_REQUESTED"
        )
        self.store.add_audit(
            workflow,
            event_type,
            "Clarification requested from manual review; ERP update remains blocked."
            if event_type == "MANUAL_REVIEW_CLARIFICATION_REQUESTED"
            else "Clarification requested from supplier; ERP update remains paused.",
            approval.model_dump(mode="json")
            | {
                "supplier_response_edited": self._has_supplier_response_override(request),
                "previous_status": previous_status.value,
            },
            actor_type="user",
        )
        self._send_supplier_response(workflow, WorkflowStatus.CLARIFICATION_REQUESTED)
        return self.store.get_workflow(workflow_id)

    def _build_graph(self):
        if StateGraph is None:
            return None
        graph = StateGraph(WorkflowState)
        graph.add_node("parse_edi_syntax", self._parse_edi_syntax)
        graph.add_node("interpret_edi_semantics", self._interpret_edi_semantics)
        graph.add_node("retrieve_purchase_order", self._retrieve_purchase_order)
        graph.add_node("compare_lines", self._compare_lines)
        graph.add_node("assess_impact", self._assess_impact)
        graph.add_node("evaluate_policy", self._evaluate_policy)
        graph.add_node("wait_for_approval", self._wait_for_approval)
        graph.add_node("apply_erp_update", self._apply_erp_update)
        graph.add_node("notify_supplier", self._notify_supplier)
        graph.add_node("complete", self._complete)

        graph.set_entry_point("parse_edi_syntax")
        graph.add_edge("parse_edi_syntax", "interpret_edi_semantics")
        graph.add_conditional_edges(
            "interpret_edi_semantics",
            self._route_after_interpretation,
            {"duplicate": "complete", "manual_review": END, "continue": "retrieve_purchase_order"},
        )
        graph.add_edge("retrieve_purchase_order", "compare_lines")
        graph.add_edge("compare_lines", "assess_impact")
        graph.add_edge("assess_impact", "evaluate_policy")
        graph.add_conditional_edges(
            "evaluate_policy",
            self._route_after_policy,
            {"auto": "apply_erp_update", "approval": "wait_for_approval", "manual_review": END, "reject": END},
        )
        graph.add_edge("wait_for_approval", END)
        graph.add_edge("apply_erp_update", "notify_supplier")
        graph.add_edge("notify_supplier", "complete")
        graph.add_edge("complete", END)
        return graph.compile()

    def _run_without_langgraph(self, state: WorkflowState) -> None:
        self._parse_edi_syntax(state)
        self._interpret_edi_semantics(state)
        route = self._route_after_interpretation(state)
        if route != "continue":
            if route == "duplicate":
                self._complete(state)
            return
        self._retrieve_purchase_order(state)
        self._compare_lines(state)
        self._assess_impact(state)
        self._evaluate_policy(state)
        route = self._route_after_policy(state)
        if route == "auto":
            self._apply_erp_update(state)
            self._notify_supplier(state)
            self._complete(state)
        elif route == "approval":
            self._wait_for_approval(state)

    def _parse_edi_syntax(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        parse_result = self.parser.parse(state["raw_edi"])
        workflow.parse_result = parse_result
        workflow.status = WorkflowStatus.PARSED
        self.store.add_audit(
            workflow,
            "EDI_SYNTAX_PARSED",
            f"EDI syntax parsed with status {parse_result.validation_status.value}.",
            {
                "transaction_type": parse_result.transaction_type,
                "edi_version": parse_result.edi_version,
                "warnings": parse_result.warnings,
                "errors": parse_result.errors,
            },
        )
        return state

    def _interpret_edi_semantics(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.parse_result is not None
        confirmation = self.interpreter.interpret(workflow.parse_result)
        workflow.confirmation = confirmation

        idempotency_key = self._idempotency_key(
            confirmation.supplier_id,
            confirmation.purchase_order_number,
            confirmation.source_control_number,
            workflow.raw_payload_hash,
        )
        workflow.idempotency_key = idempotency_key
        duplicate_of = self.store.find_by_idempotency_key(idempotency_key)
        if duplicate_of and duplicate_of != state.get("reprocess_of"):
            workflow.duplicate_of = duplicate_of
            workflow.status = WorkflowStatus.COMPLETED
            self.store.add_audit(
                workflow,
                "DUPLICATE_DETECTED",
                "Duplicate supplier confirmation detected; no ERP operation executed.",
                {"original_workflow_id": duplicate_of, "idempotency_key": idempotency_key},
            )
            return state
        self.store.index_idempotency_key(idempotency_key, workflow.workflow_id)

        self.store.add_audit(
            workflow,
            "EDI_SEMANTICS_INTERPRETED",
            f"EDI semantics interpreted with status {confirmation.validation_status.value}.",
            {
                "profile_id": confirmation.trading_partner_profile_id,
                "warnings": confirmation.warnings,
                "errors": confirmation.errors,
            },
        )
        if confirmation.validation_status == ValidationStatus.REJECTED:
            workflow.status = WorkflowStatus.DEAD_LETTER
            self.store.add_audit(workflow, "DEAD_LETTER", "EDI payload is rejected and cannot continue safely.")
        elif confirmation.validation_status == ValidationStatus.MANUAL_REVIEW_REQUIRED:
            workflow.status = WorkflowStatus.MANUAL_REVIEW
            self.store.add_audit(workflow, "MANUAL_REVIEW_REQUIRED", "EDI semantics require manual review.")
        self.store.save_workflow(workflow)
        return state

    def _route_after_interpretation(self, state: WorkflowState) -> str:
        workflow = self.store.get_workflow(state["workflow_id"])
        if workflow.duplicate_of:
            return "duplicate"
        if workflow.status in {WorkflowStatus.MANUAL_REVIEW, WorkflowStatus.DEAD_LETTER}:
            return "manual_review"
        return "continue"

    def _retrieve_purchase_order(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.confirmation is not None
        workflow.purchase_order = self._get_purchase_order_with_retry(
            workflow,
            workflow.confirmation.purchase_order_number,
        )
        workflow.status = WorkflowStatus.PO_RETRIEVED
        self.store.add_audit(
            workflow,
            "PURCHASE_ORDER_RETRIEVED",
            f"Retrieved purchase order {workflow.purchase_order.purchase_order_number}.",
        )
        return state

    def _compare_lines(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.confirmation is not None and workflow.purchase_order is not None
        supplier = self.erp.get_supplier(workflow.confirmation.supplier_id)
        workflow.comparisons = self.comparison.compare(workflow.confirmation, workflow.purchase_order, supplier)
        workflow.status = WorkflowStatus.COMPARED
        self.store.add_audit(
            workflow,
            "LINES_COMPARED",
            "Completed deterministic line-level comparison.",
            {"difference_count": sum(len(result.differences) for result in workflow.comparisons)},
        )
        return state

    def _assess_impact(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.confirmation is not None and workflow.purchase_order is not None
        workflow.impacts = self.impact.assess(workflow.confirmation, workflow.purchase_order, workflow.comparisons)
        workflow.status = WorkflowStatus.IMPACT_ASSESSED
        self.store.add_audit(
            workflow,
            "IMPACT_ASSESSED",
            "Assessed inventory, shortage, and financial impact.",
            {"stockout_risk": any(impact.stockout_risk for impact in workflow.impacts)},
        )
        return state

    def _evaluate_policy(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.confirmation is not None
        active_policy = self.policies.get_active()
        workflow.policy_decision = PolicyEngine(active_policy).evaluate(
            workflow.confirmation,
            workflow.comparisons,
            workflow.impacts,
        )
        workflow.status = WorkflowStatus.POLICY_EVALUATED
        self.store.add_audit(
            workflow,
            "POLICY_DECISION_RECORDED",
            f"Policy decision: {workflow.policy_decision.decision.value}.",
            workflow.policy_decision.model_dump(mode="json"),
        )
        return state

    def _route_after_policy(self, state: WorkflowState) -> str:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.policy_decision is not None
        if workflow.policy_decision.decision == PolicyDecisionType.AUTO_APPROVE:
            return "auto"
        if workflow.policy_decision.decision == PolicyDecisionType.REQUIRE_APPROVAL:
            return "approval"
        if workflow.policy_decision.decision == PolicyDecisionType.REJECT:
            workflow.status = WorkflowStatus.REJECTED
            self.store.save_workflow(workflow)
            return "reject"
        workflow.status = WorkflowStatus.MANUAL_REVIEW
        self.store.save_workflow(workflow)
        return "manual_review"

    def _wait_for_approval(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        workflow.status = WorkflowStatus.AWAITING_APPROVAL
        self.store.add_audit(
            workflow,
            "AWAITING_APPROVAL",
            "Workflow paused before ERP mutation because policy requires approval.",
        )
        return state

    def _apply_erp_update(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.confirmation is not None
        key = f"{workflow.idempotency_key}:erp-update"
        if self.store.has_erp_update(key):
            self.store.add_audit(workflow, "ERP_UPDATE_SKIPPED", "ERP update already executed for this workflow.")
            return state

        updates = [
            {
                "line_id": line.supplier_line_id,
                "quantity": line.normalized_quantity or line.quantity,
                "unit_price": line.normalized_unit_price or line.unit_price,
                "promised_date": line.promised_date,
            }
            for line in workflow.confirmation.lines
        ]
        workflow.erp_update_command = ERPUpdateCommand(
            workflow_id=workflow.workflow_id,
            purchase_order_number=workflow.confirmation.purchase_order_number,
            line_updates=updates,
            idempotency_key=key,
        )
        result = self.erp.update_purchase_order_lines(workflow.confirmation.purchase_order_number, updates)
        self.store.mark_erp_update(key, workflow.workflow_id)
        workflow.status = WorkflowStatus.ERP_UPDATED
        self.store.add_audit(
            workflow,
            "ERP_UPDATED",
            "Mock ERP purchase order updated.",
            result,
        )
        return state

    def _notify_supplier(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.confirmation is not None
        if workflow.supplier_response is None:
            supplier = self.erp.get_supplier(workflow.confirmation.supplier_id)
            workflow.supplier_response = self.notifications.build_supplier_response(workflow, supplier, workflow.confirmation)
        self._send_supplier_response(workflow, WorkflowStatus.SUPPLIER_NOTIFIED)
        return state

    def _complete(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        if workflow.status == WorkflowStatus.RETRY_PENDING:
            self.store.save_workflow(workflow)
            return state
        if workflow.status != WorkflowStatus.COMPLETED:
            workflow.status = WorkflowStatus.COMPLETED
            self.store.add_audit(workflow, "WORKFLOW_COMPLETED", "Workflow completed.")
        else:
            self.store.save_workflow(workflow)
        return state

    def _hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _idempotency_key(self, supplier_id: str, po_number: str, source_control_number: str, payload_hash: str) -> str:
        source = source_control_number if source_control_number != "UNKNOWN" else payload_hash
        return f"{supplier_id}:{po_number}:{source}"

    def _record_human_decision(
        self,
        workflow: WorkflowRecord,
        decision: str,
        request: ApprovalRequest,
    ) -> ApprovalRecord:
        approval = ApprovalRecord(
            workflow_id=workflow.workflow_id,
            decision=decision,  # type: ignore[arg-type]
            approved_by=request.approved_by,
            comments=request.comments,
        )
        workflow.approval = approval
        workflow.approval_history.append(approval)
        return approval

    def _stage_supplier_response(
        self,
        workflow: WorkflowRecord,
        request: ApprovalRequest,
        outcome: str,
    ) -> None:
        assert workflow.confirmation is not None
        supplier = self._supplier_for_response(workflow)
        if outcome == "rejected":
            generated = self.notifications.build_rejection_response(
                workflow,
                supplier,
                workflow.confirmation,
                request.comments,
            )
        elif outcome == "clarification":
            generated = self.notifications.build_clarification_response(
                workflow,
                supplier,
                workflow.confirmation,
                request.comments,
            )
        else:
            generated = self.notifications.build_supplier_response(workflow, supplier, workflow.confirmation)
        workflow.supplier_response = SupplierResponse(
            workflow_id=workflow.workflow_id,
            recipient=generated.recipient,
            subject=request.supplier_response_subject or generated.subject,
            body=request.supplier_response_body or generated.body,
            status="queued",
        )

    def _send_supplier_response(self, workflow: WorkflowRecord, final_status: WorkflowStatus) -> None:
        assert workflow.supplier_response is not None
        try:
            workflow.supplier_response = self.notifications.send_supplier_response(workflow, workflow.supplier_response)
        except TransientNotificationError as exc:
            workflow.supplier_response.status = "failed"
            workflow.status = WorkflowStatus.RETRY_PENDING
            self.store.add_audit(
                workflow,
                "SUPPLIER_NOTIFICATION_FAILED",
                "Supplier notification failed and is waiting for retry.",
                {"error": str(exc), "supplier_response": workflow.supplier_response.model_dump(mode="json")},
            )
            return
        workflow.status = final_status
        self.store.add_audit(
            workflow,
            "SUPPLIER_NOTIFIED",
            "Supplier response generated and marked sent.",
            workflow.supplier_response.model_dump(mode="json"),
        )

    def _has_supplier_response_override(self, request: ApprovalRequest) -> bool:
        return bool(request.supplier_response_subject or request.supplier_response_body)

    def _manual_resolution_statuses(self) -> set[WorkflowStatus]:
        return {WorkflowStatus.MANUAL_REVIEW, WorkflowStatus.DEAD_LETTER}

    def _can_record_negative_decision(self, status: WorkflowStatus) -> bool:
        return status == WorkflowStatus.AWAITING_APPROVAL or status in self._manual_resolution_statuses()

    def _supplier_for_response(self, workflow: WorkflowRecord) -> Supplier:
        assert workflow.confirmation is not None
        try:
            return self.erp.get_supplier(workflow.confirmation.supplier_id)
        except KeyError:
            return Supplier(
                supplier_id=workflow.confirmation.supplier_id,
                name=workflow.confirmation.supplier_id,
                email="manual-review@example.local",
                automation_enabled=False,
            )

    def _status_after_notification_retry(self, workflow: WorkflowRecord) -> WorkflowStatus:
        if workflow.approval and workflow.approval.decision == "REJECTED":
            return WorkflowStatus.REJECTED
        if workflow.approval and workflow.approval.decision == "CLARIFICATION_REQUESTED":
            return WorkflowStatus.CLARIFICATION_REQUESTED
        return WorkflowStatus.SUPPLIER_NOTIFIED

    def _get_purchase_order_with_retry(self, workflow: WorkflowRecord, po_number: str) -> Any:
        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                return self.erp.get_purchase_order(po_number)
            except TransientERPError as exc:
                self.store.add_audit(
                    workflow,
                    "ERP_LOOKUP_RETRY",
                    "Temporary ERP lookup failure; retrying purchase order retrieval.",
                    {"attempt": attempt, "max_attempts": attempts, "error": str(exc)},
                )
                if attempt == attempts:
                    workflow.status = WorkflowStatus.RETRY_PENDING
                    self.store.add_audit(
                        workflow,
                        "ERP_LOOKUP_RETRY_EXHAUSTED",
                        "ERP lookup retry attempts exhausted.",
                        {"error": str(exc)},
                    )
                    raise
        raise RuntimeError("ERP lookup retry loop exited unexpectedly.")
