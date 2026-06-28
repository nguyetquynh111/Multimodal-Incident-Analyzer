"""Input/output schema constants for the LLM summarizer."""

from __future__ import annotations


# Required cleaned incident input fields.
REQUIRED_INPUT_KEYS = (
    "source",
    "source_type",
    "event",
    "location",
    "time",
    "severity",
    "confidence",
)

# Required summary response fields.
REQUIRED_OUTPUT_KEYS = (
    "incident_summary",
    "summary_method",
    "summary_model",
)

# Allowed values for the ``summary_method`` return field.
SUMMARY_METHOD_LLM = "llm"
SUMMARY_METHOD_RULE_BASED = "rule_based"
SUMMARY_METHOD_DISABLED = "disabled"
SUMMARY_METHOD_ERROR = "error"

ALLOWED_SUMMARY_METHODS = (
    SUMMARY_METHOD_LLM,
    SUMMARY_METHOD_RULE_BASED,
    SUMMARY_METHOD_DISABLED,
    SUMMARY_METHOD_ERROR,
)

# Fixed ``summary_model`` labels used when no real model produced the summary.
RULE_BASED_MODEL_LABEL = "rule_based_fallback"
DISABLED_MODEL_LABEL = "disabled"
ERROR_MODEL_LABEL = "error"

# Shared placeholder for missing fields.
UNKNOWN = "Unknown"

# Length guards for accepted model output.
MAX_SUMMARY_WORDS = 80
MAX_SUMMARY_CHARS = 1000


__all__ = [
    "REQUIRED_INPUT_KEYS",
    "REQUIRED_OUTPUT_KEYS",
    "SUMMARY_METHOD_LLM",
    "SUMMARY_METHOD_RULE_BASED",
    "SUMMARY_METHOD_DISABLED",
    "SUMMARY_METHOD_ERROR",
    "ALLOWED_SUMMARY_METHODS",
    "RULE_BASED_MODEL_LABEL",
    "DISABLED_MODEL_LABEL",
    "ERROR_MODEL_LABEL",
    "UNKNOWN",
    "MAX_SUMMARY_WORDS",
    "MAX_SUMMARY_CHARS",
]
