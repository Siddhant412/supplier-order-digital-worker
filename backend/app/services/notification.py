from __future__ import annotations

from app.domain.models import Supplier, SupplierConfirmation, SupplierResponse, WorkflowRecord


class NotificationService:
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
