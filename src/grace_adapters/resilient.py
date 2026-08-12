"""Retry, circuit breaker, timeout and rate limiting for every outbound adapter call.

provider-adapters.md §2. Written once here so no adapter re-invents it, and so the
behaviour under a provider outage is a property of the system rather than of whoever wrote
that particular client.

The four pieces, and why each exists:

* **Retry** — exponential backoff with full jitter, on 429/5xx/transport only. Never on a
  4xx: a rejected request is rejected, and retrying it is how you turn one bad request
  into four. Honours ``Retry-After`` when the provider sends it.
* **Circuit breaker** — after repeated failures, stop asking. An open breaker fails
  *immediately* with `AdapterUnavailableError`, which is what lets a caller degrade
  gracefully instead of waiting out four timeouts.
* **Timeout** — always explicit. A hung connection with no timeout is an outage.
* **Rate limit** — a token bucket, because Vagaro's plan allows **5,000 calls per month**
  (~166/day). That is the number the whole mirror architecture exists to respect: in-call
  reads come from local Postgres, and this budget is spent only on sync. The daily cap
  makes a runaway loop cost a warning instead of the month's quota.

Single instance, single process, so the bucket and breaker are in-memory. If a second
instance ever runs, this becomes shared state (Redis) — noted rather than pre-built.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from grace_contracts.ports.errors import AdapterUnavailableError, RateLimitedError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0


@dataclass(frozen=True, slots=True)
class BreakerPolicy:
    consecutive_failures: int = 5
    window_size: int = 20
    window_error_ratio: float = 0.5
    recovery_s: float = 30.0


@dataclass(frozen=True, slots=True)
class RatePolicy:
    """Defaults are deliberately below Vagaro's unpublished limits (GATE-03).

    ``monthly_budget`` is not enforced — it is the number the warning is measured against,
    so we hear about a quota problem in week two rather than on the day it runs out.
    """

    per_second: float = 2.0
    daily_cap: int = 3000
    monthly_budget: int = 5000
    warn_ratio: float = 0.8


class _Breaker:
    """Closed → (failures) → open → (recovery elapsed) → half-open → closed or open."""

    def __init__(self, policy: BreakerPolicy, name: str) -> None:
        self._policy = policy
        self._name = name
        self._consecutive = 0
        self._recent: deque[bool] = deque(maxlen=policy.window_size)
        self._opened_at: float | None = None

    def before_request(self) -> None:
        if self._opened_at is None:
            return
        if time.monotonic() - self._opened_at < self._policy.recovery_s:
            raise AdapterUnavailableError(
                f"{self._name}: circuit breaker is open — not sending the request"
            )
        # Recovery elapsed: allow exactly one probe through (half-open).
        self._opened_at = None
        self._consecutive = 0
        self._recent.clear()
        log.info("%s: circuit breaker half-open, probing", self._name)

    def record(self, *, ok: bool) -> None:
        self._recent.append(ok)
        self._consecutive = 0 if ok else self._consecutive + 1

        tripped_consecutive = self._consecutive >= self._policy.consecutive_failures
        full_window = len(self._recent) == self._recent.maxlen
        error_ratio = (1 - sum(self._recent) / len(self._recent)) if self._recent else 0.0
        tripped_ratio = full_window and error_ratio >= self._policy.window_error_ratio

        if tripped_consecutive or tripped_ratio:
            self._opened_at = time.monotonic()
            log.error(
                "%s: circuit breaker OPEN (consecutive=%d, error_ratio=%.2f) — "
                "failing fast for %.0fs",
                self._name,
                self._consecutive,
                error_ratio,
                self._policy.recovery_s,
            )


class _TokenBucket:
    def __init__(self, policy: RatePolicy, name: str) -> None:
        self._policy = policy
        self._name = name
        self._tokens = policy.per_second
        self._updated = time.monotonic()
        self._day = time.gmtime().tm_yday
        self._today = 0
        self._warned = False
        self._lock = asyncio.Lock()

    async def take(self) -> None:
        async with self._lock:
            today = time.gmtime().tm_yday
            if today != self._day:
                self._day, self._today, self._warned = today, 0, False

            if self._today >= self._policy.daily_cap:
                raise AdapterUnavailableError(
                    f"{self._name}: daily request cap of {self._policy.daily_cap} reached — "
                    "refusing to spend more of the monthly API quota"
                )

            while True:
                now = time.monotonic()
                self._tokens = min(
                    self._policy.per_second,
                    self._tokens + (now - self._updated) * self._policy.per_second,
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    break
                await asyncio.sleep((1 - self._tokens) / self._policy.per_second)

            self._today += 1
            projected_month = self._today * 30
            if (
                not self._warned
                and projected_month >= self._policy.monthly_budget * self._policy.warn_ratio
            ):
                self._warned = True
                log.warning(
                    "%s: today's %d requests project to ~%d/month against a %d budget",
                    self._name,
                    self._today,
                    projected_month,
                    self._policy.monthly_budget,
                )

    @property
    def used_today(self) -> int:
        return self._today


@dataclass
class ResilientClient:
    """An httpx.AsyncClient wrapped in the four behaviours above.

    Use ``request`` rather than the underlying client so nothing bypasses the protections.
    """

    name: str
    client: httpx.AsyncClient
    auth: Callable[[], Awaitable[dict[str, str]]] | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    _breaker: _Breaker = field(init=False)
    _bucket: _TokenBucket = field(init=False)

    def __post_init__(self) -> None:  # pragma: no cover - trivial wiring
        if not hasattr(self, "_breaker"):
            self._breaker = _Breaker(BreakerPolicy(), self.name)
        if not hasattr(self, "_bucket"):
            self._bucket = _TokenBucket(RatePolicy(), self.name)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, self.retry.max_attempts + 1):
            self._breaker.before_request()
            await self._bucket.take()

            headers: dict[str, str] = dict(kwargs.pop("headers", None) or {})
            if self.auth is not None:
                headers.update(await self.auth())

            try:
                response = await self.client.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                self._breaker.record(ok=False)
                if attempt == self.retry.max_attempts:
                    break
                await asyncio.sleep(self._backoff(attempt))
                continue

            if response.status_code not in RETRYABLE_STATUS:
                # 4xx included: a rejected request is a real answer, not a blip.
                self._breaker.record(ok=response.status_code < 500)
                return response

            self._breaker.record(ok=False)
            retry_after = _retry_after(response)
            if attempt == self.retry.max_attempts:
                if response.status_code == 429:
                    raise RateLimitedError(
                        f"{self.name}: rate limited after {attempt} attempts",
                        retry_after=retry_after,
                    )
                return response

            await asyncio.sleep(retry_after if retry_after is not None else self._backoff(attempt))

        raise AdapterUnavailableError(
            f"{self.name}: {self.retry.max_attempts} attempts failed — {last_error}"
        )

    def _backoff(self, attempt: int) -> float:
        """Exponential with FULL jitter — uniform(0, cap), not cap±jitter.

        Full jitter is what actually de-synchronises a thundering herd; the half-measure
        leaves every client retrying in the same narrow window.
        """
        ceiling = min(self.retry.base_delay_s * (2 ** (attempt - 1)), self.retry.max_delay_s)
        return random.uniform(0, ceiling)

    @property
    def requests_today(self) -> int:
        return self._bucket.used_today

    async def aclose(self) -> None:
        await self.client.aclose()


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None  # HTTP-date form; backoff covers it


def create_resilient_client(
    *,
    name: str,
    base_url: str,
    timeout_s: float = 10.0,
    auth: Callable[[], Awaitable[dict[str, str]]] | None = None,
    retry: RetryPolicy | None = None,
    breaker: BreakerPolicy | None = None,
    rate: RatePolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ResilientClient:
    """Build the one client type every adapter is allowed to use."""
    wrapper = ResilientClient(
        name=name,
        client=httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout_s), transport=transport
        ),
        auth=auth,
        retry=retry or RetryPolicy(),
    )
    wrapper._breaker = _Breaker(breaker or BreakerPolicy(), name)
    wrapper._bucket = _TokenBucket(rate or RatePolicy(), name)
    return wrapper
