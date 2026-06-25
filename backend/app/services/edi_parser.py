from __future__ import annotations

from app.domain.models import EDIDelimiters, EDIParseResult, Segment, ValidationStatus


class EDIParser:
    def parse(self, raw_edi: str) -> EDIParseResult:
        normalized = self._normalize(raw_edi)
        errors: list[str] = []
        warnings: list[str] = []

        if not normalized.startswith("ISA"):
            return self._rejected("UNKNOWN", "UNKNOWN", "UNKNOWN", ["EDI payload must start with ISA."])

        element_separator = normalized[3]
        segment_terminator = self._detect_segment_terminator(normalized, element_separator)
        segments = [
            Segment(tag=parts[0], elements=parts)
            for segment in normalized.split(segment_terminator)
            if (parts := segment.split(element_separator)) and parts[0]
        ]

        isa = self._first(segments, "ISA")
        gs = self._first(segments, "GS")
        st = self._first(segments, "ST")
        se = self._first(segments, "SE")
        ge = self._first(segments, "GE")
        iea = self._first(segments, "IEA")
        bak = self._first(segments, "BAK")

        if not all([isa, gs, st, se, ge, iea]):
            errors.append("Missing required X12 envelope segment.")

        transaction_type = self._safe(st, 1, "UNKNOWN")
        source_control_number = self._safe(st, 2, "UNKNOWN")
        edi_version = self._safe(gs, 8, "UNKNOWN")
        purchase_order_number = self._safe(bak, 3, None)
        supplier_id = self._supplier_id(segments)

        if transaction_type != "855":
            errors.append(f"Unsupported transaction type: {transaction_type}.")
        if not purchase_order_number:
            errors.append("Missing purchase order number in BAK segment.")
        if not supplier_id:
            errors.append("Missing supplier identifier in N1*SU segment.")

        self._validate_control_numbers(st, se, gs, ge, isa, iea, errors)
        header_segments, line_loops = self._group_segments(segments, warnings)
        if not line_loops:
            errors.append("No PO1 line loops found.")

        status = self._status(errors, warnings)
        return EDIParseResult(
            source_control_number=source_control_number,
            transaction_type=transaction_type,
            edi_version=edi_version,
            supplier_id=supplier_id,
            purchase_order_number=purchase_order_number,
            delimiters=EDIDelimiters(
                element=element_separator,
                segment=segment_terminator,
                component=self._safe(isa, 16, ":"),
                repetition=self._safe(isa, 11, "^"),
            ),
            validation_status=status,
            warnings=warnings,
            errors=errors,
            header_segments=header_segments,
            line_loops=line_loops,
            segments_grouped=True,
        )

    def _normalize(self, raw_edi: str) -> str:
        return "".join(line.strip() for line in raw_edi.strip().splitlines())

    def _detect_segment_terminator(self, edi: str, element_separator: str) -> str:
        gs_index = edi.find(f"GS{element_separator}")
        if gs_index > 0:
            return edi[gs_index - 1]
        return "~"

    def _group_segments(self, segments: list[Segment], warnings: list[str]) -> tuple[list[Segment], list[dict]]:
        header: list[Segment] = []
        line_loops: list[dict] = []
        current_line: dict | None = None
        line_child_tags = {"ACK", "DTM", "REF", "PID"}

        for segment in segments:
            if segment.tag == "PO1":
                current_line = {"po1": segment, "ack": [], "dtm": [], "ref": [], "pid": []}
                line_loops.append(current_line)
                continue
            if current_line and segment.tag in line_child_tags:
                current_line[segment.tag.lower()].append(segment)
                continue
            header.append(segment)

        for index, line in enumerate(line_loops, start=1):
            if len(line["ack"]) > 1:
                warnings.append(f"Line {index} contains multiple ACK segments.")
            if not line["ack"]:
                warnings.append(f"Line {index} does not contain an ACK segment.")

        return header, line_loops

    def _supplier_id(self, segments: list[Segment]) -> str | None:
        for segment in segments:
            if segment.tag == "N1" and self._safe(segment, 1) == "SU":
                return self._safe(segment, 4)
        return None

    def _validate_control_numbers(
        self,
        st: Segment | None,
        se: Segment | None,
        gs: Segment | None,
        ge: Segment | None,
        isa: Segment | None,
        iea: Segment | None,
        errors: list[str],
    ) -> None:
        if st and se and self._safe(st, 2) != self._safe(se, 2):
            errors.append("ST/SE control numbers do not match.")
        if gs and ge and self._safe(gs, 6) != self._safe(ge, 2):
            errors.append("GS/GE control numbers do not match.")
        if isa and iea and self._safe(isa, 13) != self._safe(iea, 2):
            errors.append("ISA/IEA control numbers do not match.")

    def _status(self, errors: list[str], warnings: list[str]) -> ValidationStatus:
        if errors:
            return ValidationStatus.REJECTED
        if warnings:
            return ValidationStatus.VALID_WITH_WARNINGS
        return ValidationStatus.VALID

    def _rejected(
        self,
        source_control_number: str,
        transaction_type: str,
        edi_version: str,
        errors: list[str],
    ) -> EDIParseResult:
        return EDIParseResult(
            source_control_number=source_control_number,
            transaction_type=transaction_type,
            edi_version=edi_version,
            delimiters=EDIDelimiters(element="*", segment="~"),
            validation_status=ValidationStatus.REJECTED,
            errors=errors,
        )

    def _first(self, segments: list[Segment], tag: str) -> Segment | None:
        return next((segment for segment in segments if segment.tag == tag), None)

    def _safe(self, segment: Segment | None, index: int, default=None):
        if segment is None or index >= len(segment.elements):
            return default
        value = segment.elements[index]
        return value if value != "" else default
