
from classification.ner_detector import detect_named_entities


def test_detects_person_and_location_without_returning_text():
    result = detect_named_entities(
        ["Contact John Smith in London."]
    )

    assert result["available"] is True
    assert "PERSON" in result["entity_types"]
    assert result["entity_count"] >= 1
    assert "John Smith" not in str(result)
    assert "London" not in str(result)


def test_empty_input_returns_no_entities():
    result = detect_named_entities([])

    assert result["entity_types"] == []
    assert result["entity_count"] == 0


def test_none_input_returns_no_entities():
    result = detect_named_entities(None)

    assert result["entity_types"] == []
    assert result["entity_count"] == 0


def test_detector_does_not_return_entity_text():
    result = detect_named_entities(
        ["Jane Doe called from Paris."]
    )

    assert "Jane Doe" not in str(result)
    assert "Paris" not in str(result)
    assert set(result) == {
        "available",
        "entity_types",
        "entity_count",
    }
