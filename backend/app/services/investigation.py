from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import (
    PolicyDecisionType,
    ReadOnlyToolRequest,
    ReadOnlyToolResult,
    RiskInvestigation,
    WorkflowRecord,
)
from app.services.erp import ERPAdapter
from app.services.profiles import TradingPartnerProfileStore


class InvestigationPlan(BaseModel):
    observations: list[str] = Field(default_factory=list)
    tool_requests: list[ReadOnlyToolRequest] = Field(default_factory=list)
    recommendation: str


class BoundedInvestigationAgent:
    """Read-only planner for risky workflows.

    The agent can gather context and recommend an operator action, but it cannot
    approve, reject, or mutate ERP state.
    """

    def __init__(
        self,
        erp: ERPAdapter,
        profiles: TradingPartnerProfileStore,
        api_key: str | None = None,
        model: str = "gpt-5.4-mini",
        timeout_seconds: float = 20.0,
        enable_llm_planning: bool = False,
        client_factory=None,
    ) -> None:
        self.erp = erp
        self.profiles = profiles
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.enable_llm_planning = enable_llm_planning
        self.client_factory = client_factory

    def investigate(self, workflow: WorkflowRecord) -> RiskInvestigation | None:
        if workflow.policy_decision is None:
            return None
        if workflow.policy_decision.decision != PolicyDecisionType.REQUIRE_APPROVAL:
            return None
        if workflow.confirmation is None or workflow.purchase_order is None:
            return None

        plan, source = self._build_plan(workflow)
        observations = plan.observations
        tool_requests = plan.tool_requests
        tool_results = [self._execute(request, workflow) for request in tool_requests]
        return RiskInvestigation(
            workflow_id=workflow.workflow_id,
            observations=observations,
            tool_requests=tool_requests,
            tool_results=tool_results,
            recommendation=plan.recommendation or self._recommendation(workflow, tool_results),
            source=source,  # type: ignore[arg-type]
            model=self.model if source == "llm" else None,
        )

    def _build_plan(self, workflow: WorkflowRecord) -> tuple[InvestigationPlan, str]:
        fallback = InvestigationPlan(
            observations=self._observations(workflow),
            tool_requests=self._plan(workflow),
            recommendation="",
        )
        if not self.enable_llm_planning or not self.api_key:
            return fallback, "deterministic"
        try:
            return self._build_plan_with_llm(workflow, fallback), "llm"
        except Exception:
            return fallback, "deterministic"

    def _build_plan_with_llm(self, workflow: WorkflowRecord, fallback: InvestigationPlan) -> InvestigationPlan:
        client = self._client()
        facts = {
            "workflow_id": workflow.workflow_id,
            "confirmation": workflow.confirmation.model_dump(mode="json") if workflow.confirmation else None,
            "purchase_order": workflow.purchase_order.model_dump(mode="json") if workflow.purchase_order else None,
            "comparisons": [comparison.model_dump(mode="json") for comparison in workflow.comparisons],
            "impacts": [impact.model_dump(mode="json") for impact in workflow.impacts],
            "policy_decision": workflow.policy_decision.model_dump(mode="json") if workflow.policy_decision else None,
            "allowed_tools": [
                "get_purchase_order",
                "search_purchase_orders",
                "get_inventory_by_site",
                "get_open_demand",
                "get_supplier_performance",
                "get_part_aliases",
                "get_alternate_suppliers",
                "get_partner_profile",
            ],
            "fallback_plan": fallback.model_dump(mode="json"),
        }
        response = client.responses.create(
            model=self.model,
            reasoning={"effort": "low"},
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a bounded procurement investigation planner. Use only the provided JSON facts. "
                        "You may request only allowlisted read-only tools. Do not approve, reject, authorize, "
                        "update ERP records, send supplier communications, or invent facts. Return only JSON with "
                        "keys observations, tool_requests, recommendation. tool_requests must contain tool, "
                        "arguments, and reason."
                    ),
                },
                {"role": "user", "content": json.dumps(self._redact(facts), default=str, sort_keys=True)},
            ],
        )
        parsed = json.loads(response.output_text.strip())
        plan = InvestigationPlan.model_validate(parsed)
        if not plan.observations or not plan.tool_requests or not plan.recommendation.strip():
            raise ValueError("Investigation plan is incomplete.")
        return plan

    def _client(self):
        if self.client_factory is not None:
            return self.client_factory(api_key=self.api_key, timeout=self.timeout_seconds)
        from openai import OpenAI

        return OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)

    def _observations(self, workflow: WorkflowRecord) -> list[str]:
        observations = []
        for comparison in workflow.comparisons:
            for difference in comparison.differences:
                observations.append(
                    f"Line {comparison.line_id} has {difference.field} changed from "
                    f"{difference.original} to {difference.confirmed}."
                )
        for impact in workflow.impacts:
            if impact.stockout_risk:
                observations.append(
                    f"Line {impact.line_id} has projected shortage risk of "
                    f"{impact.projected_shortage_quantity} unit(s)."
                )
            if impact.financial_variance:
                observations.append(
                    f"Line {impact.line_id} changes financial exposure by {impact.financial_variance:.2f}."
                )
        if workflow.policy_decision and workflow.policy_decision.reasons:
            observations.extend(workflow.policy_decision.reasons)
        return observations or ["Policy requires approval before ERP mutation."]

    def _plan(self, workflow: WorkflowRecord) -> list[ReadOnlyToolRequest]:
        assert workflow.confirmation is not None
        requests = [
            ReadOnlyToolRequest(
                tool="get_purchase_order",
                arguments={"purchase_order_number": workflow.confirmation.purchase_order_number},
                reason="Confirm the original order context before recommending an action.",
            ),
            ReadOnlyToolRequest(
                tool="get_supplier_performance",
                arguments={"supplier_id": workflow.confirmation.supplier_id},
                reason="Check whether recent supplier performance changes the review priority.",
            ),
            ReadOnlyToolRequest(
                tool="get_partner_profile",
                arguments={
                    "supplier_id": workflow.confirmation.supplier_id,
                    "transaction_type": "855",
                    "edi_version": workflow.confirmation.edi_version,
                },
                reason="Confirm which trading-partner interpretation profile was used.",
            ),
        ]

        for part_number in self._affected_parts(workflow):
            requests.extend(
                [
                    ReadOnlyToolRequest(
                        tool="get_inventory_by_site",
                        arguments={"part_number": part_number, "site_id": workflow.purchase_order.site_id if workflow.purchase_order else "SITE-01"},
                        reason="Determine whether the supplier change creates a shortage risk.",
                    ),
                    ReadOnlyToolRequest(
                        tool="get_open_demand",
                        arguments={"part_number": part_number},
                        reason="Quantify expected demand while the changed supplier commitment is reviewed.",
                    ),
                    ReadOnlyToolRequest(
                        tool="get_part_aliases",
                        arguments={"supplier_id": workflow.confirmation.supplier_id, "part_number": part_number},
                        reason="Confirm supplier/internal part alias context.",
                    ),
                    ReadOnlyToolRequest(
                        tool="get_alternate_suppliers",
                        arguments={"part_number": part_number, "required_quantity": self._shortage_quantity(workflow, part_number)},
                        reason="Identify potential mitigation options for a shortage or quantity reduction.",
                    ),
                    ReadOnlyToolRequest(
                        tool="search_purchase_orders",
                        arguments={"supplier_id": workflow.confirmation.supplier_id, "part_number": part_number},
                        reason="Find related open purchase-order context for the affected part.",
                    ),
                ]
            )
        return requests

    def _execute(self, request: ReadOnlyToolRequest, workflow: WorkflowRecord) -> ReadOnlyToolResult:
        arguments = request.arguments
        if request.tool == "get_purchase_order":
            result = self.erp.get_purchase_order(arguments["purchase_order_number"]).model_dump(mode="json")
        elif request.tool == "search_purchase_orders":
            result = [
                po.model_dump(mode="json")
                for po in self.erp.search_purchase_orders(arguments.get("supplier_id"), arguments.get("part_number"))
            ]
        elif request.tool == "get_inventory_by_site":
            result = self.erp.get_inventory_position(arguments["part_number"]).model_dump(mode="json") | {
                "site_id": arguments.get("site_id")
            }
        elif request.tool == "get_open_demand":
            result = self.erp.get_demand(arguments["part_number"]).model_dump(mode="json")
        elif request.tool == "get_supplier_performance":
            result = self.erp.get_supplier_performance(arguments["supplier_id"])
        elif request.tool == "get_part_aliases":
            supplier = self.erp.get_supplier(arguments["supplier_id"])
            result = {
                "supplier_id": supplier.supplier_id,
                "requested_part_number": arguments.get("part_number"),
                "aliases": supplier.part_aliases,
            }
        elif request.tool == "get_alternate_suppliers":
            result = self.erp.get_alternate_suppliers(arguments["part_number"], arguments.get("required_quantity", 0))
        elif request.tool == "get_partner_profile":
            profile = self.profiles.get(
                arguments["supplier_id"],
                arguments["transaction_type"],
                arguments["edi_version"],
            )
            result = profile.model_dump(mode="json") if profile else None
        else:  # pragma: no cover - pydantic Literal guards this.
            result = {"error": "unsupported_tool"}
        return ReadOnlyToolResult(tool=request.tool, arguments=arguments, result=self._redact(result))

    def _recommendation(self, workflow: WorkflowRecord, tool_results: list[ReadOnlyToolResult]) -> str:
        stockout_risk = any(impact.stockout_risk for impact in workflow.impacts)
        alternate_count = sum(
            len(result.result)
            for result in tool_results
            if result.tool == "get_alternate_suppliers" and isinstance(result.result, list)
        )
        if stockout_risk and alternate_count:
            return "Review approval carefully; shortage risk exists and alternate supplier options are available for mitigation."
        if stockout_risk:
            return "Escalate for approval because the changed confirmation can create a shortage and no mitigation was confirmed."
        return "Review policy reasons and comparison details before approving, rejecting, or requesting clarification."

    def _affected_parts(self, workflow: WorkflowRecord) -> list[str]:
        parts: list[str] = []
        po_lines = {line.line_id: line for line in workflow.purchase_order.lines} if workflow.purchase_order else {}
        for comparison in workflow.comparisons:
            po_line = po_lines.get(comparison.line_id)
            if po_line and po_line.part_number not in parts:
                parts.append(po_line.part_number)
        return parts

    def _shortage_quantity(self, workflow: WorkflowRecord, part_number: str) -> int:
        if not workflow.purchase_order:
            return 0
        line_ids = [line.line_id for line in workflow.purchase_order.lines if line.part_number == part_number]
        return max(
            [impact.projected_shortage_quantity for impact in workflow.impacts if impact.line_id in line_ids] or [0]
        )

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[redacted]" if key in {"email", "escalation_email"} and item is not None else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value
