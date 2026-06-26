from __future__ import annotations

import json
from typing import Any

from app.domain.models import OperatorBrief, WorkflowRecord, WorkflowStatus


class BriefingService:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-5.4-mini",
        timeout_seconds: float = 20.0,
        client_factory=None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory

    def generate(self, workflow: WorkflowRecord) -> OperatorBrief:
        fallback = self._deterministic_brief(workflow)
        if not self.api_key:
            return self._fallback_with_reason(fallback, "openai_api_key_not_configured")
        try:
            return self._generate_with_llm(workflow, fallback)
        except Exception as exc:
            return self._fallback_with_reason(fallback, exc.__class__.__name__)

    def _generate_with_llm(self, workflow: WorkflowRecord, fallback: OperatorBrief) -> OperatorBrief:
        client = self._client()
        facts = self._workflow_facts(workflow)
        response = client.responses.create(
            model=self.model,
            reasoning={"effort": "low"},
            input=[
                {
                    "role": "system",
                    "content": (
                        "You create concise procurement operator briefs from validated workflow facts. "
                        "Use only the provided JSON facts. Do not invent suppliers, prices, dates, approvals, "
                        "ERP actions, or EDI details. Do not approve, reject, authorize, or claim an ERP update. "
                        "Return only a JSON object with exactly these string keys: summary, risk_assessment, "
                        "recommended_action, supplier_message_draft."
                    ),
                },
                {"role": "user", "content": json.dumps(facts, default=str, sort_keys=True)},
            ],
        )
        content = response.output_text.strip()
        parsed = self._parse_structured_output(content)
        return OperatorBrief(
            workflow_id=workflow.workflow_id,
            summary=parsed["summary"],
            risk_assessment=parsed["risk_assessment"],
            recommended_action=parsed["recommended_action"],
            supplier_message_draft=parsed["supplier_message_draft"],
            source="llm",
            model=self.model,
            metadata={"timeout_seconds": self.timeout_seconds, "facts_redacted": True},
        )

    def _client(self):
        if self.client_factory is not None:
            return self.client_factory(api_key=self.api_key, timeout=self.timeout_seconds)
        from openai import OpenAI

        return OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)

    def _deterministic_brief(self, workflow: WorkflowRecord) -> OperatorBrief:
        po_number = workflow.confirmation.purchase_order_number if workflow.confirmation else "unknown purchase order"
        supplier_id = workflow.confirmation.supplier_id if workflow.confirmation else "unknown supplier"
        decision = workflow.policy_decision.decision.value if workflow.policy_decision else "not evaluated"
        reasons = workflow.policy_decision.reasons if workflow.policy_decision else []
        difference_count = sum(len(comparison.differences) for comparison in workflow.comparisons)
        stockout_risk = any(impact.stockout_risk for impact in workflow.impacts)
        financial_variance = sum(impact.financial_variance for impact in workflow.impacts)

        summary = (
            f"Workflow {workflow.workflow_id} is {workflow.status.value} for {po_number} from {supplier_id}. "
            f"Policy decision is {decision}; {difference_count} line difference(s) were detected."
        )

        risk_parts = []
        if reasons:
            risk_parts.append("; ".join(reasons))
        if stockout_risk:
            risk_parts.append("At least one line has projected stockout risk.")
        if financial_variance:
            risk_parts.append(f"Total financial variance is {financial_variance:.2f}.")
        risk_assessment = " ".join(risk_parts) if risk_parts else "No material risk is currently identified."

        recommended_action = self._recommended_action(workflow.status)
        supplier_message_draft = self._supplier_message_draft(workflow, po_number)

        return OperatorBrief(
            workflow_id=workflow.workflow_id,
            summary=summary,
            risk_assessment=risk_assessment,
            recommended_action=recommended_action,
            supplier_message_draft=supplier_message_draft,
            source="deterministic",
            metadata={"facts_redacted": True},
        )

    def _recommended_action(self, status: WorkflowStatus) -> str:
        if status == WorkflowStatus.AWAITING_APPROVAL:
            return "Review the comparison, impact, and policy reasons before approving, rejecting, or requesting clarification."
        if status in {WorkflowStatus.MANUAL_REVIEW, WorkflowStatus.DEAD_LETTER}:
            return "Investigate the EDI payload, trading partner profile, and validation errors before taking operational action."
        if status == WorkflowStatus.RETRY_PENDING:
            return "Retry the failed external step after confirming the prior completed steps should not be repeated."
        if status == WorkflowStatus.COMPLETED:
            return "No operator action is required unless a later exception is reported."
        if status in {WorkflowStatus.REJECTED, WorkflowStatus.CLARIFICATION_REQUESTED}:
            return "Monitor supplier follow-up before reprocessing any revised acknowledgment."
        return "Continue monitoring the workflow until it reaches an approval, recovery, or completion state."

    def _supplier_message_draft(self, workflow: WorkflowRecord, po_number: str) -> str:
        if workflow.supplier_response:
            return workflow.supplier_response.body
        if workflow.status == WorkflowStatus.AWAITING_APPROVAL:
            return (
                f"Thank you for confirming purchase order {po_number}. We are reviewing the proposed changes "
                "and will respond once the review is complete."
            )
        if workflow.status in {WorkflowStatus.MANUAL_REVIEW, WorkflowStatus.DEAD_LETTER}:
            return (
                f"Thank you for sending the acknowledgment for purchase order {po_number}. We need to review "
                "the submitted details before they can be accepted."
            )
        return f"Thank you for confirming purchase order {po_number}."

    def _workflow_facts(self, workflow: WorkflowRecord) -> dict[str, Any]:
        facts = {
            "workflow_id": workflow.workflow_id,
            "status": workflow.status.value,
            "confirmation": workflow.confirmation.model_dump(mode="json") if workflow.confirmation else None,
            "purchase_order": workflow.purchase_order.model_dump(mode="json") if workflow.purchase_order else None,
            "comparisons": [comparison.model_dump(mode="json") for comparison in workflow.comparisons],
            "impacts": [impact.model_dump(mode="json") for impact in workflow.impacts],
            "policy_decision": workflow.policy_decision.model_dump(mode="json") if workflow.policy_decision else None,
            "risk_investigation": workflow.risk_investigation.model_dump(mode="json") if workflow.risk_investigation else None,
            "approval_history": [approval.model_dump(mode="json") for approval in workflow.approval_history],
            "supplier_response": workflow.supplier_response.model_dump(mode="json") if workflow.supplier_response else None,
            "latest_audit_events": [event.model_dump(mode="json") for event in workflow.audit_events[-8:]],
        }
        return self._redact(facts)

    def _parse_structured_output(self, content: str) -> dict[str, str]:
        parsed = json.loads(content)
        required = {"summary", "risk_assessment", "recommended_action", "supplier_message_draft"}
        if not isinstance(parsed, dict) or set(parsed.keys()) != required:
            raise ValueError("Operator brief output does not match the required schema.")
        for key, value in parsed.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Operator brief field {key} must be a non-empty string.")
            parsed[key] = value.strip()
        return parsed

    def _fallback_with_reason(self, fallback: OperatorBrief, reason: str) -> OperatorBrief:
        fallback.metadata = {
            **fallback.metadata,
            "fallback_reason": reason,
            "timeout_seconds": self.timeout_seconds,
        }
        return fallback

    def _redact(self, value: Any) -> Any:
        sensitive_keys = {"recipient", "approved_by", "email", "escalation_email"}
        if isinstance(value, dict):
            return {
                key: "[redacted]" if key in sensitive_keys and item is not None else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value
