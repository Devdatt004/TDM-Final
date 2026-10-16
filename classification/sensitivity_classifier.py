
"""Sensitivity classification, separate from structural pattern detection."""

import re
from typing import Any, Dict, Optional

from classification.checksum_validators import (
    passes_luhn,
    passes_npi_checksum,
)
from classification.config import ClassificationConfig
from classification.dictionary_detector import find_dictionary_matches
from classification.ner_detector import detect_named_entities


SENSITIVE_FIELD_RULES = {
    "SSN": (r"\b(ssn|social_security|social_security_number)\b", 0.98),
    "AADHAAR_NUMBER": (
        r"\b(aadhaar|aadhar|uid_number|aadhaar_number|aadhar_number)\b",
        0.98,
    ),
    "PAN_NUMBER": (r"\b(pan|pan_number|tax_id|taxpayer_id)\b", 0.95),
    "MRN": (r"\b(mrn|medical_record_number|patient_id)\b", 0.95),
    "INSURANCE_ID": (r"\b(insurance_id|policy_number|member_id)\b", 0.90),
    "CREDIT_CARD": (r"\b(credit_card|card_number|cc_number)\b", 0.98),
    "ACCOUNT_NUMBER": (r"\b(account_number|bank_account)\b", 0.95),
    "PHONE": (
        r"\b(phone|mobile|telephone|contact_number|phone_number)\b",
        0.90,
    ),
    "EMAIL": (r"\b(email|email_address|e_mail)\b", 0.95),
    "DATE_OF_BIRTH": (
        r"\b(dob|date_of_birth|birth_date|birthdate)\b",
        0.98,
    ),
    "NAME": (
        r"\b(first_name|last_name|full_name|patient_name|person_name)\b",
        0.90,
    ),
    "ADDRESS": (
        r"\b(address|street_address|postal_address|home_address)\b",
        0.90,
    ),
}


SENSITIVE_PATTERN_TYPES = {
    "SSN": 0.95,
    "AADHAAR_NUMBER": 0.95,
    "PAN_NUMBER": 0.95,
    "MRN": 0.90,
    "INSURANCE_ID": 0.90,
    "CREDIT_CARD": 0.95,
    "ACCOUNT_NUMBER": 0.85,
    "PHONE": 0.80,
}


VALUE_REGEX_RULES = {
    "EMAIL": (
        r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
        0.90,
    ),
    "SSN": (
        r"(?<!\d)(?:\d{3}-\d{2}-\d{4})(?!\d)",
        0.85,
    ),
    "PHONE": (
        r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?"
        r"(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)",
        0.75,
    ),
    "NPI": (
        r"(?<!\d)\d{10}(?!\d)",
        0.65,
    ),
    "CREDIT_CARD_CANDIDATE": (
        r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
        0.65,
    ),
}

VALID_SENSITIVITY_LEVELS = {"sensitive", "unknown"}


def _normalize_column_name(column_name: Optional[str]) -> str:
    """Normalize camelCase, PascalCase, spaces, and common separators."""
    name = str(column_name or "").strip()
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"[\s\-./]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.lower().strip("_")


def _sample_values(sample_values: Any) -> list:
    """Normalize optional sample values into a list."""
    if sample_values is None:
        return []
    if isinstance(sample_values, bytes):
        return [sample_values.decode(errors="replace")]
    if isinstance(sample_values, str):
        return [sample_values]
    try:
        return list(sample_values)
    except TypeError:
        return [sample_values]


def _matches_value_rule(
    value_type: str,
    value_regex: str,
    value: Any,
) -> bool:
    """Check a sample value against a regex and required validators."""
    text_value = str(value).strip()

    if re.search(value_regex, text_value) is None:
        return False

    if value_type == "CREDIT_CARD_CANDIDATE":
        return passes_luhn(text_value)

    if value_type == "NPI":
        return passes_npi_checksum(text_value)

    return True


def classify_sensitivity(
    column_name: str,
    top_pattern: Optional[Dict[str, Any]] = None,
    sample_values: Any = None,
    dictionaries: Optional[Dict[str, Any]] = None,
    config: Optional[ClassificationConfig] = None,
) -> Dict[str, Any]:
    """Classify sensitivity and determine human-review eligibility.

    Confidence is a rule-based evidence score, not a calibrated probability.
    Unknown results must not be interpreted as safe.
    """
    config = config or ClassificationConfig()

    normalized_name = _normalize_column_name(column_name)
    pattern = top_pattern if isinstance(top_pattern, dict) else {}

    pattern_type = pattern.get("pattern_type")
    if isinstance(pattern_type, str):
        pattern_type = pattern_type.strip().upper()

    evidence = []
    confidence = 0.0
    detected_types = set()

    # Signal 1: column-name inference.
    for sensitivity_type, (name_regex, score) in SENSITIVE_FIELD_RULES.items():
        if re.search(name_regex, normalized_name, flags=re.IGNORECASE):
            evidence.append(
                f"column_name_matches_{sensitivity_type.lower()}"
            )
            detected_types.add(sensitivity_type)
            confidence = max(confidence, score)

    # Signal 2: existing structural pattern evidence.
    if pattern_type in SENSITIVE_PATTERN_TYPES:
        pattern_score = SENSITIVE_PATTERN_TYPES[pattern_type]
        percentage = pattern.get("percentage")

        if isinstance(percentage, (int, float)) and not isinstance(
            percentage, bool
        ):
            bounded_percentage = max(
                0.0,
                min(100.0, float(percentage)),
            )
            pattern_score *= bounded_percentage / 100.0

        evidence.append(f"data_pattern_matches_{pattern_type.lower()}")
        detected_types.add(pattern_type)
        confidence = max(confidence, pattern_score)

    # Normalize samples once for regex, dictionary, and NER detection.
    values = _sample_values(sample_values)
    non_null_values = [value for value in values if value is not None]

    # Signal 3: regex detection and checksum validation.
    if non_null_values:
        for value_type, (value_regex, score) in VALUE_REGEX_RULES.items():
            matched_count = sum(
                1
                for value in non_null_values
                if _matches_value_rule(value_type, value_regex, value)
            )

            if matched_count:
                match_percentage = matched_count / len(non_null_values)
                value_score = score * match_percentage

                evidence.append(
                    f"sample_values_match_{value_type.lower()}"
                )
                detected_types.add(value_type)
                confidence = max(confidence, value_score)

    # Signal 4: caller-approved dictionary matches.
    if dictionaries and non_null_values:
        dictionary_matches = find_dictionary_matches(
            non_null_values,
            dictionaries,
        )

        if dictionary_matches:
            dictionary_names = sorted(
                {match["dictionary"] for match in dictionary_matches}
            )
            evidence.extend(
                f"sample_values_match_dictionary_{name.lower()}"
                for name in dictionary_names
            )
            confidence = max(confidence, 0.75)
            detected_types.add("DICTIONARY_MATCH")

    # Signal 5: named entities in free-text samples.
    # Entity text and offsets are never added to classification results.
    if non_null_values:
        text_values = [
            value.decode(errors="replace")
            if isinstance(value, bytes)
            else str(value)
            for value in non_null_values
        ]

        # Avoid running NER on purely numeric or short identifier-like values.
        free_text_values = [
            value
            for value in text_values
            if len(value.strip()) >= 3
            and re.search(r"[A-Za-z]", value)
            and len(value.split()) >= 2
        ]

        if free_text_values:
            ner_result = detect_named_entities(free_text_values)

            if ner_result["available"] and ner_result["entity_count"] > 0:
                entity_types = set(ner_result["entity_types"])

                if "PERSON" in entity_types:
                    evidence.append("free_text_contains_person_entity")
                    detected_types.add("PERSON")
                    confidence = max(confidence, 0.65)

                if entity_types.intersection({"GPE", "LOC", "FAC"}):
                    evidence.append("free_text_contains_location_entity")
                    detected_types.add("LOCATION")
                    confidence = max(confidence, 0.65)

    confidence = round(confidence, 3)
    has_evidence = bool(evidence)

    # Conservative handling: evidence does not automatically prove identity,
    # but detected information remains sensitive until reviewed.
    sensitivity = "sensitive" if has_evidence else "unknown"


    if not has_evidence:
        classification_status = "unknown"
        review_required = False
    elif confidence < config.review_threshold:
        classification_status = "review_required"
        review_required = True
    elif confidence < config.sensitive_threshold:
        classification_status = "review_required"
        review_required = True
    else:
        classification_status = "classified"
        review_required = False


    result = {
        "sensitivity": sensitivity,
        "confidence": confidence,
        "evidence": evidence,
        "pattern_type": pattern_type,
        "detected_types": sorted(detected_types),
        "classification_status": classification_status,
        "review_required": review_required,
    }

    assert result["sensitivity"] in VALID_SENSITIVITY_LEVELS

    return result
