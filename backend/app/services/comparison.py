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

        if confirmation.currency != purchase_order.currency:
            results.append(
                LineComparisonResult(
                    line_id="HEADER",
                    match_status="matched",
                    differences=[
                        Difference(
                            field="currency",
                            original=purchase_order.currency,
                            confirmed=confirmation.currency,
                            severity="high",
                        )
                    ],
                )
            )

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
            match_status = "matched"
            if internal_part != po_line.part_number:
                if internal_part is None:
                    match_status = "manual_review"
                differences.append(
                    Difference(
                        field="part_number",
                        original=po_line.part_number,
                        confirmed=internal_part or confirmed.supplier_part_number,
                        severity="high",
                    )
                )
            effective_quantity = confirmed.quantity
            effective_unit = confirmed.unit
            effective_unit_price = confirmed.unit_price
            if confirmed.unit != po_line.unit:
                conversion_factor = supplier.unit_conversions.get(f"{po_line.part_number}:{confirmed.unit}:{po_line.unit}")
                if conversion_factor:
                    effective_quantity = int(confirmed.quantity * conversion_factor)
                    effective_unit = po_line.unit
                    effective_unit_price = round(confirmed.unit_price / conversion_factor, 4)
                    confirmed.normalized_quantity = effective_quantity
                    confirmed.normalized_unit = effective_unit
                    confirmed.normalized_unit_price = effective_unit_price
                else:
                    match_status = "manual_review"
                    differences.append(
                        Difference(field="unit", original=po_line.unit, confirmed=confirmed.unit, severity="high")
                    )
            if effective_quantity != po_line.quantity:
                differences.append(
                    Difference(
                        field="quantity",
                        original=po_line.quantity,
                        confirmed=effective_quantity,
                        delta=effective_quantity - po_line.quantity,
                        severity="high" if effective_quantity < po_line.quantity else "medium",
                    )
                )
            if effective_unit_price != po_line.unit_price:
                delta_percentage = round(((effective_unit_price - po_line.unit_price) / po_line.unit_price) * 100, 2)
                differences.append(
                    Difference(
                        field="unit_price",
                        original=po_line.unit_price,
                        confirmed=effective_unit_price,
                        delta=round(effective_unit_price - po_line.unit_price, 2),
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
                    match_status=match_status,  # type: ignore[arg-type]
                    differences=differences,
                )
            )
        return results
