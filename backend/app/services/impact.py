from __future__ import annotations

from datetime import timedelta

from app.domain.models import ImpactAssessment, LineComparisonResult, PurchaseOrder, SupplierConfirmation
from app.services.mock_erp import MockERPAdapter


class ImpactAssessmentService:
    def __init__(self, erp: MockERPAdapter) -> None:
        self.erp = erp

    def assess(
        self,
        confirmation: SupplierConfirmation,
        purchase_order: PurchaseOrder,
        comparisons: list[LineComparisonResult],
    ) -> list[ImpactAssessment]:
        confirmed_by_line = {line.supplier_line_id: line for line in confirmation.lines}
        po_by_line = {line.line_id: line for line in purchase_order.lines}
        impacts: list[ImpactAssessment] = []

        for comparison in comparisons:
            po_line = po_by_line.get(comparison.line_id)
            confirmed = confirmed_by_line.get(comparison.supplier_line_id or "")
            if po_line is None or confirmed is None:
                continue
            inventory = self.erp.get_inventory_position(po_line.part_number)
            demand = self.erp.get_demand(po_line.part_number)
            delay_days = max((confirmed.promised_date - po_line.requested_date).days, 0)
            delayed_demand = delay_days * demand.daily_demand
            shortage = max(delayed_demand - inventory.on_hand, 0)
            quantity_reduction = max(po_line.quantity - confirmed.quantity, 0)
            if quantity_reduction:
                shortage += quantity_reduction
            financial_variance = round((confirmed.unit_price - po_line.unit_price) * confirmed.quantity, 2)
            stockout_risk = shortage > 0
            recommendation = "Accept automatically; no material operational impact detected."
            if stockout_risk:
                shortage_date = po_line.requested_date + timedelta(days=max(inventory.on_hand // max(demand.daily_demand, 1), 0))
                recommendation = (
                    f"Require approval. Projected shortage of {shortage} units for {po_line.part_number}; "
                    "request expedited partial delivery or alternate supply."
                )
            elif comparison.differences:
                recommendation = "Review differences before accepting supplier changes."

            impacts.append(
                ImpactAssessment(
                    purchase_order_number=purchase_order.purchase_order_number,
                    line_id=po_line.line_id,
                    stockout_risk=stockout_risk,
                    projected_shortage_quantity=shortage,
                    projected_shortage_date=shortage_date if stockout_risk else None,
                    financial_variance=financial_variance,
                    recommendation=recommendation,
                )
            )
        return impacts
