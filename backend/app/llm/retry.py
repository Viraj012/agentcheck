"""Retry with exponential backoff and full jitter."""

import asyncio
import random
from collections.abc import Awaitable, Callable


async def with_retries[R](
    call: Callable[[], Awaitable[R]],
    *,
    max_retries: int,
    is_retryable: Callable[[BaseException], bool],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> R:
    """Run `call`; on a retryable error wait `rng() * min(max_delay, base * 2**attempt)` and retry.

    Full jitter spreads retries from many clients so they don't hit the API in lockstep.
    """
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as exc:
            if attempt >= max_retries or not is_retryable(exc):
                raise
            await sleep(rng() * min(max_delay, base_delay * 2**attempt))
            attempt += 1
