"""Bounded parsing and identity semantics for untrusted evidence."""

from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from tests.code.verification_fixtures import component


@pytest.mark.parametrize(
    "document",
    [
        b'{"status":0,"status":1}',
        b'{"nested":{"x":1,"x":2}}',
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b"{} {}",
        b"{}trailing",
        b'"\xff"',
        b"\xef\xbb\xbf{}",
        b'"\\ud800"',
        b'"\\udfff"',
        b"[" * 33 + b"0" + b"]" * 33,
        b"[" + b"0," * 4096 + b"0]",
        b'"' + b"x" * 87385 + b'"',
        b"1" * 129,
        b"1e309",
        b"1e-309",
        b"1e" + b"9" * 10000,
    ],
)
def test_unsafe_or_ambiguous_json_is_rejected(document: bytes) -> None:
    api = component("evolution.code.strict_json")
    with pytest.raises(ValueError):
        api.loads(document)


def test_exact_decimals_do_not_use_binary_float_or_decimal_context() -> None:
    api = component("evolution.code.strict_json")
    with localcontext() as ctx:
        ctx.prec = 3
        parsed = api.loads(b"[9007199254740993,1.000000000000000001,1e0,-0.0]")
        assert type(parsed[0]) is int
        assert all(type(value) is Decimal for value in parsed[1:])
        assert parsed == [
            9007199254740993,
            Decimal("1.000000000000000001"),
            Decimal("1"),
            Decimal("-0.0"),
        ]
        assert api.equivalent(parsed[1], Decimal("1")) is False


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (True, 1, False),
        (False, 0, False),
        (1, Decimal("1"), False),
        (Decimal("1.0"), Decimal("1e0"), True),
        (Decimal("-0.0"), Decimal("0"), True),
        ({"x": True}, {"x": 1}, False),
        ([1, 2], [2, 1], False),
        ({"b": 2, "a": 1}, {"a": 1, "b": 2}, True),
        ("é", "e\u0301", False),
    ],
)
def test_comparison_is_recursive_and_type_sensitive(
    left: object, right: object, expected: bool
) -> None:
    assert component("evolution.code.strict_json").equivalent(left, right) is expected


def test_canonical_encoding_has_an_independent_literal_vector() -> None:
    api = component("evolution.code.strict_json")
    assert api.canonical_bytes({"b": Decimal("1.00"), "a": [True, 1, None]}) == (
        b'["object",[["a",["array",[["bool",true],["int","1"],["null"]]]],'
        b'["b",["decimal","1","0"]]]]'
    )


def test_canonical_decimal_encoding_ignores_ambient_precision() -> None:
    api = component("evolution.code.strict_json")
    with localcontext() as ctx:
        ctx.prec = 2
        assert api.canonical_bytes(Decimal("123456789.1200")) == (b'["decimal","12345678912","-2"]')


def test_domain_separation_and_object_order_are_stable() -> None:
    api = component("evolution.code.strict_json")
    assert api.identity("snapshot", {"a": 1, "b": 2}) == api.identity("snapshot", {"b": 2, "a": 1})
    assert (
        len(
            {
                api.identity(domain, {"a": 1})
                for domain in (
                    "snapshot",
                    "specification",
                    "runtime",
                    "policy",
                    "campaign",
                    "organism",
                    "seed",
                    "journal-record",
                )
            }
        )
        == 8
    )


def test_root_depth_and_maximum_decoded_string_are_inclusive() -> None:
    api = component("evolution.code.strict_json")
    assert api.loads(b"[" * 32 + b"0" + b"]" * 32)
    assert api.loads(b'"' + b"x" * 87384 + b'"') == "x" * 87384


def test_total_value_bound_includes_object_keys() -> None:
    api = component("evolution.code.strict_json")
    row = "{" + ",".join('"k%d":0' % index for index in range(3000)) + "}"
    with pytest.raises(ValueError):
        api.loads(("[" + ",".join([row] * 3) + "]").encode())


def test_identity_matches_domain_separated_sha256_vector() -> None:
    api = component("evolution.code.strict_json")
    assert (
        api.identity("specification", {"a": 1})
        == "9c15e163d3c4fc982265d1bdcbbf363bef0790d4e1453ed0bd37cd21240fffc3"
    )


@pytest.mark.parametrize("amount", ["0", "-0", "2", "9007199254740993"])
def test_integral_decimal_roundtrip_preserves_type_and_journal_identity(amount: str) -> None:
    api = component("evolution.code.strict_json")
    observation = {"amount_usd": Decimal(amount)}
    restored = api.loads(api.dumps(observation))
    assert type(restored["amount_usd"]) is Decimal
    assert api.identity("journal-record", restored) == api.identity("journal-record", observation)
