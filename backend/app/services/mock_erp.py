from __future__ import annotations

from copy import deepcopy
from datetime import date

from app.domain.models import DemandForecast, InventoryPosition, PurchaseOrder, PurchaseOrderLine, Supplier
from app.services.erp import TransientERPError


class MockERPAdapter:
    def __init__(self, transient_lookup_failures: dict[str, int] | None = None) -> None:
        self.transient_lookup_failures = transient_lookup_failures or {}
        self.reset()

    def reset(self) -> None:
        self.purchase_orders: dict[str, PurchaseOrder] = {
            "PO-1042": PurchaseOrder(
                purchase_order_number="PO-1042",
                supplier_id="SUP-100",
                lines=[
                    PurchaseOrderLine(
                        line_id="1",
                        part_number="MOTOR-100",
                        quantity=500,
                        unit="EA",
                        unit_price=12.00,
                        requested_date=date(2026, 7, 10),
                    ),
                    PurchaseOrderLine(
                        line_id="2",
                        part_number="SENSOR-22",
                        quantity=200,
                        unit="EA",
                        unit_price=8.50,
                        requested_date=date(2026, 7, 12),
                    ),
                ],
            )
        }
        self.suppliers: dict[str, Supplier] = {
            "SUP-100": Supplier(
                supplier_id="SUP-100",
                name="Acme Components",
                email="orders@acme.example",
                part_aliases={"ACME-M100": "MOTOR-100", "ACME-S22": "SENSOR-22"},
                unit_conversions={"MOTOR-100:CA:EA": 10},
                escalation_email="procurement-leads@example.local",
            )
        }
        self.inventory: dict[str, InventoryPosition] = {
            "MOTOR-100": InventoryPosition(part_number="MOTOR-100", on_hand=20),
            "SENSOR-22": InventoryPosition(part_number="SENSOR-22", on_hand=500),
        }
        self.demand: dict[str, DemandForecast] = {
            "MOTOR-100": DemandForecast(part_number="MOTOR-100", daily_demand=10),
            "SENSOR-22": DemandForecast(part_number="SENSOR-22", daily_demand=5),
        }
        self.supplier_performance: dict[str, dict] = {
            "SUP-100": {
                "on_time_delivery_rate": 0.93,
                "quality_escape_rate": 0.01,
                "average_acknowledgment_response_hours": 6,
                "recent_exception_count": 2,
            }
        }
        self.alternate_suppliers: dict[str, list[dict]] = {
            "MOTOR-100": [
                {
                    "supplier_id": "SUP-220",
                    "supplier_name": "Northline Motion",
                    "available_quantity": 120,
                    "lead_time_days": 4,
                    "unit_price": 12.80,
                }
            ],
            "SENSOR-22": [
                {
                    "supplier_id": "SUP-330",
                    "supplier_name": "Vector Sensing",
                    "available_quantity": 75,
                    "lead_time_days": 6,
                    "unit_price": 8.95,
                }
            ],
        }

    def get_purchase_order(self, po_number: str) -> PurchaseOrder:
        remaining_failures = self.transient_lookup_failures.get(po_number, 0)
        if remaining_failures > 0:
            self.transient_lookup_failures[po_number] = remaining_failures - 1
            raise TransientERPError(f"Temporary ERP lookup outage for {po_number}.")
        return deepcopy(self.purchase_orders[po_number])

    def get_supplier(self, supplier_id: str) -> Supplier:
        return self.suppliers[supplier_id]

    def get_inventory_position(self, part_number: str) -> InventoryPosition:
        return self.inventory.get(part_number, InventoryPosition(part_number=part_number, on_hand=0))

    def get_demand(self, part_number: str) -> DemandForecast:
        return self.demand.get(part_number, DemandForecast(part_number=part_number, daily_demand=0))

    def search_purchase_orders(self, supplier_id: str | None = None, part_number: str | None = None) -> list[PurchaseOrder]:
        purchase_orders = list(self.purchase_orders.values())
        if supplier_id:
            purchase_orders = [po for po in purchase_orders if po.supplier_id == supplier_id]
        if part_number:
            purchase_orders = [
                po
                for po in purchase_orders
                if any(line.part_number == part_number for line in po.lines)
            ]
        return deepcopy(purchase_orders)

    def get_supplier_performance(self, supplier_id: str) -> dict:
        return deepcopy(
            self.supplier_performance.get(
                supplier_id,
                {
                    "on_time_delivery_rate": None,
                    "quality_escape_rate": None,
                    "average_acknowledgment_response_hours": None,
                    "recent_exception_count": None,
                },
            )
        )

    def get_alternate_suppliers(self, part_number: str, required_quantity: int = 0) -> list[dict]:
        suppliers = deepcopy(self.alternate_suppliers.get(part_number, []))
        if required_quantity:
            return [supplier for supplier in suppliers if supplier["available_quantity"] >= required_quantity]
        return suppliers

    def update_purchase_order_lines(self, po_number: str, line_updates: list[dict]) -> dict:
        before = self.get_purchase_order(po_number)
        po = self.purchase_orders[po_number]
        line_by_id = {line.line_id: line for line in po.lines}
        for update in line_updates:
            line = line_by_id[update["line_id"]]
            line.quantity = update.get("quantity", line.quantity)
            line.unit_price = update.get("unit_price", line.unit_price)
            line.requested_date = update.get("promised_date", line.requested_date)
            line.status = "confirmed"
        after = self.get_purchase_order(po_number)
        return {"before": before.model_dump(mode="json"), "after": after.model_dump(mode="json")}
