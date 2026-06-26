from __future__ import annotations

from typing import Protocol

from app.domain.models import DemandForecast, InventoryPosition, PurchaseOrder, Supplier


class TransientERPError(RuntimeError):
    pass


class ERPAdapter(Protocol):
    def get_purchase_order(self, po_number: str) -> PurchaseOrder: ...

    def get_supplier(self, supplier_id: str) -> Supplier: ...

    def get_inventory_position(self, part_number: str) -> InventoryPosition: ...

    def get_demand(self, part_number: str) -> DemandForecast: ...

    def update_purchase_order_lines(self, po_number: str, line_updates: list[dict]) -> dict: ...
