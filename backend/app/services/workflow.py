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
    ValidationStatus,
    WorkflowRecord,
    WorkflowStatus,
    new_id,
)
from app.services.comparison import ComparisonEngine
from app.services.edi_interpreter import EDIInterpreter
from app.services.edi_parser import EDIParser
from app.services.impact import ImpactAssessmentService
from app.services.mock_erp import MockERPAdapter
from app.services.notification import NotificationService
from app.services.policy import PolicyEngine
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    raw_edi: str
    route: str


class WorkflowEngine:
    def __init__(
        self,
        store: InMemoryStore,
        erp: MockERPAdapter,
        profiles: TradingPartnerProfileRepository,
    ) -> None:
        self.store = store
        self.erp = erp
        self.parser = EDIParser()
        self.interpreter = EDIInterpreter(profiles)
        self.comparison = ComparisonEngine()
        self.impact = ImpactAssessmentService(erp)
        self.policy = PolicyEngine()
        self.notifications = NotificationService()
        self.graph = self._build_graph()

    def start(self, request: IngestRequest) -> WorkflowRecord:
        workflow = WorkflowRecord(
            workflow_id=new_id("WF"),
            correlation_id=new_id("CORR"),
            status=WorkflowStatus.RECEIVED,
            raw_payload_hash=self._hash(request.edi_text),
        )
        self.store.save_workflow(workflow)
        self.store.add_audit(workflow, "WORKFLOW_RECEIVED", "Received EDI supplier confirmation.")

        state: WorkflowState = {"workflow_id": workflow.workflow_id, "raw_edi": request.edi_text}
        if self.graph:
            self.graph.invoke(state)
        else:
            self._run_without_langgraph(state)
        return self.store.get_workflow(workflow.workflow_id)

    def approve(self, workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.status != WorkflowStatus.AWAITING_APPROVAL:
            raise ValueError("Workflow is not awaiting approval.")
        workflow.approval = ApprovalRecord(
            workflow_id=workflow.workflow_id,
            decision="APPROVED",
            approved_by=request.approved_by,
            comments=request.comments,
        )
        workflow.status = WorkflowStatus.APPROVED
        self.store.add_audit(
            workflow,
            "APPROVAL_RECORDED",
            "Approval recorded; workflow will resume ERP update.",
            {"approved_by": request.approved_by, "comments": request.comments},
            actor_type="user",
        )
        state: WorkflowState = {"workflow_id": workflow.workflow_id}
        self._apply_erp_update(state)
        self._notify_supplier(state)
        self._complete(state)
        return self.store.get_workflow(workflow_id)

    def reject(self, workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.status != WorkflowStatus.AWAITING_APPROVAL:
            raise ValueError("Workflow is not awaiting approval.")
        workflow.approval = ApprovalRecord(
            workflow_id=workflow.workflow_id,
            decision="REJECTED",
            approved_by=request.approved_by,
            comments=request.comments,
        )
        workflow.status = WorkflowStatus.REJECTED
        self.store.add_audit(
            workflow,
            "APPROVAL_REJECTED",
            "Supplier changes rejected by approver.",
            {"approved_by": request.approved_by, "comments": request.comments},
            actor_type="user",
        )
        self.store.save_workflow(workflow)
        return workflow

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
        if duplicate_of:
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
        if confirmation.validation_status in {ValidationStatus.MANUAL_REVIEW_REQUIRED, ValidationStatus.REJECTED}:
            workflow.status = WorkflowStatus.MANUAL_REVIEW
            self.store.add_audit(workflow, "MANUAL_REVIEW_REQUIRED", "EDI semantics require manual review.")
        self.store.save_workflow(workflow)
        return state

    def _route_after_interpretation(self, state: WorkflowState) -> str:
        workflow = self.store.get_workflow(state["workflow_id"])
        if workflow.duplicate_of:
            return "duplicate"
        if workflow.status == WorkflowStatus.MANUAL_REVIEW:
            return "manual_review"
        return "continue"

    def _retrieve_purchase_order(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
        assert workflow.confirmation is not None
        workflow.purchase_order = self.erp.get_purchase_order(workflow.confirmation.purchase_order_number)
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
        workflow.policy_decision = self.policy.evaluate(workflow.confirmation, workflow.comparisons, workflow.impacts)
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
        if key in self.store.erp_update_index:
            self.store.add_audit(workflow, "ERP_UPDATE_SKIPPED", "ERP update already executed for this workflow.")
            return state

        updates = [
            {
                "line_id": line.supplier_line_id,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
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
        self.store.erp_update_index.add(key)
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
        supplier = self.erp.get_supplier(workflow.confirmation.supplier_id)
        workflow.supplier_response = self.notifications.build_supplier_response(workflow, supplier, workflow.confirmation)
        workflow.status = WorkflowStatus.SUPPLIER_NOTIFIED
        self.store.add_audit(
            workflow,
            "SUPPLIER_NOTIFIED",
            "Supplier response generated and marked sent.",
            workflow.supplier_response.model_dump(mode="json"),
        )
        return state

    def _complete(self, state: WorkflowState) -> WorkflowState:
        workflow = self.store.get_workflow(state["workflow_id"])
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
