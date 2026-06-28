from __future__ import annotations

from app.domain.models import Supplier, SupplierConfirmation, SupplierResponse, WorkflowRecord


class TransientNotificationError(RuntimeError):
    pass


class NotificationService:
    def __init__(self, fail_once_control_numbers: set[str] | None = None) -> None:
        self.fail_once_control_numbers = fail_once_control_numbers or set()
        self._failed_control_numbers: set[str] = set()

    def build_supplier_response(
        self,
        workflow: WorkflowRecord,
        supplier: Supplier,
        confirmation: SupplierConfirmation,
    ) -> SupplierResponse:
        if workflow.policy_decision and workflow.policy_decision.reasons:
            reason_text = " ".join(workflow.policy_decision.reasons)
        else:
            reason_text = "The confirmation was accepted under the configured procurement policy."

        body = (
            f"Thank you for confirming purchase order {confirmation.purchase_order_number}. "
            f"The approved confirmation has been recorded. {reason_text}"
        )
        return SupplierResponse(
            workflow_id=workflow.workflow_id,
            recipient=supplier.email,
            subject=f"Purchase Order {confirmation.purchase_order_number} confirmation",
            body=body,
            status="sent",
        )

    def build_rejection_response(
        self,
        workflow: WorkflowRecord,
        supplier: Supplier,
        confirmation: SupplierConfirmation,
        comments: str = "",
    ) -> SupplierResponse:
        reason_text = comments or self._issue_summary(workflow)
        body = (
            f"Thank you for confirming purchase order {confirmation.purchase_order_number}. "
            f"We cannot accept the proposed changes at this time. {reason_text}"
        )
        return SupplierResponse(
            workflow_id=workflow.workflow_id,
            recipient=supplier.email,
            subject=f"Purchase Order {confirmation.purchase_order_number} changes not accepted",
            body=body,
            status="sent",
        )

    def build_clarification_response(
        self,
        workflow: WorkflowRecord,
        supplier: Supplier,
        confirmation: SupplierConfirmation,
        comments: str = "",
    ) -> SupplierResponse:
        request_text = comments or self._issue_summary(workflow)
        body = (
            f"Thank you for confirming purchase order {confirmation.purchase_order_number}. "
            f"We need clarification before the acknowledgment can be accepted. Please review: {request_text}"
        )
        return SupplierResponse(
            workflow_id=workflow.workflow_id,
            recipient=supplier.email,
            subject=f"Clarification needed for purchase order {confirmation.purchase_order_number}",
            body=body,
            status="sent",
        )

    def send_supplier_response(self, workflow: WorkflowRecord, response: SupplierResponse) -> SupplierResponse:
        control_number = workflow.confirmation.source_control_number if workflow.confirmation else None
        if (
            control_number
            and control_number in self.fail_once_control_numbers
            and control_number not in self._failed_control_numbers
        ):
            self._failed_control_numbers.add(control_number)
            raise TransientNotificationError(f"Temporary notification outage for control {control_number}.")
        response.status = "sent"
        return response

    def _issue_summary(self, workflow: WorkflowRecord) -> str:
        issues: list[str] = []
        if workflow.risk_investigation:
            issues.extend(workflow.risk_investigation.observations[:3])
            if workflow.risk_investigation.recommendation:
                issues.append(workflow.risk_investigation.recommendation)
        if workflow.policy_decision and workflow.policy_decision.reasons:
            issues.extend(workflow.policy_decision.reasons)
        if workflow.confirmation:
            issues.extend(workflow.confirmation.errors)
            issues.extend(workflow.confirmation.warnings)
        if workflow.parse_result:
            issues.extend(workflow.parse_result.errors)
            issues.extend(workflow.parse_result.warnings)
        for comparison in workflow.comparisons:
            for difference in comparison.differences:
                issues.append(
                    f"Line {comparison.line_id} {difference.field} changed from "
                    f"{difference.original} to {difference.confirmed}."
                )
        for impact in workflow.impacts:
            if impact.stockout_risk:
                issues.append(
                    f"Line {impact.line_id} has projected shortage risk of "
                    f"{impact.projected_shortage_quantity} unit(s)."
                )
        deduped = []
        for issue in issues:
            if issue and issue not in deduped:
                deduped.append(issue)
        return " ".join(deduped[:6]) or "Please confirm the updated quantity, price, delivery date, and any partial shipment plan."
