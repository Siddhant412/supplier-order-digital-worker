from __future__ import annotations

from app.domain.models import Difference, LineComparisonResult, PurchaseOrder, Supplier, SupplierConfirmation


class ComparisonEngine:
    def compare(
        self,
        confirmation: SupplierConfirmation,
        purchase_order: PurchaseOrder,
        supplier: Supplier,
    ) -> list[LineComparisonResult]:
        po_lines = {line.line_id: line for line in purchase_order.lines}
        results: list[LineComparisonResult] = []

        for confirmed in confirmation.lines:
            internal_part = confirmed.internal_part_number or supplier.part_aliases.get(confirmed.supplier_part_number)
            po_line = po_lines.get(confirmed.supplier_line_id)
            if po_line is None:
                results.append(
                    LineComparisonResult(
                        line_id="UNKNOWN",
                        supplier_line_id=confirmed.supplier_line_id,
                        match_status="unmatched",
                        differences=[
                            Difference(
                                field="line_id",
                                original=None,
                                confirmed=confirmed.supplier_line_id,
                                severity="high",
                            )
                        ],
                    )
                )
                continue

            differences: list[Difference] = []
            if internal_part != po_line.part_number:
                differences.append(
                    Difference(
                        field="part_number",
                        original=po_line.part_number,
                        confirmed=internal_part or confirmed.supplier_part_number,
                        severity="high",
                    )
                )
            if confirmed.quantity != po_line.quantity:
                differences.append(
                    Difference(
                        field="quantity",
                        original=po_line.quantity,
                        confirmed=confirmed.quantity,
                        delta=confirmed.quantity - po_line.quantity,
                        severity="high" if confirmed.quantity < po_line.quantity else "medium",
                    )
                )
            if confirmed.unit != po_line.unit:
                differences.append(
                    Difference(field="unit", original=po_line.unit, confirmed=confirmed.unit, severity="high")
                )
            if confirmed.unit_price != po_line.unit_price:
                delta_percentage = round(((confirmed.unit_price - po_line.unit_price) / po_line.unit_price) * 100, 2)
                differences.append(
                    Difference(
                        field="unit_price",
                        original=po_line.unit_price,
                        confirmed=confirmed.unit_price,
                        delta=round(confirmed.unit_price - po_line.unit_price, 2),
                        delta_percentage=delta_percentage,
                        severity="high" if delta_percentage > 1 else "medium",
                    )
                )
            if confirmed.promised_date != po_line.requested_date:
                delta_days = (confirmed.promised_date - po_line.requested_date).days
                differences.append(
                    Difference(
                        field="delivery_date",
                        original=po_line.requested_date,
                        confirmed=confirmed.promised_date,
                        delta_days=delta_days,
                        severity="medium" if delta_days <= 5 else "high",
                    )
                )

            results.append(
                LineComparisonResult(
                    line_id=po_line.line_id,
                    supplier_line_id=confirmed.supplier_line_id,
                    match_status="matched",
                    differences=differences,
                )
            )
        return results
