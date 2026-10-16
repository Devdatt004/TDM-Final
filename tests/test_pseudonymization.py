"""Step 10: HMAC pseudonymization service."""
import base64

import pytest

from privacy.pseudonymization import (
    Pseudonymizer, PseudonymizationError, canonicalize, is_token, load_keyring, parse_token,
)

KEY_A = base64.b64encode(b"A" * 32).decode()
KEY_B = base64.b64encode(b"B" * 32).decode()


def _p(keys=f"k1:{KEY_A}", active=None):
    env = {"TDM_PSEUDONYM_KEYS": keys, "TDM_AUTH_MODE": "production"}
    if active:
        env["TDM_PSEUDONYM_ACTIVE_KEY_ID"] = active
    return Pseudonymizer(load_keyring(env))


def test_same_key_namespace_and_value_is_stable():
    p = _p()
    assert p.pseudonymize("123-45-6789", "id.ssn") == p.pseudonymize("123-45-6789", "id.ssn")
    assert p.pseudonymize("123-45-6789", "id.ssn") == _p().pseudonymize("123-45-6789", "id.ssn")


def test_namespace_and_key_separate_tokens():
    p = _p()
    assert p.pseudonymize("1001", "key.patients.patient_id") != p.pseudonymize("1001", "key.accounts.account_id")
    assert _p().pseudonymize("1001", "id.mrn") != _p(f"k1:{KEY_B}").pseudonymize("1001", "id.mrn")


def test_token_is_well_formed_and_never_contains_raw_value():
    token = _p().pseudonymize("alice@example.com", "id.email")
    assert is_token(token)
    assert parse_token(token)[0] == "k1"
    assert "alice" not in token and "example" not in token


@pytest.mark.parametrize("a,b", [
    ("  A   b ", "A b"),
    (42, "42"),
    (42.0, 42),
    ("１２", "12"),          # full-width digits NFKC-normalise to ASCII
])
def test_canonical_equivalents_share_a_token(a, b):
    p = _p()
    assert p.pseudonymize(a, "id.x") == p.pseudonymize(b, "id.x")


@pytest.mark.parametrize("a,b", [
    ("00123", "123"),                # leading zeros are significant
    ("abc", "ABC"),                  # case is preserved
    (("ab", "c"), ("a", "bc")),      # composite parts are length-prefixed
])
def test_distinct_identifiers_do_not_collide(a, b):
    p = _p()
    assert p.pseudonymize(a, "id.x") != p.pseudonymize(b, "id.x")


@pytest.mark.parametrize("value", [None, "", "   ", ("a", None)])
def test_nulls_stay_null(value):
    assert _p().pseudonymize(value, "id.x") is None


@pytest.mark.parametrize("value", [True, float("nan"), {"a": 1}, [] ])
def test_ambiguous_values_are_rejected(value):
    with pytest.raises(PseudonymizationError):
        canonicalize(value)


@pytest.mark.parametrize("namespace", ["", "Upper", "1abc", "has space", "x" * 65, None])
def test_invalid_namespace_rejected(namespace):
    with pytest.raises(PseudonymizationError):
        _p().pseudonymize("v", namespace)


def test_short_or_malformed_keys_rejected():
    with pytest.raises(PseudonymizationError):
        _p(f"k1:{base64.b64encode(b'short').decode()}")
    with pytest.raises(PseudonymizationError):
        _p("no-separator")
    with pytest.raises(PseudonymizationError):
        _p(f"k1:{KEY_A}", active="missing")


def test_missing_key_fails_outside_development():
    with pytest.raises(PseudonymizationError):
        load_keyring({"TDM_AUTH_MODE": "production"})
    dev = Pseudonymizer(load_keyring({"TDM_AUTH_MODE": "development"}))
    assert dev.ephemeral and is_token(dev.pseudonymize("x", "id.x"))


def test_rotation_keeps_old_tokens_verifiable():
    old = _p(f"k1:{KEY_A}")
    old_token = old.pseudonymize("ACC-1", "id.account_number")
    rotated = _p(f"k1:{KEY_A},k2:{KEY_B}", active="k2")
    new_token = rotated.pseudonymize("ACC-1", "id.account_number")

    assert new_token != old_token and parse_token(new_token)[0] == "k2"
    assert rotated.matches(old_token, "ACC-1", "id.account_number")
    assert rotated.matches(new_token, "ACC-1", "id.account_number")
    assert not rotated.matches(new_token, "ACC-2", "id.account_number")
    assert rotated.rotation_pairs("ACC-1", "id.account_number") == {"k1": old_token, "k2": new_token}


def test_key_material_is_not_exposed_by_repr():
    p = _p()
    assert KEY_A not in repr(p) and "AAAA" not in repr(p)
