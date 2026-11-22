import math

import pytest
from pydantic import BaseModel

from app.llm import FakeLLMClient, LLMClient, LLMError


class Answer(BaseModel):
    answer: str
    abstained: bool


async def test_returns_scripted_response_as_schema() -> None:
    client = FakeLLMClient([{"answer": "5 days", "abstained": False}], dim=8)
    result = await client.generate_json("q", schema=Answer)
    assert result == Answer(answer="5 days", abstained=False)


async def test_records_calls() -> None:
    client = FakeLLMClient([{"answer": "a", "abstained": True}], dim=8)
    await client.generate_json("the prompt", schema=Answer, system="sys", role="judge")
    await client.embed(["x"], task="query")
    assert [(c.kind, c.prompt, c.system, c.role) for c in client.calls] == [
        ("generate_json", "the prompt", "sys", "judge"),
        ("embed", "x", None, None),
    ]


async def test_raises_when_script_is_exhausted() -> None:
    client = FakeLLMClient([], dim=8)
    with pytest.raises(LLMError, match="no scripted response"):
        await client.generate_json("q", schema=Answer)


async def test_invalid_response_raises_llm_error() -> None:
    client = FakeLLMClient([{"answer": "missing abstained"}], dim=8)
    with pytest.raises(LLMError, match="does not match"):
        await client.generate_json("q", schema=Answer)


async def test_embed_is_deterministic_and_unit_length() -> None:
    client = FakeLLMClient(dim=16)
    first, second, other = await client.embed(["refunds", "refunds", "shipping"], task="document")
    assert first == second
    assert first != other
    assert len(first) == 16
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-9)


def test_fake_satisfies_protocol() -> None:
    assert isinstance(FakeLLMClient(dim=8), LLMClient)
