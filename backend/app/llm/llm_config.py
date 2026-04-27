from __future__ import annotations

"""Configuration for the generic LLM provider layer.

This module is responsible **only** for reading environment-driven
configuration for the low-level LLM provider. It does not perform any
network I/O, does not know about TAISA or reasoning, and does not
validate API keys.
"""

import os
from typing import Final


# Provider selection ----------------------------------------------------------

# Logical provider name. By convention:
# - "mock" (default) – in-process deterministic stub, no network calls.
# - "groq"           – future real provider backed by Groq's API.
LLM_PROVIDER: Final[str] = os.getenv("SCION_LLM_PROVIDER", "mock").lower()


# Model and endpoint configuration -------------------------------------------

# Default model identifier for the selected provider. The concrete meaning is
# provider-specific and interpreted only by the chosen LLMProvider
# implementation.
LLM_MODEL: Final[str] = os.getenv("SCION_LLM_MODEL", "scion-llm-demo")

# Optional base URL for HTTP-based LLM providers. Not used by the mock
# implementation, but reserved for future real providers (e.g. Groq).
LLM_BASE_URL: Final[str] = os.getenv("SCION_LLM_BASE_URL", "")

# API key for real LLM providers. This module merely exposes the value; it
# does not validate presence or permissions.
LLM_API_KEY: Final[str] = os.getenv("SCION_LLM_API_KEY", "")

# Request timeout in seconds for network-based providers.
try:
    LLM_TIMEOUT: Final[float] = float(os.getenv("SCION_LLM_TIMEOUT", "30"))
except ValueError:  # pragma: no cover - defensive fallback
    LLM_TIMEOUT = 30.0
