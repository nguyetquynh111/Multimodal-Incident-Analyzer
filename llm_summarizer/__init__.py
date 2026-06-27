"""Separate LLM summarizer package (rules.md section 6).

Public entry point::

    from llm_summarizer.summarizer import summarize_incident, update_image_location

The summarizer only narrates the cleaned integrated fields into a short
``incident_summary``. The image-OCR helper extracts a location only when the
provided OCR text explicitly contains one. This package never generates IDs
and never touches Supabase.
"""

from __future__ import annotations

from .summarizer import summarize_incident, update_image_location

__all__ = ["summarize_incident", "update_image_location"]
