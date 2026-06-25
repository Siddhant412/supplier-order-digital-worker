from pathlib import Path

from app.domain.models import ValidationStatus
from app.services.edi_interpreter import EDIInterpreter
from app.services.edi_parser import EDIParser
from app.services.profiles import TradingPartnerProfileRepository


ROOT = Path(__file__).resolve().parents[2]


def load_sample(name: str) -> str:
    return (ROOT / "sample-data" / "edi" / name).read_text()


def test_parser_detects_standard_delimiters_and_groups_lines():
    result = EDIParser().parse(load_sample("exact-match.edi"))

    assert result.validation_status == ValidationStatus.VALID
    assert result.delimiters.element == "*"
    assert result.delimiters.segment == "~"
    assert result.transaction_type == "855"
    assert result.purchase_order_number == "PO-1042"
    assert len(result.line_loops) == 2


def test_parser_detects_alternate_delimiters():
    result = EDIParser().parse(load_sample("alternate-delimiters.edi"))

    assert result.validation_status == ValidationStatus.VALID
    assert result.delimiters.element == "|"
    assert result.delimiters.segment == "'"
    assert result.source_control_number == "0004"


def test_interpreter_routes_unknown_qualifier_to_manual_review():
    parser = EDIParser()
    interpreter = EDIInterpreter(TradingPartnerProfileRepository())

    confirmation = interpreter.interpret(parser.parse(load_sample("unsupported-qualifier.edi")))

    assert confirmation.validation_status == ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "Unsupported or ambiguous date qualifier: 999." in confirmation.errors
