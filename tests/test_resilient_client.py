"""Resilience behaviour, asserted rather than assumed (provider-adapters.md §2).

Uses httpx.MockTransport, so these run offline and deterministically. The retry delays are
neutralised per-test — we are asserting *which* requests are made, not how long the client
sleeps between them.
"""

from __future__ import annotations

import httpx
import pytest

from grace_adapters.resilient import (
    BreakerPolicy,
    RatePolicy,
    RetryPolicy,
    create_resilient_client,
)
from grace_contracts.ports.errors import AdapterUnavailableError, RateLimitedError

NO_WAIT = RetryPolicy(max_attempts=4, base_delay_s=0.0, max_delay_s=0.0)
FAST_RATE = RatePolicy(per_second=1000.0, daily_cap=10_000)


def counting_transport(*statuses: int) -> tuple[httpx.MockTransport, list[int]]:
    """Replies with each status in turn, repeating the last one forever."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(len(calls), len(statuses) - 1)
        calls.append(statuses[index])
        return httpx.Response(statuses[index])

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_no_retry_on_4xx() -> None:
    """A 400 is an answer. Retrying it turns one bad request into four."""
    transport, calls = counting_transport(400)
    client = create_resilient_client(
        name="test",
        base_url="https://example.invalid",
        retry=NO_WAIT,
        rate=FAST_RATE,
        transport=transport,
    )
    response = await client.request("GET", "/thing")
    assert response.status_code == 400
    assert len(calls) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_retries_5xx_then_succeeds() -> None:
    transport, calls = counting_transport(503, 503, 200)
    client = create_resilient_client(
        name="test",
        base_url="https://example.invalid",
        retry=NO_WAIT,
        rate=FAST_RATE,
        transport=transport,
    )
    response = await client.request("GET", "/thing")
    assert response.status_code == 200
    assert len(calls) == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_persistent_429_raises_rate_limited_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = create_resilient_client(
        name="test",
        base_url="https://example.invalid",
        retry=NO_WAIT,
        rate=FAST_RATE,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RateLimitedError) as caught:
        await client.request("GET", "/thing")
    assert caught.value.retry_after == 0.0
    await client.aclose()


@pytest.mark.asyncio
async def test_breaker_opens_and_stops_sending() -> None:
    """Once open, the breaker must fail WITHOUT a request — that is the whole value."""
    transport, calls = counting_transport(500)
    client = create_resilient_client(
        name="test",
        base_url="https://example.invalid",
        retry=RetryPolicy(max_attempts=1, base_delay_s=0.0, max_delay_s=0.0),
        breaker=BreakerPolicy(consecutive_failures=3, recovery_s=60.0),
        rate=FAST_RATE,
        transport=transport,
    )
    for _ in range(3):
        await client.request("GET", "/thing")
    assert len(calls) == 3

    with pytest.raises(AdapterUnavailableError):
        await client.request("GET", "/thing")
    assert len(calls) == 3, "breaker was open but a request was still sent"
    await client.aclose()


@pytest.mark.asyncio
async def test_daily_cap_refuses_rather_than_spending_the_monthly_quota() -> None:
    """Vagaro allows 5,000 calls/month. A runaway loop must cost a refusal, not the month."""
    transport, calls = counting_transport(200)
    client = create_resilient_client(
        name="test",
        base_url="https://example.invalid",
        retry=NO_WAIT,
        rate=RatePolicy(per_second=1000.0, daily_cap=2),
        transport=transport,
    )
    await client.request("GET", "/a")
    await client.request("GET", "/b")
    with pytest.raises(AdapterUnavailableError, match="daily request cap"):
        await client.request("GET", "/c")
    assert len(calls) == 2
    assert client.requests_today == 2
    await client.aclose()
