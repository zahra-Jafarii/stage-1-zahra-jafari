"""Record validation driven by a contract: returns reason codes, never drops silently."""
from .contract import Column, Contract
from .exceptions import SchemaDriftError
from .parsing import DTYPE_CHECKS, is_missing, to_number


def normalize_choice(value, column: Column) -> str:
    text = str(value).strip()
    return text.upper() if column.case_insensitive else text


def inside_range(value, column: Column) -> bool:
    if column.min_value is None and column.max_value is None:
        return True
    number = to_number(value)
    if number is None:
        return False
    if column.min_value is not None and number < column.min_value:
        return False
    return column.max_value is None or number <= column.max_value


def value_is_valid(value, column: Column) -> bool:
    if not DTYPE_CHECKS[column.dtype](value):
        return False
    if column.allowed is not None and normalize_choice(value, column) not in column.allowed:
        return False
    return inside_range(value, column)


def validate_column(record: dict, column: Column) -> list:
    value = record.get(column.name)
    if is_missing(value):
        if column.nullable or column.fill_value is not None:
            return []
        return [column.missing_reason]
    return [] if value_is_valid(value, column) else [column.invalid_reason]


def validate_record(record: dict, contract: Contract) -> list:
    reasons = []
    for column in contract.source_columns:
        reasons.extend(validate_column(record, column))
    for rule in contract.row_rules:
        reasons.extend(rule(record))
    return sorted(set(reasons))  # fixed order keeps the quarantine file deterministic


def split_valid(batch: list, contract: Contract) -> tuple:
    valid, rejected = [], []
    for record in batch:
        reasons = validate_record(record, contract)
        if reasons:
            rejected.append((record, reasons))
        else:
            valid.append(record)
    return valid, rejected


def check_batch_types(batch: list, contract: Contract) -> None:
    # a text source never sends numbers; any other type means the schema changed
    if not contract.text_only_source:
        return
    for record in batch:
        for column in contract.required_columns:
            value = record.get(column)
            if value is not None and not isinstance(value, str):
                raise SchemaDriftError(f"column {column} changed type: {type(value).__name__}")


def check_required_columns(columns_seen: set, contract: Contract) -> None:
    missing = [column for column in contract.required_columns if column not in columns_seen]
    if missing:
        raise SchemaDriftError(f"required columns missing from source: {missing}")
