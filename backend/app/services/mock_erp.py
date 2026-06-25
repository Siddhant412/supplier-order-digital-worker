from __future__ import annotations

from copy import deepcopy
from datetime import date

from app.domain.models import DemandForecast, InventoryPosition, PurchaseOrder, PurchaseOrderLine, Supplier


class MockERPAdapter:
    def __init__(self) -> None:
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

    def get_purchase_order(self, po_number: str) -> PurchaseOrder:
        return deepcopy(self.purchase_orders[po_number])

    def get_supplier(self, supplier_id: str) -> Supplier:
        return self.suppliers[supplier_id]

    def get_inventory_position(self, part_number: str) -> InventoryPosition:
        return self.inventory.get(part_number, InventoryPosition(part_number=part_number, on_hand=0))

    def get_demand(self, part_number: str) -> DemandForecast:
        return self.demand.get(part_number, DemandForecast(part_number=part_number, daily_demand=0))

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
