from classification.checksum_validators import (
    passes_luhn,
    passes_npi_checksum,
)


def test_valid_luhn_candidate():
    assert passes_luhn("4532015112830366") is True


def test_valid_luhn_candidate_with_separators():
    assert passes_luhn("4532-0151-1283-0366") is True
    assert passes_luhn("4532 0151 1283 0366") is True


def test_invalid_luhn_candidate():
    assert passes_luhn("4532015112830367") is False


def test_rejects_non_digit_characters():
    assert passes_luhn("4532x15112830366") is False


def test_rejects_invalid_lengths():
    assert passes_luhn("1234567890") is False
    assert passes_luhn("123456789012345678901") is False


def test_rejects_non_string_and_empty_values():
    assert passes_luhn(None) is False
    assert passes_luhn(4532015112830366) is False
    assert passes_luhn("") is False
    assert passes_luhn("   ") is False


def test_valid_npi_checksum():
    assert passes_npi_checksum("1234567893") is True


def test_invalid_npi_checksum():
    assert passes_npi_checksum("1234567890") is False


def test_npi_requires_exactly_10_digits():
    assert passes_npi_checksum("123456789") is False
    assert passes_npi_checksum("12345678930") is False


def test_npi_rejects_non_digit_and_non_string_values():
    assert passes_npi_checksum("123456789A") is False
    assert passes_npi_checksum("12345-7893") is False
    assert passes_npi_checksum(None) is False
    assert passes_npi_checksum(1234567893) is False
