from contextlib import contextmanager
from typing import Any

from app.config import Settings
from app.llm.tracing import NullTracer, make_tracer
from tests.llm.test_gemini import GOOD, FakeModels, Verdict, make_client, response


class RecordingTracer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    @contextmanager
    def generation(self, *, name: str, model: str, prompt: str):
        record: dict[str, Any] = {"name": name, "model": model, "prompt": prompt}
        self.records.append(record)
        yield _Recorder(record)


class _Recorder:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record

    def update(self, *, output: str, usage: dict[str, int]) -> None:
        self.record |= {"output": output, "usage": usage}


def test_tracing_is_off_without_langfuse_keys() -> None:
    assert isinstance(make_tracer(Settings(_env_file=None)), NullTracer)


async def test_generations_are_traced_with_output_and_usage() -> None:
    tracer = RecordingTracer()
    client, _, _ = make_client(FakeModels([response(GOOD, prompt=7, out=3, thoughts=1)]))
    client._tracer = tracer
    await client.generate_json("grade this", schema=Verdict, role="judge")
    (record,) = tracer.records
    assert record["name"] == "generate_json:Verdict"
    assert record["prompt"] == "grade this"
    assert record["output"] == GOOD
    assert record["usage"] == {"input": 7, "output": 4}
