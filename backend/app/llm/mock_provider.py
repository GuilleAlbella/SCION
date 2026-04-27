from __future__ import annotations

"""Deterministic in-process mock implementation of :class:`LLMProvider`.

This provider allows the rest of the system (including TAISA and reasoning)
to exercise the LLM boundary without performing any network I/O. It is
intentionally simple and does not embed business logic.
"""

import hashlib

from .llm_provider import LLMProvider


class MockLLMProvider(LLMProvider):
    """Simple deterministic mock LLM provider.

    The response format is intentionally plain text so that it can be logged
    or stored without additional parsing.
    """

    def generate(self, prompt: str) -> str:
        # Derive a short, human-readable hash of the prompt so that responses
        # are stable but do not echo the full prompt content.
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return f"[MOCK LLM RESPONSE]\nPrompt hash: {digest}"
