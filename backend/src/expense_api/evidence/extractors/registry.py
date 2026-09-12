"""Adapter selection.

The default is rule-based, and that is a deliberate default rather than a placeholder: it needs
no credentials, behaves identically every run, and is the path the test suite covers.
"""

from __future__ import annotations

import logging

from expense_api.config.settings import settings
from expense_api.evidence.extractors.base import Extractor
from expense_api.evidence.extractors.rule_based import RuleBasedExtractor

logger = logging.getLogger(__name__)


def get_extractor(name: str | None = None) -> Extractor:
    choice = name or settings.extractor

    if choice == "llm":
        from expense_api.evidence.extractors.llm import LlmExtractor

        return LlmExtractor()

    return RuleBasedExtractor()
