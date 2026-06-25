from __future__ import annotations

from app.services.mock_erp import MockERPAdapter
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore
from app.services.workflow import WorkflowEngine


store = InMemoryStore()
erp = MockERPAdapter()
profiles = TradingPartnerProfileRepository()
workflow_engine = WorkflowEngine(store=store, erp=erp, profiles=profiles)
