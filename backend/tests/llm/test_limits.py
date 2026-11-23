import pytest

from app.llm.base import LLMError
from app.llm.limits import CallBudget, LLMBudgetExceeded, TokenBucket, Usage
from app.llm.retry import with_retries


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_bucket_allows_burst_then_paces_at_rate() -> None:
    clock = FakeClock()
    bucket = TokenBucket(12, burst=3, clock=clock.time, sleep=clock.sleep)
    for _ in range(3):
        await bucket.acquire()
    assert clock.sleeps == []
    await bucket.acquire()
    assert sum(clock.sleeps) == pytest.approx(5.0)


async def test_bucket_never_exceeds_burst_plus_rate_in_a_minute() -> None:
    clock = FakeClock()
    bucket = TokenBucket(12, burst=3, clock=clock.time, sleep=clock.sleep)
    calls_in_first_minute = 0
    while clock.now <= 60.0:
        await bucket.acquire()
        calls_in_first_minute += clock.now <= 60.0
    assert calls_in_first_minute <= 15


async def test_bucket_refills_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(60, burst=3, clock=clock.time, sleep=clock.sleep)
    for _ in range(3):
        await bucket.acquire()
    clock.now += 3.0
    for _ in range(3):
        await bucket.acquire()
    assert clock.sleeps == []


def test_budget_raises_at_cap() -> None:
    budget = CallBudget(2)
    budget.spend()
    budget.spend()
    assert budget.used == 2
    with pytest.raises(LLMBudgetExceeded, match="2"):
        budget.spend()
    assert issubclass(LLMBudgetExceeded, LLMError)


def test_usage_accumulates() -> None:
    usage = Usage()
    usage.add(input_tokens=10, output_tokens=3)
    usage.add(input_tokens=5, output_tokens=None)
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (2, 15, 3)


class Transient(Exception):
    pass


async def test_retry_succeeds_after_transient_errors() -> None:
    clock = FakeClock()
    attempts = 0

    async def call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Transient
        return "ok"

    result = await with_retries(
        call,
        max_retries=4,
        is_retryable=lambda e: isinstance(e, Transient),
        sleep=clock.sleep,
        rng=lambda: 1.0,
    )
    assert (result, attempts) == ("ok", 3)
    assert clock.sleeps == [1.0, 2.0]


async def test_retry_gives_up_after_max_retries() -> None:
    clock = FakeClock()

    async def call() -> str:
        raise Transient

    with pytest.raises(Transient):
        await with_retries(
            call, max_retries=2, is_retryable=lambda e: True, sleep=clock.sleep, rng=lambda: 0.5
        )
    assert len(clock.sleeps) == 2


async def test_non_retryable_error_is_raised_immediately() -> None:
    clock = FakeClock()

    async def call() -> str:
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        await with_retries(
            call, max_retries=5, is_retryable=lambda e: False, sleep=clock.sleep, rng=lambda: 1.0
        )
    assert clock.sleeps == []


async def test_backoff_is_capped() -> None:
    clock = FakeClock()

    async def call() -> str:
        raise Transient

    with pytest.raises(Transient):
        await with_retries(
            call,
            max_retries=8,
            is_retryable=lambda e: True,
            sleep=clock.sleep,
            rng=lambda: 1.0,
            max_delay=10.0,
        )
    assert max(clock.sleeps) == 10.0


async def test_bucket_charges_a_cost_per_acquire() -> None:
    clock = FakeClock()
    bucket = TokenBucket(60, burst=40, clock=clock.time, sleep=clock.sleep)
    await bucket.acquire(40)
    assert clock.sleeps == []
    await bucket.acquire(10)
    assert sum(clock.sleeps) == pytest.approx(10.0)


async def test_bucket_rejects_a_cost_above_burst() -> None:
    bucket = TokenBucket(60, burst=40)
    with pytest.raises(ValueError, match="burst"):
        await bucket.acquire(41)
