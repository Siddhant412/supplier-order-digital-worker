from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import PolicyConfig, PolicyCreateRequest, PolicyUpdateRequest, ProfileStatus, new_id, utc_now


def seed_policy() -> PolicyConfig:
    now = utc_now()
    return PolicyConfig(
        policy_id="POLICY-DEFAULT:v1",
        version=1,
        status=ProfileStatus.PUBLISHED,
        policy_version="2026.07.01",
        published_at=now,
        exact_match_auto_approve=True,
        maximum_price_increase_percent=1.0,
        maximum_delivery_delay_days=2,
        maximum_order_value=5000,
        require_no_stockout_impact=True,
    )


class PolicyConfigStore(Protocol):
    def get_active(self) -> PolicyConfig: ...

    def get_by_id(self, policy_id: str) -> PolicyConfig: ...

    def list(self) -> list[PolicyConfig]: ...

    def create(self, request: PolicyCreateRequest) -> PolicyConfig: ...

    def update(self, policy_id: str, request: PolicyUpdateRequest) -> PolicyConfig: ...

    def publish(self, policy_id: str) -> PolicyConfig: ...

    def archive(self, policy_id: str) -> PolicyConfig: ...


@dataclass
class PolicyConfigRepository:
    _policies: dict[str, PolicyConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self._policies:
            policy = seed_policy()
            self._policies[policy.policy_id] = policy

    def get_active(self) -> PolicyConfig:
        published = [policy for policy in self._policies.values() if policy.status == ProfileStatus.PUBLISHED]
        if not published:
            raise KeyError("No published policy found.")
        return max(published, key=lambda policy: policy.version)

    def get_by_id(self, policy_id: str) -> PolicyConfig:
        try:
            return self._policies[policy_id]
        except KeyError as exc:
            raise KeyError(policy_id) from exc

    def list(self) -> list[PolicyConfig]:
        return sorted(self._policies.values(), key=lambda policy: -policy.version)

    def create(self, request: PolicyCreateRequest) -> PolicyConfig:
        policy = PolicyConfig(
            policy_id=self._new_policy_id(1),
            version=1,
            status=ProfileStatus.DRAFT,
            policy_version=request.policy_version,
            exact_match_auto_approve=request.exact_match_auto_approve,
            maximum_price_increase_percent=request.maximum_price_increase_percent,
            maximum_delivery_delay_days=request.maximum_delivery_delay_days,
            maximum_order_value=request.maximum_order_value,
            require_no_stockout_impact=request.require_no_stockout_impact,
        )
        self._policies[policy.policy_id] = policy
        return policy

    def update(self, policy_id: str, request: PolicyUpdateRequest) -> PolicyConfig:
        existing = self.get_by_id(policy_id)
        policy = existing if existing.status == ProfileStatus.DRAFT else self._draft_from(existing)
        self._apply_update(policy, request)
        policy.updated_at = utc_now()
        self._policies[policy.policy_id] = policy
        return policy

    def publish(self, policy_id: str) -> PolicyConfig:
        policy = self.get_by_id(policy_id)
        now = utc_now()
        for other in self._policies.values():
            if other.policy_id != policy.policy_id and other.status == ProfileStatus.PUBLISHED:
                other.status = ProfileStatus.ARCHIVED
                other.archived_at = now
                other.updated_at = now
        policy.status = ProfileStatus.PUBLISHED
        policy.published_at = now
        policy.archived_at = None
        policy.updated_at = now
        if policy.policy_version.startswith("draft-"):
            policy.policy_version = f"policy-v{policy.version}"
        self._policies[policy.policy_id] = policy
        return policy

    def archive(self, policy_id: str) -> PolicyConfig:
        policy = self.get_by_id(policy_id)
        policy.status = ProfileStatus.ARCHIVED
        policy.archived_at = utc_now()
        policy.updated_at = policy.archived_at
        self._policies[policy.policy_id] = policy
        return policy

    def _draft_from(self, policy: PolicyConfig) -> PolicyConfig:
        version = self._next_version()
        draft = policy.model_copy(
            deep=True,
            update={
                "policy_id": self._new_policy_id(version),
                "version": version,
                "status": ProfileStatus.DRAFT,
                "policy_version": f"draft-v{version}",
                "published_at": None,
                "archived_at": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
        )
        self._policies[draft.policy_id] = draft
        return draft

    def _next_version(self) -> int:
        return max([policy.version for policy in self._policies.values()] or [0]) + 1

    def _new_policy_id(self, version: int) -> str:
        return f"POLICY:v{version}-{new_id('POL').split('-', 1)[1]}"

    def _apply_update(self, policy: PolicyConfig, request: PolicyUpdateRequest) -> None:
        for field, value in request.model_dump(exclude_unset=True).items():
            setattr(policy, field, value)
