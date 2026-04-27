from __future__ import annotations

"""TAISA integration package.

This package defines the contract between the core system and the
Reasoning & Explanation Engine (TAISA).

TAISA is not implemented yet. For demos, a concrete backend such as Groq
may be used, but this package only encodes the public interface and
expected data shapes, not any provider-specific logic.
"""

from .taisa_client import TaisaClient, TaisaClientConfig
from .taisa_models import TaisaAnalysisRequest, TaisaAnalysisResult

__all__ = [
    "TaisaClient",
    "TaisaClientConfig",
    "TaisaAnalysisRequest",
    "TaisaAnalysisResult",
]
