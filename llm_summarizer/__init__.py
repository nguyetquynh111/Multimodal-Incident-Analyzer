"""Separate LLM summarizer package (rules.md section 6).

Public entry point::

    from llm_summarizer.summarizer import summarize_incident

The summarizer only narrates the cleaned integrated fields into a short
``incident_summary``; it never overrides event/location/time/severity, never
generates IDs, and never touches Supabase.
"""

from __future__ import annotations

from .summarizer import summarize_incident

__all__ = ["summarize_incident"]
