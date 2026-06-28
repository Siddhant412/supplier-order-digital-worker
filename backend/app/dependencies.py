from __future__ import annotations

import os
from pathlib import Path

from app.services.database import DatabasePolicyConfigRepository, DatabaseTradingPartnerProfileRepository, DatabaseWorkflowStore
from app.services.evaluations import EvaluationRunner
from app.services.briefing import BriefingService
from app.services.mock_erp import MockERPAdapter
from app.services.policies import PolicyConfigRepository
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


def create_profiles():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return TradingPartnerProfileRepository()
    profile_repo = DatabaseTradingPartnerProfileRepository(database_url)
    profile_repo.initialize()
    return profile_repo


def create_policies():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return PolicyConfigRepository()
    policy_repo = DatabasePolicyConfigRepository(database_url)
    policy_repo.initialize()
    return policy_repo


def find_project_root() -> Path:
    candidates = [Path("/app"), Path(__file__).resolve().parents[2]]
    for candidate in candidates:
        if (candidate / "evaluations" / "scenarios").exists() and (candidate / "sample-data").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


store = create_store()
erp = MockERPAdapter()
profiles = create_profiles()
policies = create_policies()
briefing_service = BriefingService(
    api_key=os.getenv("OPENAI_API_KEY") or None,
    model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
    timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20")),
)
workflow_engine = WorkflowEngine(
    store=store,
    erp=erp,
    profiles=profiles,
    policies=policies,
    investigation_api_key=os.getenv("OPENAI_API_KEY") or None,
    investigation_model=os.getenv("OPENAI_INVESTIGATION_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4-mini")),
    investigation_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20")),
    enable_llm_investigation=os.getenv("ENABLE_LLM_INVESTIGATION", "false").lower() == "true",
    briefing_service=briefing_service,
    auto_operator_brief=True,
)
project_root = find_project_root()
evaluation_runner = EvaluationRunner(
    store=store,
    profiles=profiles,
    policies=policies,
    scenario_dir=project_root / "evaluations" / "scenarios",
    project_root=project_root,
)
