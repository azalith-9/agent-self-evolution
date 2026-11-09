"""Bounded, exact JSON and domain-separated content identities."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

MAX_DOCUMENT = 4 * 1024 * 1024


def _number(token: str) -> int | Decimal:
    if len(token) > 128:
        raise ValueError("numeric token too long")
    exponent = re.search(r"[eE]([+-]?\d+)$", token)
    if exponent and abs(int(exponent[1])) > 308:
        raise ValueError("decimal exponent out of range")
    return Decimal(token) if any(c in token for c in ".eE") else int(token)


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _validate(value: object, depth: int = 0, count: list[int] | None = None) -> None:
    count = [0] if count is None else count
    count[0] += 1
    if count[0] > 16384:
        raise ValueError("too many JSON values")
    if type(value) in (list, dict):
        if depth >= 32 or len(value) > 4096:
            raise ValueError("JSON collection bound exceeded")
        for item in value:
            _validate(item, depth + 1, count)
            if type(value) is dict:
                if type(item) is not str:
                    raise ValueError("JSON keys must be strings")
                _validate(value[item], depth + 1, count)
    elif type(value) is str:
        if len(value.encode("utf-8")) > 87384:
            raise ValueError("JSON string too long")
    elif type(value) is Decimal:
        if not value.is_finite() or len(str(value)) > 128 or abs(value.as_tuple().exponent) > 436:
            raise ValueError("invalid JSON decimal")
    elif type(value) is int:
        if len(str(value)) > 128:
            raise ValueError("JSON integer too long")
    elif value is not None and type(value) is not bool:
        raise ValueError("unsupported JSON type")


def loads(document: bytes) -> object:
    """Parse one strict UTF-8 document without binary floating point."""
    if type(document) is not bytes or len(document) > MAX_DOCUMENT:
        raise ValueError("JSON document bound exceeded")
    try:
        source = document.decode("utf-8")
        # Bound lexical nesting before invoking the recursive standard parser.
        depth, quoted, escaped = 0, False, False
        for char in source:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > 32:
                    raise ValueError("JSON nesting too deep")
            elif char in "]}":
                depth -= 1
        def invalid(token: str) -> None:
            raise ValueError("nonfinite JSON number")
        result = json.loads(source, object_pairs_hook=_object, parse_int=_number,
                            parse_float=_number, parse_constant=invalid)
        _validate(result)
        return result
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc


def equivalent(left: object, right: object) -> bool:
    """Compare JSON values recursively, preserving numeric type distinctions."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(equivalent(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    return left == right


def _tag(value: object) -> list:
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is str:
        return ["str", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is Decimal:
        sign, digits, exponent = value.as_tuple()
        coefficient = ''.join(map(str, digits)).lstrip('0')
        if not coefficient:
            return ["decimal", "0", "0"]
        while coefficient.endswith('0'):
            coefficient, exponent = coefficient[:-1], exponent + 1
        return ["decimal", ('-' if sign else '') + coefficient, str(exponent)]
    if type(value) is list:
        return ["array", [_tag(item) for item in value]]
    return ["object", [[key, _tag(value[key])] for key in sorted(value)]]


def canonical_bytes(value: object) -> bytes:
    _validate(value)
    return json.dumps(_tag(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def identity(domain: str, value: object) -> str:
    if not re.fullmatch(r"[a-z][a-z-]*", domain):
        raise ValueError("invalid identity domain")
    return hashlib.sha256(f"agent-self-evolution:{domain}:1\0".encode() + canonical_bytes(value)).hexdigest()


def dumps(value: object) -> bytes:
    """Encode exact decimals as JSON numbers, without using a float conversion."""
    _validate(value)
    if type(value) is Decimal:
        token = str(value)
        if not any(c in token for c in ".eE"):
            token += ".0"
        return token.encode("ascii")
    if type(value) is list:
        return b'[' + b','.join(dumps(item) for item in value) + b']'
    if type(value) is dict:
        return b'{' + b','.join(dumps(k) + b':' + dumps(v) for k, v in value.items()) + b'}'
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
