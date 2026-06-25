from __future__ import annotations

import os

from app.services.database import DatabaseWorkflowStore
from app.services.mock_erp import MockERPAdapter
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore
from app.services.workflow import WorkflowEngine


def create_store():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return InMemoryStore()
    db_store = DatabaseWorkflowStore(database_url)
    db_store.initialize()
    return db_store


store = create_store()
erp = MockERPAdapter()
profiles = TradingPartnerProfileRepository()
workflow_engine = WorkflowEngine(store=store, erp=erp, profiles=profiles)
