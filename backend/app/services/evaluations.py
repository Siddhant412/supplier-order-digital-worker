from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import (
    EvaluationRun,
    EvaluationScenario,
    EvaluationScenarioResult,
    EvaluationStatus,
    IngestRequest,
    new_id,
)
from app.services.mock_erp import MockERPAdapter
from app.services.policies import PolicyConfigStore
from app.services.profiles import TradingPartnerProfileStore
from app.services.store import InMemoryStore, WorkflowStore
from app.services.workflow import WorkflowEngine


class EvaluationRunner:
    def __init__(
        self,
        store: WorkflowStore,
        profiles: TradingPartnerProfileStore,
        policies: PolicyConfigStore,
        scenario_dir: Path,
        project_root: Path,
    ) -> None:
        self.store = store
        self.profiles = profiles
        self.policies = policies
        self.scenario_dir = scenario_dir
        self.project_root = project_root

    def run_all(self) -> EvaluationRun:
        scenarios = self.load_scenarios()
        results = [self._run_scenario(scenario) for scenario in scenarios]
        passed = sum(1 for result in results if result.status == EvaluationStatus.PASSED)
        failed = len(results) - passed
        run = EvaluationRun(
            run_id=new_id("EVAL"),
            status=EvaluationStatus.PASSED if failed == 0 else EvaluationStatus.FAILED,
            total=len(results),
            passed=passed,
            failed=failed,
            results=results,
        )
        self.store.save_evaluation_run(run)
        return run

    def load_scenarios(self) -> list[EvaluationScenario]:
        scenarios = []
        for path in sorted(self.scenario_dir.glob("*.json")):
            scenarios.append(EvaluationScenario.model_validate(json.loads(path.read_text())))
        return scenarios

    def _run_scenario(self, scenario: EvaluationScenario) -> EvaluationScenarioResult:
        # Evaluation scenarios should not affect each other's idempotency keys or ERP update markers.
        engine = WorkflowEngine(InMemoryStore(), MockERPAdapter(), self.profiles, self.policies)
        edi_text = (self.project_root / scenario.edi_file).read_text()
        workflow = engine.start(IngestRequest(edi_text=edi_text))
        actual = {
            "workflow_status": workflow.status.value,
            "policy_decision": workflow.policy_decision.decision.value if workflow.policy_decision else None,
            "validation_status": workflow.confirmation.validation_status.value if workflow.confirmation else None,
            "erp_update_executed": workflow.erp_update_command is not None,
            "duplicate_of_existing": workflow.duplicate_of is not None,
            "profile_id": workflow.confirmation.trading_partner_profile_id if workflow.confirmation else None,
        }
        mismatches = self._compare(scenario, actual)
        return EvaluationScenarioResult(
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            status=EvaluationStatus.PASSED if not mismatches else EvaluationStatus.FAILED,
            workflow_id=workflow.workflow_id,
            mismatches=mismatches,
            expected=scenario.expectation,
            actual=actual,
        )

    def _compare(self, scenario: EvaluationScenario, actual: dict) -> list[str]:
        expected = scenario.expectation
        mismatches: list[str] = []
        self._expect(mismatches, "workflow_status", expected.workflow_status.value, actual["workflow_status"])
        self._expect(
            mismatches,
            "policy_decision",
            expected.policy_decision.value if expected.policy_decision else None,
            actual["policy_decision"],
        )
        self._expect(
            mismatches,
            "validation_status",
            expected.validation_status.value if expected.validation_status else None,
            actual["validation_status"],
        )
        self._expect(mismatches, "erp_update_executed", expected.erp_update_executed, actual["erp_update_executed"])
        self._expect(mismatches, "duplicate_of_existing", expected.duplicate_of_existing, actual["duplicate_of_existing"])
        if expected.profile_id_contains and expected.profile_id_contains not in (actual.get("profile_id") or ""):
            mismatches.append(
                f"profile_id expected to contain {expected.profile_id_contains!r}, got {actual.get('profile_id')!r}"
            )
        return mismatches

    def _expect(self, mismatches: list[str], field: str, expected, actual) -> None:
        if expected != actual:
            mismatches.append(f"{field}: expected {expected!r}, got {actual!r}")
