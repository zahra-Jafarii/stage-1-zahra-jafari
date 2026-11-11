"""Ready-made row rules for contracts (cross-column checks)."""
from datetime import datetime

from .parsing import parse_timestamp


def window_rule(column: str, start: datetime, end: datetime, code: str):
    # start is inclusive, end is exclusive; unparsable dates are caught by the column check
    def rule(record: dict) -> list:
        value = parse_timestamp(record.get(column))
        if value is None or start <= value < end:
            return []
        return [code]
    return rule


def not_before_rule(first: str, second: str, code: str):
    # `second` must not be earlier than `first`; empty values are ignored
    def rule(record: dict) -> list:
        first_value = parse_timestamp(record.get(first))
        second_value = parse_timestamp(record.get(second))
        if first_value and second_value and second_value < first_value:
            return [code]
        return []
    return rule
