from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class LLMConnectionConfig:
    """HTTP connection parameters for the LLM provider.

    Attributes:
        base_url: Root URL of the LLM API (without trailing path).
        api_key: Bearer token used in the ``Authorization`` header.
        timeout_seconds: Request timeout applied to each HTTP call.
    """

    base_url: str
    api_key: str
    timeout_seconds: int = 30


@dataclass
class LLMModelConfig:
    """Model-level sampling parameters.

    Attributes:
        name: Provider-specific model identifier.
        temperature: Sampling temperature passed to the API.
        max_tokens: Maximum tokens to generate per response.
    """

    name: str
    temperature: float = 0.0
    max_tokens: int = 1024


@dataclass
class TaisaLLMConfig:
    """Resolved TAISA LLM configuration loaded from YAML.

    Attributes:
        provider: Provider key (e.g. ``groq``, ``mock``).
        public_name: Display name shown to end users.
        connection: HTTP connection settings.
        model: Model and sampling settings.
    """

    provider: str
    public_name: str
    connection: LLMConnectionConfig
    model: LLMModelConfig


def load_taisa_llm_config() -> TaisaLLMConfig:
    """Load and parse ``backend/app/config/taisa_llm.yaml`` into a config object.

    Returns:
        A fully populated ``TaisaLLMConfig``.

    Raises:
        RuntimeError: If the YAML configuration file is missing.
    """
    config_path = Path(__file__).parent.parent / "config" / "taisa_llm.yaml"

    if not config_path.exists():
        raise RuntimeError(
            "TAISA LLM config file not found: backend/app/config/taisa_llm.yaml"
        )

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return TaisaLLMConfig(
        provider=raw["provider"],
        public_name=raw.get("public_name", "TAISA"),
        connection=LLMConnectionConfig(**raw["connection"]),
        model=LLMModelConfig(**raw["model"]),
    )
