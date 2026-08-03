# Daily Log — Generation Guidelines

How to write the end-of-day entry in [DAILY-LOG.md](DAILY-LOG.md). Run this when wrapping up.

**The log records engineering output** — features built, systems deployed, technical problems
solved — **written so a non-technical reader can follow it.**

Both halves matter. Technical substance with no plain explanation is unreadable to the people who
need the status. Plain explanation with no substance is not worth writing.

---

## Format

- **Exactly 6 bullets.** More than 6 means the extras were not major — merge or drop. Fewer is fine;
  never pad.
- **2–4 lines per bullet.** Bold lead clause naming the thing built, then the technical substance.
- **One ⚠️ line at the end** listing what is unproven or broken. Never omit it.
- Newest entry on top, under a `## <D Month YYYY>` heading.

## What earns a bullet

Engineering output only:

- a system, service or pipeline that now exists and did not before
- something deployed and running
- a non-obvious technical problem solved, and *how*
- an API/platform incompatibility discovered, and where it is now caught
- a mechanism that prevents a class of bug (validator, generator, constraint, test)
- an architectural decision with a concrete technical consequence

## What does NOT earn a bullet

These are noise. Leave them out entirely — not even a short mention.

| Excluded | Why |
|---|---|
| Writing, rewriting or reorganising documentation | Not a feature |
| "Removed X", "cleaned up Y", "renamed Z" | Housekeeping, unless it changed system behaviour |
| Repo setup, tooling config, dependency bumps | Plumbing |
| Individual commits, refactors, lint fixes | Below the reporting threshold |
| Process/tracking changes (including this file) | Meta-work |

**Test:** if a competent engineer joining the project would not need to know it to understand what
the system does today, it is not a bullet.

*Exception:* if housekeeping changed real behaviour, report the behaviour change, not the cleanup.
"n8n now holds no third-party credentials, so SMS compliance cannot be bypassed" is a bullet;
"removed Slack nodes" is not.

## Tone

**Assume the reader is smart but not technical.** No code, no field names, no library names, no
internal jargon. Explain what the thing does and why it was hard — the difficulty is usually the
interesting part, and it survives translation.

Three ways a bullet goes wrong:

| Too vague | Too technical | Right |
|---|---|---|
| "improved the diffing logic" | "compares `remote` against `deepMerge(remote, local)` so materialised server defaults are excluded" | "can now tell whether what's running matches what we intended — Vapi silently adds dozens of its own defaults, which made the obvious version of this check useless" |
| "fixed schema issues" | "Vapi rejects `anyOf`, emitted by a constrained `.nullable()`" | "two settings Vapi rejects outright used to fail mid-deployment; they now fail instantly with an explanation" |
| "added idempotency" | "idempotency keyed on `callId:toolCallId`" | "if the same request arrives twice, it is only acted on once — so a stutter cannot double-book someone" |

Rules of thumb:

- **Lead with what it means, not how it works.** Mechanism second, in plain words.
- **Keep the numbers.** How many tools, rules, tests, problems fixed. Numbers survive translation
  and make the entry checkable.
- **Give the symptom for bugs.** "Grace said 'Monday the third' for a Tuesday" beats "timezone bug"
  for every reader, technical or not.
- **No backticks, no file paths, no API names** unless the name is the point (a platform name like
  Vapi or n8n is fine).

## Honesty rules

The point of the log is that it can be trusted.

1. **"Deployed" and "verified working" are different words.** Use the accurate one.
2. **The ⚠️ line is mandatory**, including on good days. If everything landed, name the next risk.
3. **Report self-inflicted bugs and reversals** as plainly as wins.
4. If a claim is not backed by evidence in [00-STATUS.md](00-STATUS.md), soften it or cut it.

## Wrap-up checklist

1. Read the day's commits — raw material, not the output.
2. Discard everything in the exclusion table.
3. Pick the 6 with the largest effect on what the system can do.
4. For each, state the mechanism and one concrete number or symptom.
5. Write ⚠️ from [06-pending-and-blocked.md](06-pending-and-blocked.md).
6. Refresh **Last updated** in [00-STATUS.md](00-STATUS.md); commit as `docs: daily log <date>`.
