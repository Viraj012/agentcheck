"""Smoke-test the real Gemini API: two embedding calls and one JSON call.

Run from the backend folder:  uv run python ../scripts/gemini_smoke.py
Prints only shapes and token counts, never the API key.
"""

import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pydantic import BaseModel  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.llm.gemini import GeminiLLMClient  # noqa: E402
from app.llm.limits import CallBudget, TokenBucket, Usage  # noqa: E402


class Capital(BaseModel):
    country: str
    capital: str


async def main() -> None:
    settings = get_settings()
    usage = Usage()
    client = GeminiLLMClient(
        settings,
        limiter=TokenBucket(settings.llm_rpm, burst=settings.llm_burst),
        budget=CallBudget(3),
        usage=usage,
    )
    docs = await client.embed(
        ["Refunds go to the original payment method.", "Standard shipping takes 3-5 days."],
        task="document",
        titles=["Returns", "Shipping"],
    )
    (query,) = await client.embed(["How do I get my money back?"], task="query")
    similarity = [sum(q * d for q, d in zip(query, doc, strict=True)) for doc in docs]
    print(f"embeddings: {len(docs)} docs x {len(docs[0])} dims, norm={math.hypot(*docs[0]):.3f}")
    print(f"query similarity  refunds={similarity[0]:.3f}  shipping={similarity[1]:.3f}")
    answer = await client.generate_json(
        "What is the capital of France?", schema=Capital, system="Answer in JSON."
    )
    print(f"generate_json ({settings.gemini_model_fast}): {answer.model_dump()}")
    print(f"usage: {usage.calls} calls, {usage.input_tokens} in, {usage.output_tokens} out")


if __name__ == "__main__":
    asyncio.run(main())
