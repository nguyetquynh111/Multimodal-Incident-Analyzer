"""Tests for the LLM summarizer (rules.md section 11: test_llm_summarizer.py).

Covers tickets T-022/T-023/T-024. Every test injects a fake ``llm_call`` (or
disables the LLM), so NO test ever makes a real network call or needs an API
key.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from llm_summarizer import fallback, schemas
from llm_summarizer.summarizer import summarize_incident


SAMPLE_ROW = {
    "source": "pdf",
    "source_type": "PDF",
    "event": "Theft / Robbery",
    "location": "Main Street",
    "time": "June 20, 2026",
    "severity": "High",
    "confidence": 0.8,
    "raw_text": "A robbery occurred near Main Street on June 20, 2026.",
}

# Exactly the shape the PDF processor emits when nothing is extractable.
ALL_UNKNOWN_ROW = {
    "source": "Unknown",
    "source_type": "PDF",
    "event": "Unknown",
    "location": "Unknown",
    "time": "Unknown",
    "severity": "Low",
    "confidence": 0.0,
    "raw_text": "Unknown",
}

LLM_CONFIGURED_ENV = {"OPENROUTER_API_KEY": "test-key-not-real"}


def _ok_response(content: str) -> dict:
    """An OpenRouter/OpenAI-style chat-completion response."""

    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _assert_valid_contract(test: unittest.TestCase, result: dict) -> None:
    """Every result must carry the required keys, types, and a legal method."""

    test.assertEqual(set(schemas.REQUIRED_OUTPUT_KEYS), set(result))
    test.assertIsInstance(result["incident_summary"], str)
    test.assertTrue(result["incident_summary"].strip())
    test.assertIsInstance(result["summary_method"], str)
    test.assertIsInstance(result["summary_model"], str)
    test.assertIn(result["summary_method"], schemas.ALLOWED_SUMMARY_METHODS)


class FallbackTests(unittest.TestCase):
    def test_fallback_handles_all_unknown_without_crashing(self) -> None:
        result = fallback.summarize_fallback(ALL_UNKNOWN_ROW)

        _assert_valid_contract(self, result)
        self.assertEqual(result["summary_method"], schemas.SUMMARY_METHOD_RULE_BASED)
        self.assertEqual(result["summary_model"], schemas.RULE_BASED_MODEL_LABEL)
        # No invented detail leaks in from an all-Unknown row.
        self.assertNotIn("None", result["incident_summary"])

    def test_fallback_uses_known_fields(self) -> None:
        result = fallback.summarize_fallback(SAMPLE_ROW)

        summary = result["incident_summary"]
        self.assertIn("Theft / Robbery", summary)
        self.assertIn("Main Street", summary)
        self.assertIn("High-severity", summary)


class SummarizeIncidentTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_missing_key_skips_llm_call_entirely(self) -> None:
        def boom(_request: dict) -> dict:
            raise AssertionError("llm_call must not run without an API key")

        result = summarize_incident(SAMPLE_ROW, llm_call=boom)

        _assert_valid_contract(self, result)
        self.assertEqual(result["summary_method"], schemas.SUMMARY_METHOD_DISABLED)
        self.assertEqual(result["summary_model"], schemas.DISABLED_MODEL_LABEL)

    @mock.patch.dict(os.environ, LLM_CONFIGURED_ENV, clear=True)
    def test_enabled_with_valid_llm_output(self) -> None:
        text = "A High-severity Theft / Robbery incident was reported on Main Street."

        def fake_ok(request: dict) -> dict:
            self.assertIn("messages", request)
            return _ok_response(text)

        result = summarize_incident(SAMPLE_ROW, llm_call=fake_ok)

        _assert_valid_contract(self, result)
        self.assertEqual(result["summary_method"], schemas.SUMMARY_METHOD_LLM)
        self.assertEqual(result["incident_summary"], text)
        self.assertNotIn(result["summary_model"], ("", schemas.UNKNOWN))

    @mock.patch.dict(os.environ, LLM_CONFIGURED_ENV, clear=True)
    def test_llm_exception_falls_back_to_error(self) -> None:
        def fake_raise(_request: dict) -> dict:
            raise RuntimeError("simulated network/timeout failure")

        result = summarize_incident(SAMPLE_ROW, llm_call=fake_raise)

        _assert_valid_contract(self, result)
        self.assertEqual(result["summary_method"], schemas.SUMMARY_METHOD_ERROR)
        self.assertEqual(result["summary_model"], schemas.ERROR_MODEL_LABEL)
        # Falls back to the deterministic summary, so real fields still appear.
        self.assertIn("Theft / Robbery", result["incident_summary"])

    @mock.patch.dict(os.environ, LLM_CONFIGURED_ENV, clear=True)
    def test_llm_overlong_output_is_rejected(self) -> None:
        def fake_long(_request: dict) -> dict:
            return _ok_response(" ".join(["word"] * 250))  # ~250 words

        result = summarize_incident(SAMPLE_ROW, llm_call=fake_long)

        _assert_valid_contract(self, result)
        self.assertEqual(result["summary_method"], schemas.SUMMARY_METHOD_ERROR)

    @mock.patch.dict(os.environ, LLM_CONFIGURED_ENV, clear=True)
    def test_llm_empty_output_is_rejected(self) -> None:
        def fake_empty(_request: dict) -> dict:
            return _ok_response("   ")

        result = summarize_incident(SAMPLE_ROW, llm_call=fake_empty)

        _assert_valid_contract(self, result)
        self.assertEqual(result["summary_method"], schemas.SUMMARY_METHOD_ERROR)


if __name__ == "__main__":
    unittest.main()
