from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    RECOVERABLE_ERROR = "RECOVERABLE_ERROR"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class WorkflowStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    PO_RETRIEVED = "PO_RETRIEVED"
    COMPARED = "COMPARED"
    IMPACT_ASSESSED = "IMPACT_ASSESSED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    AUTO_APPROVED = "AUTO_APPROVED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ERP_UPDATED = "ERP_UPDATED"
    SUPPLIER_NOTIFIED = "SUPPLIER_NOTIFIED"
    COMPLETED = "COMPLETED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DEAD_LETTER = "DEAD_LETTER"
    FAILED = "FAILED"


class PolicyDecisionType(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class EvaluationStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class EDIDelimiters(BaseModel):
    element: str
    segment: str
    component: str = ":"
    repetition: str = "^"


class Segment(BaseModel):
    tag: str
    elements: list[str]


class EDIParseResult(BaseModel):
    source_control_number: str
    transaction_type: str
    edi_version: str
    supplier_id: str | None = None
    purchase_order_number: str | None = None
    delimiters: EDIDelimiters
    validation_status: ValidationStatus
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    header_segments: list[Segment] = Field(default_factory=list)
    line_loops: list[dict[str, Any]] = Field(default_factory=list)
    segments_grouped: bool = False


class TradingPartnerProfile(BaseModel):
    profile_id: str
    supplier_id: str
    transaction_type: str
    edi_version: str
    version: int = 1
    status: ProfileStatus = ProfileStatus.PUBLISHED
    date_qualifiers: dict[str, str]
    ack_codes: dict[str, str]
    repeated_ack_policy: Literal["split_quantities", "manual_review"] = "manual_review"
    unknown_qualifier_policy: Literal["manual_review", "reject"] = "manual_review"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    archived_at: datetime | None = None


class SupplierConfirmationLine(BaseModel):
    supplier_line_id: str
    supplier_part_number: str
    internal_part_number: str | None = None
    quantity: int
    unit: str
    unit_price: float
    promised_date: date
    status: str
    warnings: list[str] = Field(default_factory=list)


class SupplierConfirmation(BaseModel):
    confirmation_id: str
    source_type: str = "x12_855"
    source_control_number: str
    edi_version: str
    trading_partner_profile_id: str
    validation_status: ValidationStatus
    purchase_order_number: str
    supplier_id: str
    confirmation_status: str
    currency: str = "USD"
    lines: list[SupplierConfirmationLine]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PurchaseOrderLine(BaseModel):
    line_id: str
    part_number: str
    quantity: int
    unit: str
    unit_price: float
    requested_date: date
    status: str = "released"


class PurchaseOrder(BaseModel):
    purchase_order_number: str
    supplier_id: str
    status: str = "released"
    currency: str = "USD"
    site_id: str = "SITE-01"
    lines: list[PurchaseOrderLine]


class Supplier(BaseModel):
    supplier_id: str
    name: str
    email: str
    part_aliases: dict[str, str] = Field(default_factory=dict)


class InventoryPosition(BaseModel):
    part_number: str
    on_hand: int


class DemandForecast(BaseModel):
    part_number: str
    daily_demand: int


class Difference(BaseModel):
    field: str
    original: Any
    confirmed: Any
    delta: float | int | None = None
    delta_percentage: float | None = None
    delta_days: int | None = None
    severity: Literal["low", "medium", "high"]


class LineComparisonResult(BaseModel):
    line_id: str
    match_status: Literal["matched", "unmatched", "manual_review"]
    supplier_line_id: str | None = None
    differences: list[Difference] = Field(default_factory=list)


class ImpactAssessment(BaseModel):
    purchase_order_number: str
    line_id: str
    stockout_risk: bool
    projected_shortage_quantity: int = 0
    projected_shortage_date: date | None = None
    financial_variance: float = 0
    recommendation: str


class PolicyConfig(BaseModel):
    policy_id: str = "POLICY-DEFAULT:v1"
    version: int = 1
    status: ProfileStatus = ProfileStatus.PUBLISHED
    exact_match_auto_approve: bool = True
    maximum_price_increase_percent: float = 1.0
    maximum_delivery_delay_days: int = 2
    maximum_order_value: float = 5000
    require_no_stockout_impact: bool = True
    policy_version: str = "2026.07.01"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    archived_at: datetime | None = None


class PolicyDecision(BaseModel):
    decision: PolicyDecisionType
    policy_version: str
    policy_id: str = "UNKNOWN"
    reasons: list[str] = Field(default_factory=list)


class ApprovalRecord(BaseModel):
    workflow_id: str
    decision: Literal["APPROVED", "REJECTED", "CLARIFICATION_REQUESTED"]
    approved_by: str
    approved_at: datetime = Field(default_factory=utc_now)
    comments: str = ""


class ERPUpdateCommand(BaseModel):
    workflow_id: str
    purchase_order_number: str
    line_updates: list[dict[str, Any]]
    idempotency_key: str


class SupplierResponse(BaseModel):
    workflow_id: str
    recipient: str
    subject: str
    body: str
    status: Literal["queued", "sent", "failed"] = "queued"


class AuditEvent(BaseModel):
    workflow_id: str
    event_type: str
    occurred_at: datetime = Field(default_factory=utc_now)
    correlation_id: str
    actor_type: Literal["system", "user"]
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRecord(BaseModel):
    workflow_id: str
    correlation_id: str
    status: WorkflowStatus
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    raw_payload_hash: str
    idempotency_key: str | None = None
    duplicate_of: str | None = None
    parse_result: EDIParseResult | None = None
    confirmation: SupplierConfirmation | None = None
    purchase_order: PurchaseOrder | None = None
    comparisons: list[LineComparisonResult] = Field(default_factory=list)
    impacts: list[ImpactAssessment] = Field(default_factory=list)
    policy_decision: PolicyDecision | None = None
    approval: ApprovalRecord | None = None
    erp_update_command: ERPUpdateCommand | None = None
    supplier_response: SupplierResponse | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)


class IngestRequest(BaseModel):
    edi_text: str


class ApprovalRequest(BaseModel):
    approved_by: str = "operator@procureops.local"
    comments: str = ""


class ProfileCreateRequest(BaseModel):
    supplier_id: str
    transaction_type: str = "855"
    edi_version: str = "004010"
    date_qualifiers: dict[str, str] = Field(default_factory=dict)
    ack_codes: dict[str, str] = Field(default_factory=dict)
    repeated_ack_policy: Literal["split_quantities", "manual_review"] = "manual_review"
    unknown_qualifier_policy: Literal["manual_review", "reject"] = "manual_review"


class ProfileUpdateRequest(BaseModel):
    date_qualifiers: dict[str, str] | None = None
    ack_codes: dict[str, str] | None = None
    repeated_ack_policy: Literal["split_quantities", "manual_review"] | None = None
    unknown_qualifier_policy: Literal["manual_review", "reject"] | None = None


class PolicyCreateRequest(BaseModel):
    exact_match_auto_approve: bool = True
    maximum_price_increase_percent: float = 1.0
    maximum_delivery_delay_days: int = 2
    maximum_order_value: float = 5000
    require_no_stockout_impact: bool = True
    policy_version: str = "draft-v1"


class PolicyUpdateRequest(BaseModel):
    exact_match_auto_approve: bool | None = None
    maximum_price_increase_percent: float | None = None
    maximum_delivery_delay_days: int | None = None
    maximum_order_value: float | None = None
    require_no_stockout_impact: bool | None = None
    policy_version: str | None = None


class EvaluationExpectation(BaseModel):
    workflow_status: WorkflowStatus
    policy_decision: PolicyDecisionType | None = None
    validation_status: ValidationStatus | None = None
    erp_update_executed: bool
    duplicate_of_existing: bool = False
    profile_id_contains: str | None = None


class EvaluationScenario(BaseModel):
    scenario_id: str
    name: str
    description: str = ""
    edi_file: str
    expectation: EvaluationExpectation


class EvaluationScenarioResult(BaseModel):
    scenario_id: str
    name: str
    status: EvaluationStatus
    workflow_id: str | None = None
    mismatches: list[str] = Field(default_factory=list)
    expected: EvaluationExpectation
    actual: dict[str, Any] = Field(default_factory=dict)


class EvaluationRun(BaseModel):
    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    status: EvaluationStatus
    total: int
    passed: int
    failed: int
    results: list[EvaluationScenarioResult]
