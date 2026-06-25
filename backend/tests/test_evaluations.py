from pathlib import Path

from app.domain.models import EvaluationStatus
from app.services.evaluations import EvaluationRunner
from app.services.policies import PolicyConfigRepository
from app.services.profiles import TradingPartnerProfileRepository
from app.services.store import InMemoryStore


ROOT = Path(__file__).resolve().parents[2]


def test_evaluation_runner_executes_scenarios_and_persists_run():
    store = InMemoryStore()
    runner = EvaluationRunner(
        store=store,
        profiles=TradingPartnerProfileRepository(),
        policies=PolicyConfigRepository(),
        scenario_dir=ROOT / "evaluations" / "scenarios",
        project_root=ROOT,
    )

    run = runner.run_all()

    assert run.total >= 4
    assert run.status == EvaluationStatus.PASSED
    assert run.failed == 0
    assert store.get_evaluation_run(run.run_id).run_id == run.run_id
