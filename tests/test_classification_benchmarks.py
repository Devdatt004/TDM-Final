
"""Synthetic benchmark tests for classification accuracy and coverage."""

import pytest

from classification.sensitivity_classifier import classify_sensitivity


# Synthetic fixtures only. Unknown means no sensitive signal was detected;
# it does not establish that real-world data is safe.
BENCHMARK_CASES = [
    ("email_address", ["alex@example.com"], "sensitive", "EMAIL"),
    ("phone_number", ["212-555-0184"], "sensitive", "PHONE"),
    ("social_security_number", ["synthetic-value"], "sensitive", "SSN"),
    ("patient_name", ["Alex Morgan"], "sensitive", "NAME"),
    ("field_unknown_01", [None, None], "unknown", None),
    ("field_unknown_02", ["ordinary-value-123"], "unknown", None),
]


@pytest.mark.parametrize(
    ("column_name", "sample_values", "expected_sensitivity", "expected_type"),
    BENCHMARK_CASES,
)
def test_synthetic_classification_benchmarks(
    column_name,
    sample_values,
    expected_sensitivity,
    expected_type,
):
    result = classify_sensitivity(
        column_name=column_name,
        sample_values=sample_values,
    )

    assert result["sensitivity"] == expected_sensitivity

    if expected_type is not None:
        assert expected_type in result["detected_types"]


def test_benchmark_accuracy_and_coverage():
    """Report basic accuracy and the proportion classified as sensitive/unknown."""
    results = [
        classify_sensitivity(column_name, sample_values)
        for column_name, sample_values, _, _ in BENCHMARK_CASES
    ]

    expected = [
        expected_sensitivity
        for _, _, expected_sensitivity, _ in BENCHMARK_CASES
    ]

    correct = sum(
        result["sensitivity"] == expected_label
        for result, expected_label in zip(results, expected)
    )
    accuracy = correct / len(BENCHMARK_CASES)

    # Coverage here means the fraction receiving a non-unknown result.
    # It is not the same as accuracy or safe-data coverage.
    classified = sum(
        result["sensitivity"] != "unknown"
        for result in results
    )
    coverage = classified / len(BENCHMARK_CASES)

    print(f"Benchmark accuracy: {accuracy:.1%}")
    print(f"Non-unknown classification coverage: {coverage:.1%}")

    assert accuracy >= 0.80
