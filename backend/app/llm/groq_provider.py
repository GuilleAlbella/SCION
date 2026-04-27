from __future__ import annotations

import requests

from app.llm.llm_provider import LLMProvider
from app.llm.llm_settings import load_taisa_llm_config


class GroqLLMProvider(LLMProvider):
    """LLM provider implementation that calls the Groq chat-completions API.

    Reads connection and model settings from ``taisa_llm.yaml`` and issues a
    single chat completion request using the configured TAISA system persona.
    """

    def generate(self, prompt: str) -> str:
        """Send ``prompt`` to Groq and return the assistant message text.

        Args:
            prompt: User-role content to append after the TAISA system prompt.

        Returns:
            The raw text of the first completion choice.

        Raises:
            RuntimeError: If the API key is not configured in the YAML file.
            requests.HTTPError: If the Groq API responds with an error status.
        """
        # Config is reloaded on every call so hot edits to taisa_llm.yaml
        # (model, temperature, key rotation) take effect without restarting
        # the API process. Cost is negligible — it's a small YAML read.
        config = load_taisa_llm_config()

        if not config.connection.api_key:
            raise RuntimeError("Groq API key is missing in taisa_llm.yaml")

        # Trailing slash normalisation so "https://api.groq.com/openai/v1/"
        # and "https://api.groq.com/openai/v1" both work.
        url = config.connection.base_url.rstrip("/") + "/chat/completions"

        headers = {
            "Authorization": f"Bearer {config.connection.api_key}",
            "Content-Type": "application/json",
        }

        # Chat-completions payload: a lightweight TAISA persona goes in the
        # system role and the caller's rendered prompt (already including the
        # structured change context) goes in the user role.
        payload = {
            "model": config.model.name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are TAISA, Teradata AI System Advisor. "
                        "You analyze database structural changes and explain risk clearly."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": config.model.temperature,
            "max_tokens": config.model.max_tokens,
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=config.connection.timeout_seconds,
        )

        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]
