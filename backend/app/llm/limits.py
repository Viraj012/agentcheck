"""Guards around the LLM provider: pace requests, cap calls per run, count tokens."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.llm.base import LLMError


class LLMBudgetExceeded(LLMError):
    """The run has used all of its allowed LLM calls."""


class TokenBucket:
    """Allows `burst` calls at once, then refills at `rate_per_minute`.

    In any 60-second window at most `burst + rate_per_minute` calls go out, so keep that
    sum at or below the provider's per-minute limit.
    """

    def __init__(
        self,
        rate_per_minute: int,
        *,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._per_second = rate_per_minute / 60.0
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            self._refill()
            if self._tokens < 1.0:
                await self._sleep((1.0 - self._tokens) / self._per_second)
                self._refill()
            self._tokens -= 1.0

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._per_second)
        self._updated = now


class CallBudget:
    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.max_calls:
            raise LLMBudgetExceeded(f"run reached its limit of {self.max_calls} LLM calls")
        self.used += 1


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, *, input_tokens: int | None, output_tokens: int | None) -> None:
        self.calls += 1
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0
