"""Optional named-entity detection for free-text classification."""

from functools import lru_cache
from typing import Any


# Entity labels that may indicate personal or sensitive information.
SENSITIVE_ENTITY_LABELS = {
    "PERSON",
    "GPE",
    "LOC",
    "FAC",
}


@lru_cache(maxsize=1)
def _load_ner_model():
    """Load spaCy's English model lazily.

    Return None when spaCy or the model is unavailable so that NER
    cannot prevent the rest of the classification engine from working.
    """
    try:
        import spacy

        return spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        return None


def detect_named_entities(values: Any) -> dict:
    """Detect potentially sensitive entity types without returning text.

    The result contains entity labels and counts only, not extracted
    names, locations, or source values.
    """
    if values is None:
        return {
            "available": _load_ner_model() is not None,
            "entity_types": [],
            "entity_count": 0,
        }

    if isinstance(values, (str, bytes)):
        values = [values]
    else:
        try:
            values = list(values)
        except TypeError:
            values = [values]

    model = _load_ner_model()
    if model is None:
        return {
            "available": False,
            "entity_types": [],
            "entity_count": 0,
        }

    entity_counts = {}

    for value in values:
        if value is None:
            continue

        if isinstance(value, bytes):
            text = value.decode(errors="replace")
        else:
            text = str(value)

        if not text.strip():
            continue

        try:
            doc = model(text[:100_000])
        except (ValueError, RuntimeError):
            # A malformed or unsupported sample must not break profiling.
            continue

        for entity in doc.ents:
            if entity.label_ in SENSITIVE_ENTITY_LABELS:
                entity_counts[entity.label_] = (
                    entity_counts.get(entity.label_, 0) + 1
                )

    return {
        "available": True,
        "entity_types": sorted(entity_counts),
        "entity_count": sum(entity_counts.values()),
    }