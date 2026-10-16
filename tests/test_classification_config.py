import pytest

from classification.config import ClassificationConfig


def test_default_thresholds():
    config = ClassificationConfig()

    assert config.sensitive_threshold == 0.80
    assert config.review_threshold == 0.60


def test_custom_thresholds():
    config = ClassificationConfig(
        sensitive_threshold=0.90,
        review_threshold=0.70,
    )

    assert config.sensitive_threshold == 0.90
    assert config.review_threshold == 0.70


def test_rejects_threshold_above_one():
    with pytest.raises(ValueError):
        ClassificationConfig(sensitive_threshold=1.1)


def test_rejects_negative_threshold():
    with pytest.raises(ValueError):
        ClassificationConfig(review_threshold=-0.1)


def test_review_threshold_cannot_exceed_sensitive_threshold():
    with pytest.raises(ValueError):
        ClassificationConfig(
            sensitive_threshold=0.60,
            review_threshold=0.80,
        )


def test_configuration_is_immutable():
    config = ClassificationConfig()

    with pytest.raises(AttributeError):
        config.review_threshold = 0.50
