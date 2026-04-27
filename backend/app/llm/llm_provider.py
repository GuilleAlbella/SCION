from __future__ import annotations

"""Abstract interface for low-level LLM providers.

This layer defines the contract that concrete providers (mock, Groq, etc.)
must implement. It is intentionally minimal and synchronous so that it can be
used from existing orchestrators without pulling in async or HTTP details.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Implementations are responsible for taking a prompt string and returning
    a response string. They do not know about TAISA or higher-level
    reasoning contracts; that mapping is handled upstream.
    """

    @abstractmethod
    def generate(self, prompt: str) -> str:  # pragma: no cover - interface only
        """Generate a response for the given prompt.

        Implementations should be deterministic/stable for the same prompt
        where possible, or at least bounded in behaviour so that tests and
        demos remain reproducible.
        """

        raise NotImplementedError
