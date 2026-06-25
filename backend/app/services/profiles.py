from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import (
    ProfileCreateRequest,
    ProfileStatus,
    ProfileUpdateRequest,
    TradingPartnerProfile,
    new_id,
    utc_now,
)


def seed_profile() -> TradingPartnerProfile:
    now = utc_now()
    return TradingPartnerProfile(
        profile_id="SUP-100:855:004010:v1",
        supplier_id="SUP-100",
        transaction_type="855",
        edi_version="004010",
        version=1,
        status=ProfileStatus.PUBLISHED,
        published_at=now,
        date_qualifiers={
            "067": "promised_delivery_date",
            "068": "promised_delivery_date",
            "002": "requested_delivery_date",
        },
        ack_codes={
            "IA": "accepted",
            "IQ": "accepted_quantity_changed",
            "IR": "rejected",
            "IB": "backordered",
        },
        repeated_ack_policy="split_quantities",
        unknown_qualifier_policy="manual_review",
    )


class TradingPartnerProfileStore(Protocol):
    def get(self, supplier_id: str, transaction_type: str, edi_version: str) -> TradingPartnerProfile | None: ...

    def get_by_id(self, profile_id: str) -> TradingPartnerProfile: ...

    def list(self) -> list[TradingPartnerProfile]: ...

    def create(self, request: ProfileCreateRequest) -> TradingPartnerProfile: ...

    def update(self, profile_id: str, request: ProfileUpdateRequest) -> TradingPartnerProfile: ...

    def publish(self, profile_id: str) -> TradingPartnerProfile: ...

    def archive(self, profile_id: str) -> TradingPartnerProfile: ...


@dataclass
class TradingPartnerProfileRepository:
    _profiles: dict[str, TradingPartnerProfile] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self._profiles:
            profile = seed_profile()
            self._profiles[profile.profile_id] = profile

    def get(self, supplier_id: str, transaction_type: str, edi_version: str) -> TradingPartnerProfile | None:
        candidates = [
            profile
            for profile in self._profiles.values()
            if profile.supplier_id == supplier_id
            and profile.transaction_type == transaction_type
            and profile.edi_version == edi_version
            and profile.status == ProfileStatus.PUBLISHED
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda profile: profile.version)

    def get_by_id(self, profile_id: str) -> TradingPartnerProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise KeyError(profile_id) from exc

    def list(self) -> list[TradingPartnerProfile]:
        return sorted(
            self._profiles.values(),
            key=lambda profile: (profile.supplier_id, profile.transaction_type, profile.edi_version, -profile.version),
        )

    def create(self, request: ProfileCreateRequest) -> TradingPartnerProfile:
        profile = TradingPartnerProfile(
            profile_id=self._new_profile_id(request.supplier_id, request.transaction_type, request.edi_version, 1),
            supplier_id=request.supplier_id,
            transaction_type=request.transaction_type,
            edi_version=request.edi_version,
            version=1,
            status=ProfileStatus.DRAFT,
            date_qualifiers=request.date_qualifiers,
            ack_codes=request.ack_codes,
            repeated_ack_policy=request.repeated_ack_policy,
            unknown_qualifier_policy=request.unknown_qualifier_policy,
        )
        self._profiles[profile.profile_id] = profile
        return profile

    def update(self, profile_id: str, request: ProfileUpdateRequest) -> TradingPartnerProfile:
        existing = self.get_by_id(profile_id)
        profile = existing if existing.status == ProfileStatus.DRAFT else self._draft_from(existing)
        self._apply_update(profile, request)
        profile.updated_at = utc_now()
        self._profiles[profile.profile_id] = profile
        return profile

    def publish(self, profile_id: str) -> TradingPartnerProfile:
        profile = self.get_by_id(profile_id)
        now = utc_now()
        for other in self._profiles.values():
            if (
                other.profile_id != profile.profile_id
                and other.supplier_id == profile.supplier_id
                and other.transaction_type == profile.transaction_type
                and other.edi_version == profile.edi_version
                and other.status == ProfileStatus.PUBLISHED
            ):
                other.status = ProfileStatus.ARCHIVED
                other.archived_at = now
                other.updated_at = now
        profile.status = ProfileStatus.PUBLISHED
        profile.published_at = now
        profile.updated_at = now
        self._profiles[profile.profile_id] = profile
        return profile

    def archive(self, profile_id: str) -> TradingPartnerProfile:
        profile = self.get_by_id(profile_id)
        profile.status = ProfileStatus.ARCHIVED
        profile.archived_at = utc_now()
        profile.updated_at = profile.archived_at
        self._profiles[profile.profile_id] = profile
        return profile

    def _draft_from(self, profile: TradingPartnerProfile) -> TradingPartnerProfile:
        next_version = self._next_version(profile.supplier_id, profile.transaction_type, profile.edi_version)
        draft = profile.model_copy(
            deep=True,
            update={
                "profile_id": self._new_profile_id(
                    profile.supplier_id,
                    profile.transaction_type,
                    profile.edi_version,
                    next_version,
                ),
                "version": next_version,
                "status": ProfileStatus.DRAFT,
                "published_at": None,
                "archived_at": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
        )
        self._profiles[draft.profile_id] = draft
        return draft

    def _next_version(self, supplier_id: str, transaction_type: str, edi_version: str) -> int:
        versions = [
            profile.version
            for profile in self._profiles.values()
            if profile.supplier_id == supplier_id
            and profile.transaction_type == transaction_type
            and profile.edi_version == edi_version
        ]
        return max(versions or [0]) + 1

    def _new_profile_id(self, supplier_id: str, transaction_type: str, edi_version: str, version: int) -> str:
        return f"{supplier_id}:{transaction_type}:{edi_version}:v{version}-{new_id('PROF').split('-', 1)[1]}"

    def _apply_update(self, profile: TradingPartnerProfile, request: ProfileUpdateRequest) -> None:
        if request.date_qualifiers is not None:
            profile.date_qualifiers = request.date_qualifiers
        if request.ack_codes is not None:
            profile.ack_codes = request.ack_codes
        if request.repeated_ack_policy is not None:
            profile.repeated_ack_policy = request.repeated_ack_policy
        if request.unknown_qualifier_policy is not None:
            profile.unknown_qualifier_policy = request.unknown_qualifier_policy
