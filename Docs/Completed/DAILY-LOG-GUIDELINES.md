# Daily Log — Generation Guidelines

How to write the end-of-day entry in [DAILY-LOG.md](DAILY-LOG.md). Run this when wrapping up.

---

## Format

- **Exactly 6 bullets.** If there are more than 6 things, the extra ones were not major — merge or
  drop them. If there are fewer than 6, write fewer; do not pad.
- **2–3 lines per bullet.** Bold lead clause, then the detail.
- **One ⚠️ line at the end** stating what is *not* done or still unproven. Never omit this.
- Newest entry at the top, under a `## <D Month YYYY>` heading.

## What earns a bullet

Only **major, reportable** work:

- something now live that was not live before
- a whole capability built (a layer, a test system, a pipeline)
- a significant problem found or a design decision reversed
- a dependency removed or added
- a permanent safeguard put in place

**Not** a bullet: routine fixes, refactors, lint cleanups, individual commits, or anything a reader
outside the project would not care about.

## Tone

Written for someone **non-technical** — a client, a manager, a stakeholder. But each bullet should
carry one concrete technical fact so it is credible rather than vague.

| Write this | Not this |
|---|---|
| "Grace is now live in the Vapi account — the assistant and all 15 of her tools" | "Completed Vapi integration work" |
| "caught Grace saying 'Monday the third' for a Tuesday" | "fixed timezone handling in the date formatter" |
| "32 corrections" | "various fixes" |

- Name real things: what is live, how many, what broke.
- Explain jargon inline the first time, or avoid it. "Practice system", not "mock server".
- Prefer the consequence over the mechanism: *"would have disabled call summaries with no error
  shown"* beats *"serverMessages replaces rather than extends the default array"*.

## Honesty rules

These are the point of the log — a status report nobody trusts is worthless.

1. **Never claim something works that has not been observed working.** "Deployed" and "verified
   working" are different words; use the right one.
2. **The ⚠️ line is mandatory**, even on a good day. If everything genuinely landed, say what the
   next risk is.
3. **Report reversals and self-inflicted bugs** as plainly as wins. A log that only contains
   successes is not being read carefully.
4. If a claim in a bullet is not backed by evidence in [00-STATUS.md](00-STATUS.md), soften the
   wording or leave it out.

## Wrap-up checklist

1. Re-read the day's commits — they are the raw material.
2. Pick the 6 that a stakeholder would actually ask about.
3. Draft, then cut every clause that does not change the reader's understanding.
4. Write the ⚠️ line from [06-pending-and-blocked.md](06-pending-and-blocked.md).
5. Update the numbered technical files if anything material changed, and refresh
   **Last updated** in [00-STATUS.md](00-STATUS.md).
6. Commit with `docs: daily log <date>`.
