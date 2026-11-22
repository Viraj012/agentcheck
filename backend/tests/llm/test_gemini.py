import math
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from google.genai import errors
from pydantic import BaseModel

from app.config import Settings
from app.llm.base import LLMClient, LLMError
from app.llm.gemini import GeminiLLMClient
from app.llm.limits import CallBudget, LLMBudgetExceeded, TokenBucket, Usage


class Verdict(BaseModel):
    verdict: str
    reason: str


def response(text: str, prompt: int = 10, out: int = 4, thoughts: int | None = 2) -> Any:
    usage = SimpleNamespace(
        prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts
    )
    return SimpleNamespace(text=text, usage_metadata=usage)


class FakeModels:
    """Stands in for `genai.Client().aio.models`; replays scripted results or exceptions."""

    def __init__(self, generate: list[Any] | None = None, dim: int = 4) -> None:
        self.generate = list(generate or [])
        self.dim = dim
        self.generate_calls: list[dict[str, Any]] = []
        self.embed_calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> Any:
        self.generate_calls.append(kwargs)
        result = self.generate.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def embed_content(self, **kwargs: Any) -> Any:
        self.embed_calls.append(kwargs)
        vectors = [[3.0, 4.0] + [0.0] * (self.dim - 2) for _ in kwargs["contents"]]
        return SimpleNamespace(embeddings=[SimpleNamespace(values=v) for v in vectors])


async def no_sleep(_: float) -> None:
    return None


def make_client(models: FakeModels, **overrides: Any) -> tuple[GeminiLLMClient, CallBudget, Usage]:
    settings = Settings(_env_file=None, embedding_dim=4, **overrides)
    budget = CallBudget(settings.max_llm_calls_per_run)
    usage = Usage()
    limiter = TokenBucket(6000, burst=100, sleep=no_sleep)
    client = GeminiLLMClient(
        settings, limiter=limiter, budget=budget, usage=usage, models=models, sleep=no_sleep
    )
    return client, budget, usage


def rate_limited() -> errors.ClientError:
    return errors.ClientError(429, {"error": {"code": 429, "message": "quota exceeded"}})


GOOD = '{"verdict": "correct", "reason": "matches the source"}'


def test_satisfies_protocol() -> None:
    assert isinstance(make_client(FakeModels())[0], LLMClient)


async def test_generate_json_uses_role_model_and_schema() -> None:
    models = FakeModels([response(GOOD)])
    client, _, _ = make_client(models)
    result = await client.generate_json(
        "grade this", schema=Verdict, system="be strict", role="judge"
    )
    assert result == Verdict(verdict="correct", reason="matches the source")
    call = models.generate_calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert call["contents"] == "grade this"
    assert call["config"].response_schema is Verdict
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].system_instruction == "be strict"
    assert call["config"].temperature == 0


async def test_fast_role_uses_fast_model() -> None:
    models = FakeModels([response(GOOD)])
    client, _, _ = make_client(models)
    await client.generate_json("q", schema=Verdict)
    assert models.generate_calls[0]["model"] == "gemini-3.5-flash-lite"


async def test_usage_counts_thinking_tokens_as_output() -> None:
    client, _, usage = make_client(FakeModels([response(GOOD, prompt=100, out=20, thoughts=30)]))
    await client.generate_json("q", schema=Verdict)
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (1, 100, 50)


@pytest.mark.parametrize("text", ['{"verdict": "x"}', "not json", None])
async def test_invalid_or_empty_output_raises_llm_error(text: str | None) -> None:
    client, _, _ = make_client(FakeModels([response(text)]))
    with pytest.raises(LLMError):
        await client.generate_json("q", schema=Verdict)


async def test_rate_limit_is_retried_and_every_attempt_is_budgeted() -> None:
    models = FakeModels([rate_limited(), rate_limited(), response(GOOD)])
    client, budget, usage = make_client(models)
    await client.generate_json("q", schema=Verdict)
    assert len(models.generate_calls) == 3
    assert budget.used == 3
    assert usage.calls == 1


async def test_network_timeout_is_retried() -> None:
    models = FakeModels([httpx2.ReadTimeout("slow"), response(GOOD)])
    client, _, _ = make_client(models)
    await client.generate_json("q", schema=Verdict)
    assert len(models.generate_calls) == 2


async def test_client_error_is_not_retried() -> None:
    bad = errors.ClientError(400, {"error": {"code": 400, "message": "bad schema"}})
    models = FakeModels([bad, response(GOOD)])
    client, _, _ = make_client(models)
    with pytest.raises(LLMError, match="bad schema"):
        await client.generate_json("q", schema=Verdict)
    assert len(models.generate_calls) == 1


async def test_budget_stops_retries() -> None:
    models = FakeModels([rate_limited()] * 5)
    client, _, _ = make_client(models, max_llm_calls_per_run=2)
    with pytest.raises(LLMBudgetExceeded):
        await client.generate_json("q", schema=Verdict)
    assert len(models.generate_calls) == 2


async def test_embed_batches_wraps_prefixes_and_normalizes() -> None:
    models = FakeModels()
    client, budget, _ = make_client(models, embed_batch=2)
    vectors = await client.embed(
        ["refunds take time", "shipping costs", "gift cards"],
        task="document",
        titles=["Returns", "Shipping", "Gift cards"],
    )
    assert len(models.embed_calls) == 2
    assert budget.used == 2
    first = models.embed_calls[0]
    assert first["model"] == "gemini-embedding-2"
    assert first["config"].output_dimensionality == 4
    texts = [content.parts[0].text for content in first["contents"]]
    assert texts == [
        "title: Returns | text: refunds take time",
        "title: Shipping | text: shipping costs",
    ]
    assert len(vectors) == 3
    assert all(math.isclose(math.hypot(*v), 1.0) for v in vectors)


async def test_query_embeddings_use_question_answering_prefix() -> None:
    models = FakeModels()
    client, _, _ = make_client(models)
    await client.embed(["how long do refunds take?"], task="query")
    text = models.embed_calls[0]["contents"][0].parts[0].text
    assert text == "task: question answering | query: how long do refunds take?"


async def test_document_without_title_uses_none() -> None:
    models = FakeModels()
    client, _, _ = make_client(models)
    await client.embed(["text"], task="document")
    assert models.embed_calls[0]["contents"][0].parts[0].text == "title: none | text: text"


async def test_wrong_embedding_dimension_raises() -> None:
    client, _, _ = make_client(FakeModels(dim=8))
    with pytest.raises(LLMError, match="dimension"):
        await client.embed(["x"], task="query")


async def test_embed_empty_list_makes_no_call() -> None:
    models = FakeModels()
    client, budget, _ = make_client(models)
    assert await client.embed([], task="document") == []
    assert budget.used == 0


def test_sdk_requests_time_out_and_skip_sdk_retries() -> None:
    from app.llm.gemini import http_options

    options = http_options(Settings(_env_file=None, llm_timeout_s=45))
    assert options.timeout == 45_000
    assert options.retry_options.attempts == 1
