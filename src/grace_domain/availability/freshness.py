"""Is the local mirror fresh enough to answer with?

**This is an addition to the frozen design, not part of it.** `availability-engine.md`
specifies refresh cadences and drift *alerts*, but nothing that stops the engine answering
from a stale mirror. That gap matters more here than it would elsewhere:

* availability is answered entirely from our own copy of the calendar (invariant I1), so
  if the copy stops updating, the engine has no way to notice from the data alone;
* an **empty** mirror is indistinguishable from a genuinely free calendar — the engine
  would cheerfully offer every slot in the week;
* while Massagebook and Vagaro are dual-running (GATE-12), the mirror is the only place
  those two views are reconciled.

So: a stale mirror must produce an honest "I can't reach the schedule, let me get someone"
rather than a confident wrong answer. Offering a slot that was booked an hour ago and
having the customer turn up to a full room is far worse than admitting the gap.

Pure — takes the sync timestamp, returns a verdict. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

#: The poller runs every 10 minutes and webhooks land in under 5 seconds, so 30 minutes
#: means several consecutive failures — comfortably past a transient blip, well short of
#: a caller noticing the schedule is wrong.
DEFAULT_MAX_AGE = timedelta(minutes=30)

#: The source key in `sync_state` this gate reads.
APPOINTMENT_SYNC_SOURCE = "vagaro.appointments"


@dataclass(frozen=True, slots=True)
class Freshness:
    usable: bool
    reason: str | None = None
    age: timedelta | None = None

    @property
    def spoken_fallback(self) -> str:
        """What Grace says instead of inventing availability (core-api.md §6.4)."""
        return "I'm having trouble reaching the schedule. Let me get someone who can help."


def evaluate(
    last_success_at: datetime | None,
    *,
    now: datetime,
    max_age: timedelta = DEFAULT_MAX_AGE,
    mirror_has_rows: bool = True,
) -> Freshness:
    """Decide whether availability may be offered at all.

    ``mirror_has_rows`` is checked separately from the timestamp on purpose: a sync that
    has never run leaves no timestamp, and a sync that ran against an empty result leaves
    a fresh timestamp with nothing behind it. Neither should be answered confidently.
    """
    if last_success_at is None:
        return Freshness(
            usable=False,
            reason="the appointment mirror has never synced — there is nothing to answer from",
        )

    age = now - last_success_at
    if age > max_age:
        return Freshness(
            usable=False,
            reason=(
                f"the appointment mirror last synced {int(age.total_seconds() // 60)} minutes "
                f"ago, past the {int(max_age.total_seconds() // 60)}-minute limit"
            ),
            age=age,
        )

    if not mirror_has_rows:
        return Freshness(
            usable=False,
            reason=(
                "the appointment mirror is empty, which is indistinguishable from a "
                "completely free calendar"
            ),
            age=age,
        )

    return Freshness(usable=True, age=age)
