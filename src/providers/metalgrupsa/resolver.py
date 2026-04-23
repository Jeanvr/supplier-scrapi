from __future__ import annotations

from src.providers.simple_catalog import make_resolver


resolve_reference = make_resolver("metalgrupsa", extra_stopwords={"MTG", "METALGRUP"})
