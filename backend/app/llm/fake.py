"""A deterministic, offline LLMClient for tests."""

import hashlib
import math
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.llm.base import EmbedTask, LLMError, ModelRole, T


@dataclass(frozen=True)
class FakeCall:
    kind: Literal["generate_json", "embed"]
    prompt: str
    system: str | None
    role: ModelRole | None


class FakeLLMClient:
    """Returns scripted JSON responses in order (or builds each one from the prompt with
    `responder`) and hash-derived embeddings."""

    def __init__(
        self,
        responses: Iterable[dict[str, Any] | BaseModel] = (),
        *,
        dim: int,
        responder: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._responses = deque(responses)
        self._responder = responder
        self._dim = dim
        self.calls: list[FakeCall] = []

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: type[T],
        system: str | None = None,
        role: ModelRole = "fast",
    ) -> T:
        self.calls.append(FakeCall("generate_json", prompt, system, role))
        if self._responder is not None:
            self._responses.append(self._responder(prompt))
        if not self._responses:
            raise LLMError("FakeLLMClient has no scripted response left")
        response = self._responses.popleft()
        data = response.model_dump() if isinstance(response, BaseModel) else response
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            raise LLMError(f"scripted response does not match {schema.__name__}") from exc

    async def embed(
        self, texts: Sequence[str], *, task: EmbedTask, titles: Sequence[str] | None = None
    ) -> list[list[float]]:
        self.calls.extend(FakeCall("embed", text, None, None) for text in texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        raw = [hashlib.sha256(f"{i}:{text}".encode()).digest()[0] - 127.5 for i in range(self._dim)]
        norm = math.sqrt(sum(v * v for v in raw))
        return [v / norm for v in raw]
