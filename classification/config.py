"""Configuration for sensitivity classification and review routing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassificationConfig:
    """Thresholds for interpreting rule-based classification scores."""

    sensitive_threshold: float = 0.80
    review_threshold: float = 0.60

    def __post_init__(self) -> None:
        if not 0.0 <= self.sensitive_threshold <= 1.0:
            raise ValueError("sensitive_threshold must be between 0 and 1")

        if not 0.0 <= self.review_threshold <= 1.0:
            raise ValueError("review_threshold must be between 0 and 1")

        if self.review_threshold > self.sensitive_threshold:
            raise ValueError(
                "review_threshold must not exceed sensitive_threshold"
            )
