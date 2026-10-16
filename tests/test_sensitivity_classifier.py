from classification.sensitivity_classifier import classify_sensitivity
from classification.config import ClassificationConfig


def test_sensitive_column_name():
    result = classify_sensitivity("patient_name")
    assert result["sensitivity"] == "sensitive"
    assert result["confidence"] == 0.90


def test_structural_pattern_detection():
    result = classify_sensitivity(
        "field_17",
        {"pattern_type": "SSN", "percentage": 100.0},
    )
    assert result["sensitivity"] == "sensitive"
    assert result["confidence"] == 0.95


def test_unknown_field():
    result = classify_sensitivity("field_18")
    assert result["sensitivity"] == "unknown"
    assert result["confidence"] == 0.0


def test_email_sample_detection():
    result = classify_sensitivity(
        "field_17",
        sample_values=["person@example.com", "other@example.org"],
    )
    assert result["sensitivity"] == "sensitive"
    assert "EMAIL" in result["detected_types"]


def test_ssn_sample_detection():
    result = classify_sensitivity(
        "field_18",
        sample_values=["123-45-6789", "987-65-4321"],
    )
    assert result["sensitivity"] == "sensitive"
    assert "SSN" in result["detected_types"]


def test_partial_matches_reduce_confidence():
    result = classify_sensitivity(
        "field_19",
        sample_values=["person@example.com", "not-an-email"],
    )
    assert result["sensitivity"] == "sensitive"
    assert result["confidence"] == 0.45


def test_null_values_do_not_reduce_match_percentage():
    result = classify_sensitivity(
        "field_20",
        sample_values=["person@example.com", None],
    )
    assert result["confidence"] == 0.90
    assert "EMAIL" in result["detected_types"]


def test_valid_luhn_sample_is_detected_as_credit_card_candidate():
    result = classify_sensitivity(
        "field_21",
        sample_values=["4532015112830366"],
    )

    assert result["sensitivity"] == "sensitive"
    assert result["confidence"] == 0.65
    assert "CREDIT_CARD_CANDIDATE" in result["detected_types"]


def test_invalid_luhn_sample_is_not_detected_as_credit_card_candidate():
    result = classify_sensitivity(
        "field_22",
        sample_values=["4532015112830367"],
    )

    assert result["sensitivity"] == "unknown"
    assert result["confidence"] == 0.0
    assert "CREDIT_CARD_CANDIDATE" not in result["detected_types"]


def test_approved_dictionary_match_adds_sensitivity_evidence():
    result = classify_sensitivity(
        "field_23",
        sample_values=["Bengaluru", "UnknownCity"],
        dictionaries={
            "approved_cities": ["Bengaluru", "Mysuru"],
        },
    )

    assert result["sensitivity"] == "sensitive"
    assert result["confidence"] == 0.75
    assert "DICTIONARY_MATCH" in result["detected_types"]
    assert (
        "sample_values_match_dictionary_approved_cities"
        in result["evidence"]
    )


def test_medium_confidence_requires_review():
    result = classify_sensitivity(
        "field_24",
        sample_values=["person@example.com", "not-an-email"],
    )

    assert result["confidence"] == 0.45
    assert result["classification_status"] == "review_required"
    assert result["review_required"] is True


def test_dictionary_evidence_requires_review():
    result = classify_sensitivity(
        "field_25",
        sample_values=["Bengaluru"],
        dictionaries={"approved_cities": ["Bengaluru"]},
    )

    assert result["confidence"] == 0.75
    assert result["classification_status"] == "review_required"
    assert result["review_required"] is True
    assert result["sensitivity"] == "sensitive"


def test_custom_thresholds_control_review_eligibility():
    config = ClassificationConfig(
        sensitive_threshold=0.95,
        review_threshold=0.70,
    )

    result = classify_sensitivity(
        "field_26",
        sample_values=["Bengaluru"],
        dictionaries={"approved_cities": ["Bengaluru"]},
        config=config,
    )

    assert result["classification_status"] == "review_required"
    assert result["review_required"] is True


def test_high_confidence_is_classified_without_review():
    result = classify_sensitivity("patient_name")

    assert result["confidence"] == 0.90
    assert result["classification_status"] == "classified"
    assert result["review_required"] is False


def test_no_evidence_remains_unknown():
    result = classify_sensitivity("field_27")

    assert result["sensitivity"] == "unknown"
    assert result["classification_status"] == "unknown"
    assert result["review_required"] is False
def test_valid_npi_sample_is_detected():
    result = classify_sensitivity(
        "field_28",
        sample_values=["1234567893"],
    )

    assert result["sensitivity"] == "sensitive"
    assert "NPI" in result["detected_types"]
    assert "sample_values_match_npi" in result["evidence"]


def test_invalid_npi_sample_is_not_detected_as_npi():
    result = classify_sensitivity(
        "field_29",
        sample_values=["1234567890"],
    )

    assert "NPI" not in result["detected_types"]
    assert "sample_values_match_npi" not in result["evidence"]