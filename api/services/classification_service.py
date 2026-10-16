# api/services/classification_service.py

from typing import Any, Dict, Optional

from classification.config import ClassificationConfig
from classification.sensitivity_classifier import classify_sensitivity


KNOWN_SPECIFIC_TYPES = {
    "SSN", "DATE", "PHONE", "ZIP_CODE",
    "MRN", "INSURANCE_ID",
    "CREDIT_CARD", "ACCOUNT_NUMBER", "IFSC_CODE", "PAN_NUMBER",
    "AADHAAR_NUMBER",
}
HIGH_CONFIDENCE_THRESHOLD = 90.0


def classify_column(top_pattern: dict) -> str:
    """Legacy verdict retained for existing profiling consumers."""
    if top_pattern is None:
        return "needs_review"

    is_specific_type = top_pattern["pattern_type"] in KNOWN_SPECIFIC_TYPES
    is_dominant_enough = (
        top_pattern["percentage"] >= HIGH_CONFIDENCE_THRESHOLD
    )
    return "high_confidence" if (
        is_specific_type and is_dominant_enough
    ) else "needs_review"


def classify_column_sensitivity(
    column_name: str,
    top_pattern: Optional[Dict[str, Any]] = None,
    sample_values: Any = None,
    dictionaries: Optional[Dict[str, Any]] = None,
    config: Optional[ClassificationConfig] = None,
) -> Dict[str, Any]:
    """Classify sensitivity independently of the legacy pattern verdict."""
    return classify_sensitivity(
        column_name=column_name,
        top_pattern=top_pattern,
        sample_values=sample_values,
        dictionaries=dictionaries,
        config=config,
    )