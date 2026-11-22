"""LLMClient backed by the Google Gemini API (google-genai SDK).

Every attempt to call the API, including retries, waits for the shared rate limiter and
spends one unit of the run's call budget. The SDK's own retries are switched off so that
this module is the only place retries happen.
"""

import math
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx2
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.config import Settings
from app.llm.base import EmbedTask, LLMError, ModelRole, T
from app.llm.limits import CallBudget, TokenBucket, Usage
from app.llm.retry import with_retries

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_STATUS
    return isinstance(exc, httpx2.TransportError)


class GeminiLLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        limiter: TokenBucket,
        budget: CallBudget,
        usage: Usage,
        models: Any = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._limiter = limiter
        self._budget = budget
        self._usage = usage
        self._models = models if models is not None else _sdk_models(settings)
        self._sleep_kwargs = {"sleep": sleep} if sleep else {}
        self._model_names: dict[ModelRole, str] = {
            "fast": settings.gemini_model_fast,
            "judge": settings.gemini_model_judge,
        }

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: type[T],
        system: str | None = None,
        role: ModelRole = "fast",
    ) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
        )
        response = await self._call(
            lambda: self._models.generate_content(
                model=self._model_names[role], contents=prompt, config=config
            )
        )
        meta = response.usage_metadata
        self._usage.add(
            input_tokens=getattr(meta, "prompt_token_count", None),
            output_tokens=(getattr(meta, "candidates_token_count", None) or 0)
            + (getattr(meta, "thoughts_token_count", None) or 0),
        )
        if not response.text:
            raise LLMError("model returned no text (possibly blocked)")
        try:
            return schema.model_validate_json(response.text)
        except ValidationError as exc:
            raise LLMError(f"model output does not match {schema.__name__}") from exc

    async def embed(
        self, texts: Sequence[str], *, task: EmbedTask, titles: Sequence[str] | None = None
    ) -> list[list[float]]:
        prepared = [
            _embedding_input(text, task, titles[i] if titles else None)
            for i, text in enumerate(texts)
        ]
        config = types.EmbedContentConfig(output_dimensionality=self._settings.embedding_dim)
        vectors: list[list[float]] = []
        for start in range(0, len(prepared), self._settings.embed_batch):
            contents = [
                types.Content(parts=[types.Part.from_text(text=text)])
                for text in prepared[start : start + self._settings.embed_batch]
            ]
            response = await self._call(
                lambda contents=contents: self._models.embed_content(
                    model=self._settings.gemini_embedding_model, contents=contents, config=config
                )
            )
            self._usage.add(input_tokens=None, output_tokens=None)
            vectors += [self._normalize(embedding.values) for embedding in response.embeddings]
        return vectors

    async def _call(self, request: Callable[[], Awaitable[Any]]) -> Any:
        async def attempt() -> Any:
            self._budget.spend()
            await self._limiter.acquire()
            return await request()

        try:
            return await with_retries(
                attempt,
                max_retries=self._settings.llm_max_retries,
                is_retryable=is_retryable,
                **self._sleep_kwargs,
            )
        except errors.APIError as exc:
            raise LLMError(f"Gemini API error {exc.code}: {exc.message}") from exc
        except httpx2.TransportError as exc:
            raise LLMError(f"Gemini API unreachable: {exc}") from exc

    def _normalize(self, values: Sequence[float]) -> list[float]:
        if len(values) != self._settings.embedding_dim:
            raise LLMError(
                f"embedding dimension {len(values)} != configured {self._settings.embedding_dim}"
            )
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


def _embedding_input(text: str, task: EmbedTask, title: str | None) -> str:
    if task == "query":
        return f"task: question answering | query: {text}"
    return f"title: {title or 'none'} | text: {text}"


def _sdk_models(settings: Settings) -> Any:
    if settings.gemini_api_key is None:
        raise LLMError("GEMINI_API_KEY is not set")
    client = genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(), http_options=http_options(settings)
    )
    return client.aio.models


def http_options(settings: Settings) -> types.HttpOptions:
    """A timeout so a hung request can't stall a run, and no SDK retries (ours do that)."""
    return types.HttpOptions(
        timeout=int(settings.llm_timeout_s * 1000),
        retry_options=types.HttpRetryOptions(attempts=1),
    )
