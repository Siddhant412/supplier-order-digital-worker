from __future__ import annotations

from datetime import date

from app.domain.models import (
    EDIParseResult,
    SupplierConfirmation,
    SupplierConfirmationLine,
    TradingPartnerProfile,
    ValidationStatus,
)
from app.services.profiles import TradingPartnerProfileRepository


class EDIInterpreter:
    def __init__(self, profiles: TradingPartnerProfileRepository) -> None:
        self.profiles = profiles

    def interpret(self, parse_result: EDIParseResult) -> SupplierConfirmation:
        errors = list(parse_result.errors)
        warnings = list(parse_result.warnings)
        profile = self.profiles.get(
            parse_result.supplier_id or "",
            parse_result.transaction_type,
            parse_result.edi_version,
        )
        if parse_result.validation_status == ValidationStatus.REJECTED:
            return self._manual_confirmation(parse_result, "rejected", warnings, errors)
        if profile is None:
            errors.append("No trading partner profile found.")
            return self._manual_confirmation(parse_result, "manual_review", warnings, errors)

        lines: list[SupplierConfirmationLine] = []
        for line_loop in parse_result.line_loops:
            line, line_warnings, line_errors = self._line_from_loop(line_loop, profile)
            warnings.extend(line_warnings)
            errors.extend(line_errors)
            if line:
                lines.append(line)

        validation_status = self._validation_status(errors, warnings)
        confirmation_status = "accepted"
        if errors:
            confirmation_status = "manual_review"
        elif any(line.status != "accepted" for line in lines):
            confirmation_status = "accepted_with_changes"

        return SupplierConfirmation(
            confirmation_id=f"ACK-{parse_result.source_control_number}",
            source_control_number=parse_result.source_control_number,
            edi_version=parse_result.edi_version,
            trading_partner_profile_id=profile.profile_id,
            validation_status=validation_status,
            purchase_order_number=parse_result.purchase_order_number or "UNKNOWN",
            supplier_id=parse_result.supplier_id or "UNKNOWN",
            confirmation_status=confirmation_status,
            lines=lines,
            warnings=warnings,
            errors=errors,
        )

    def _line_from_loop(
        self,
        line_loop: dict,
        profile: TradingPartnerProfile,
    ) -> tuple[SupplierConfirmationLine | None, list[str], list[str]]:
        warnings: list[str] = []
        errors: list[str] = []
        po1 = line_loop["po1"]
        ack_segments = line_loop["ack"]
        if not ack_segments:
            errors.append("Line is missing ACK segment.")
            return None, warnings, errors
        if len(ack_segments) > 1 and profile.repeated_ack_policy != "split_quantities":
            errors.append("Repeated ACK segments require manual review for this partner.")
            return None, warnings, errors

        ack = ack_segments[0]
        status_code = self._safe(ack, 1)
        canonical_status = profile.ack_codes.get(status_code or "")
        if canonical_status is None:
            errors.append(f"Unknown ACK code: {status_code}.")

        quantity = self._int(self._safe(ack, 2), "ACK quantity", errors)
        unit = self._safe(ack, 3, self._safe(po1, 3, "EA"))
        date_qualifier = self._safe(ack, 4)
        date_field = profile.date_qualifiers.get(date_qualifier or "")
        if date_field != "promised_delivery_date":
            errors.append(f"Unsupported or ambiguous date qualifier: {date_qualifier}.")
        promised_date = self._date(self._safe(ack, 5), "ACK date", errors)

        supplier_part, internal_part = self._part_numbers(po1)
        if len(ack_segments) > 1:
            warnings.append("Using first ACK segment for v1 canonical mapping; repeated segments remain visible in audit data.")

        if quantity is None or promised_date is None or canonical_status is None:
            return None, warnings, errors

        return (
            SupplierConfirmationLine(
                supplier_line_id=self._safe(po1, 1, "UNKNOWN"),
                supplier_part_number=supplier_part,
                internal_part_number=internal_part,
                quantity=quantity,
                unit=unit,
                unit_price=float(self._safe(po1, 4, 0)),
                promised_date=promised_date,
                status=canonical_status,
                warnings=warnings,
            ),
            warnings,
            errors,
        )

    def _manual_confirmation(
        self,
        parse_result: EDIParseResult,
        status: str,
        warnings: list[str],
        errors: list[str],
    ) -> SupplierConfirmation:
        return SupplierConfirmation(
            confirmation_id=f"ACK-{parse_result.source_control_number}",
            source_control_number=parse_result.source_control_number,
            edi_version=parse_result.edi_version,
            trading_partner_profile_id="UNKNOWN",
            validation_status=ValidationStatus.MANUAL_REVIEW_REQUIRED
            if status == "manual_review"
            else ValidationStatus.REJECTED,
            purchase_order_number=parse_result.purchase_order_number or "UNKNOWN",
            supplier_id=parse_result.supplier_id or "UNKNOWN",
            confirmation_status=status,
            lines=[],
            warnings=warnings,
            errors=errors,
        )

    def _validation_status(self, errors: list[str], warnings: list[str]) -> ValidationStatus:
        if errors:
            return ValidationStatus.MANUAL_REVIEW_REQUIRED
        if warnings:
            return ValidationStatus.VALID_WITH_WARNINGS
        return ValidationStatus.VALID

    def _part_numbers(self, po1) -> tuple[str, str | None]:
        supplier_part = "UNKNOWN"
        internal_part: str | None = None
        elements = po1.elements
        for index in range(6, len(elements) - 1, 2):
            qualifier = elements[index]
            value = elements[index + 1]
            if qualifier == "VP":
                supplier_part = value
            if qualifier == "BP":
                internal_part = value
        return supplier_part, internal_part

    def _date(self, value: str | None, label: str, errors: list[str]) -> date | None:
        if not value or len(value) != 8:
            errors.append(f"Invalid {label}.")
            return None
        try:
            return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
        except ValueError:
            errors.append(f"Invalid {label}.")
            return None

    def _int(self, value: str | None, label: str, errors: list[str]) -> int | None:
        try:
            return int(float(value or ""))
        except ValueError:
            errors.append(f"Invalid {label}.")
            return None

    def _safe(self, segment, index: int, default=None):
        if index >= len(segment.elements):
            return default
        value = segment.elements[index]
        return value if value != "" else default
