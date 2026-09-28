"""RFC 8785 ordering and the integer-only Passport JSON profile."""

from __future__ import annotations

import pytest

from backend.app.passport.jcs import canonicalize, parse_canonical


def test_utf16_property_order_matches_rfc_8785_vector() -> None:
    source = {
        "€": "Euro Sign", "\r": "Carriage Return", "דּ": "Hebrew Letter",
        "1": "One", "😀": "Emoji", "\x80": "Control", "ö": "Latin",
    }
    encoded = canonicalize(source)
    assert list(parse_canonical(encoded)) == ["\r", "1", "\x80", "ö", "€", "😀", "דּ"]


def test_canonical_string_and_integer_encoding() -> None:
    encoded = canonicalize({"z": [None, True, False, -1, 0], "a": "€\n/"})
    assert encoded == b'{"a":"\xe2\x82\xac\\n/","z":[null,true,false,-1,0]}'
    assert parse_canonical(encoded) == {"a": "€\n/", "z": [None, True, False, -1, 0]}


@pytest.mark.parametrize("raw", [
    b'{"b":1,"a":2}', b'{"a":1,"a":2}', b'\xef\xbb\xbf{"a":1}',
    b'{"a":1.0}', b'{"a":9007199254740992}', b'{"a":NaN}',
    b'{"a":"\\ud800"}', b'{"a":1}\n',
])
def test_noncanonical_or_out_of_profile_json_is_rejected(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_canonical(raw)


def test_float_and_unpaired_surrogate_are_rejected_on_export() -> None:
    with pytest.raises(ValueError):
        canonicalize({"amount": 1.0})
    with pytest.raises(ValueError):
        canonicalize({"key": "\ud800"})
