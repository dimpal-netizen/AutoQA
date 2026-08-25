"""OpenAI model and prices — the configured fallback.

The call itself goes through app/ai/langchain_client.py. Claude is the primary
provider; this exists so LLM_PROVIDER=openai is a real option.
"""

from __future__ import annotations

MODEL = "gpt-5"

#: Per million tokens, for the cost ledger.
INPUT_COST_PER_MTOK = 1.25
OUTPUT_COST_PER_MTOK = 10.00
