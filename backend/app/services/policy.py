from __future__ import annotations

from app.domain.models import (
    ImpactAssessment,
    LineComparisonResult,
    PolicyConfig,
    PolicyDecision,
    PolicyDecisionType,
    SupplierConfirmation,
    ValidationStatus,
)


class PolicyEngine:
    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def evaluate(
        self,
        confirmation: SupplierConfirmation,
        comparisons: list[LineComparisonResult],
        impacts: list[ImpactAssessment],
    ) -> PolicyDecision:
        reasons: list[str] = []
        if confirmation.validation_status in {
            ValidationStatus.MANUAL_REVIEW_REQUIRED,
            ValidationStatus.RECOVERABLE_ERROR,
            ValidationStatus.REJECTED,
        }:
            reasons.extend(confirmation.errors or ["EDI validation requires review."])
            return PolicyDecision(
                decision=PolicyDecisionType.MANUAL_REVIEW,
                policy_version=self.config.policy_version,
                reasons=reasons,
            )

        all_differences = [difference for result in comparisons for difference in result.differences]
        if not all_differences and self.config.exact_match_auto_approve:
            return PolicyDecision(
                decision=PolicyDecisionType.AUTO_APPROVE,
                policy_version=self.config.policy_version,
                reasons=["Exact match and policy allows automatic confirmation."],
            )

        for difference in all_differences:
            if difference.field == "quantity" and (difference.delta or 0) < 0:
                reasons.append("Quantity reduction requires approval.")
            if difference.field == "unit_price" and (difference.delta_percentage or 0) > self.config.maximum_price_increase_percent:
                reasons.append(
                    f"Price increase exceeds {self.config.maximum_price_increase_percent}% threshold."
                )
            if difference.field == "delivery_date" and (difference.delta_days or 0) > self.config.maximum_delivery_delay_days:
                reasons.append(
                    f"Delivery delay exceeds {self.config.maximum_delivery_delay_days}-day threshold."
                )
            if difference.field in {"part_number", "unit"}:
                reasons.append(f"{difference.field} change requires approval.")

        if any(impact.stockout_risk for impact in impacts):
            reasons.append("Inventory impact creates stockout risk.")

        if reasons:
            return PolicyDecision(
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                policy_version=self.config.policy_version,
                reasons=reasons,
            )

        return PolicyDecision(
            decision=PolicyDecisionType.AUTO_APPROVE,
            policy_version=self.config.policy_version,
            reasons=["Differences are within configured automatic approval thresholds."],
        )
