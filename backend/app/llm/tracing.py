"""Optional LLM tracing. Off unless all three LANGFUSE_* settings are present."""

import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

from app.config import Settings

log = logging.getLogger("app.llm")


class Generation(Protocol):
    def update(self, *, output: str, usage: dict[str, int]) -> None: ...


class Tracer(Protocol):
    def generation(
        self, *, name: str, model: str, prompt: str
    ) -> AbstractContextManager[Generation]: ...


class _NoGeneration:
    def update(self, *, output: str, usage: dict[str, int]) -> None:
        return None


class NullTracer:
    @contextmanager
    def generation(self, *, name: str, model: str, prompt: str) -> Iterator[Generation]:
        yield _NoGeneration()


class LangfuseTracer:
    """Sends each JSON generation to Langfuse (SDK v4, OpenTelemetry-based)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @contextmanager
    def generation(self, *, name: str, model: str, prompt: str) -> Iterator[Generation]:
        with self._client.start_as_current_observation(
            as_type="generation", name=name, model=model, input=prompt
        ) as observation:
            yield _LangfuseGeneration(observation)


class _LangfuseGeneration:
    def __init__(self, observation: Any) -> None:
        self._observation = observation

    def update(self, *, output: str, usage: dict[str, int]) -> None:
        self._observation.update(output=output, usage_details=usage)


def make_tracer(settings: Settings) -> Tracer:
    keys = (settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_base_url)
    if not all(keys):
        return NullTracer()
    try:
        from langfuse import Langfuse  # optional dependency: uv sync --extra tracing
    except ImportError:
        log.warning("LANGFUSE_* is set but the langfuse package isn't installed; tracing is off")
        return NullTracer()
    return LangfuseTracer(
        Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
        )
    )
