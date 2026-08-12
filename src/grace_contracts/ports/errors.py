"""Adapter error taxonomy (provider-adapters.md §2, §9).

These are the only failures the layers above an adapter are expected to distinguish.
Anything else is a bug and should propagate.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base for every failure raised out of an adapter."""


class NotSupportedByProvider(AdapterError):
    """The operation is real but this provider cannot do it.

    Raised when a capability flag is False — never caught by branching on the adapter's
    class. Callers ask ``pms.capabilities.write_appointments``; this exception is the
    backstop for code that forgot to.
    """

    def __init__(self, operation: str, provider: str = "provider") -> None:
        super().__init__(f"{provider} does not support {operation}")
        self.operation = operation
        self.provider = provider


class RateLimitedError(AdapterError):
    """429 from the provider. ``retry_after`` is seconds, when the provider said."""

    def __init__(self, message: str = "rate limited", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AdapterUnavailableError(AdapterError):
    """The circuit breaker is open, or the daily request budget is spent.

    No request was made. Distinct from a failed request: retrying immediately is
    pointless, and the caller should degrade rather than wait.
    """
