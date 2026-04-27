from __future__ import annotations

"""Generic LLM provider factory for SCION.

This module wires together configuration from the TAISA LLM YAML settings
with the :class:`LLMProvider` interface and concrete implementations. It does
**not** know about TAISA or higher-level reasoning; it only returns an
``LLMProvider`` suitable for use by upstream components.
"""

from .llm_provider import LLMProvider
from .mock_provider import MockLLMProvider
from .groq_provider import GroqLLMProvider
from .llm_settings import load_taisa_llm_config


def get_llm_provider() -> LLMProvider:
    """Return an appropriate :class:`LLMProvider` based on YAML config.

    Mappings:

    - ``"mock"`` (default in taisa_llm.yaml) – deterministic in-process
      implementation that performs no network I/O.
    - ``"groq"`` – reserved for a future Groq-backed provider; currently
      raises :class:`NotImplementedError`.
    """

    config = load_taisa_llm_config()
    provider = config.provider.lower()

    if provider == "mock":
        return MockLLMProvider()

    if provider == "groq":
        return GroqLLMProvider()

    raise ValueError(f"Unsupported LLM provider: {config.provider}")
