"""RFC 8785 JCS for Sentinel's restricted integer/string JSON schema.

The bundle schema has no floating-point fields. Refusing floats avoids an
incorrect ECMAScript-number implementation while all generated documents are
fully JCS canonical. Integers are restricted to I-JSON's exact range.
"""

from __future__ import annotations

import json
from typing import Any

_MAX_EXACT_INTEGER = (1 << 53) - 1


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object property")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise ValueError(f"Unsupported JCS numeric value: {value[:32]}")


def _string(value: str) -> str:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("Unpaired Unicode surrogate is not valid JCS") from exc
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _render(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int):
        if abs(value) > _MAX_EXACT_INTEGER:
            raise ValueError("Integer exceeds I-JSON exact range")
        return str(value)
    if isinstance(value, float):
        raise ValueError("Passport JCS profile does not allow floating-point numbers")
    if isinstance(value, list):
        return "[" + ",".join(_render(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object properties must be strings")
        keys = sorted(value, key=lambda key: key.encode("utf-16-be", errors="strict"))
        return "{" + ",".join(_string(key) + ":" + _render(value[key]) for key in keys) + "}"
    raise ValueError(f"Unsupported JSON type: {type(value).__name__}")


def canonicalize(value: object) -> bytes:
    """Generate deterministic UTF-8 JCS bytes for the bounded bundle schema."""
    return _render(value).encode("utf-8")


def parse_canonical(raw: bytes) -> object:
    """Decode strict I-JSON and reject any noncanonical representation."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("JCS must not have a UTF-8 BOM")
    try:
        parsed = json.loads(raw.decode("utf-8", errors="strict"),
                            object_pairs_hook=_reject_duplicate_keys,
                            parse_float=_reject_number, parse_constant=_reject_number)
        if canonicalize(parsed) != raw:
            raise ValueError("JSON is not JCS canonical")
        return parsed
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Malformed JCS JSON") from exc
