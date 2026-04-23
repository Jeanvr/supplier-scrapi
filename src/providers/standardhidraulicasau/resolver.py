from __future__ import annotations

from src.providers.simple_catalog import make_resolver


resolve_reference = make_resolver(
    "standardhidraulicasau",
    extra_stopwords={"STANDARD", "HIDRAULICA", "SAU", "STH"},
)
