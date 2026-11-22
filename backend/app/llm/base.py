"""The provider-neutral LLM interface. Pipeline code depends only on this module."""

from collections.abc import Sequence
from typing import Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

ModelRole = Literal["fast", "judge"]
"""Which configured model to use. Callers pick a role; config maps roles to model names."""

EmbedTask = Literal["document", "query"]
"""Embeddings for stored chunks versus for search queries."""

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Any failure to get a usable response from the provider."""


@runtime_checkable
class LLMClient(Protocol):
    async def generate_json(
        self,
        prompt: str,
        *,
        schema: type[T],
        system: str | None = None,
        role: ModelRole = "fast",
    ) -> T:
        """Generate a response that validates against `schema`, or raise LLMError."""
        ...

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> list[list[float]]:
        """Return one unit-length vector per input text, in order."""
        ...
