from __future__ import annotations

from app.llm import get_llm_provider


def main() -> None:
    provider = get_llm_provider()

    prompt = """
You are TAISA, an AI for data governance.
Explain briefly the risk of adding a new table to a production schema.
"""

    result = provider.generate(prompt)

    print("LLM response:")
    print(result)


if __name__ == "__main__":
    main()
