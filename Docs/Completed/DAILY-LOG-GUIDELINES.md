# Daily Log — Generation Guidelines

How to write the end-of-day entry in [DAILY-LOG.md](DAILY-LOG.md). Run this when wrapping up.

**The log records engineering output** — features built, systems deployed, technical problems
solved — **written so a non-technical reader can follow it.**

Both halves matter. Technical substance with no plain explanation is unreadable to the people who
need the status. Plain explanation with no substance is not worth writing.

---

## Format

**One flat bullet list per day. Shortest possible, and ideally around 6 bullets.** Under the
`## <D Month YYYY>` heading, put the bullets directly, then the ⚠️ line. No `### New features`
sub-heading, no second `### What changed` section — one date, one flat list. Bullet lists only,
never tables.

**Start every bullet with a past-tense verb, no bold lead.** *Wired…, Built…, Fixed…, Redeployed…,
Profiled…, Surfaced…, Restored…* — the achievement, then the technical substance and the number that
makes it concrete (19 migrations, 15 tools, ~390 ms, LIMIT 200). Name the real thing — FastAPI,
PostgreSQL, Alembic, Cloudflare tunnel, `/webhooks/vapi/events` — a notch more technical than plain
English, because the reader following this log is technical.

Rules:

- **Max 2 sentences per bullet. Hard cap**, and one is usually enough. If it needs a third, the
  detail belongs in [DAILY-LOG-TECHNICAL.md](DAILY-LOG-TECHNICAL.md).
- **A bug found *is* a bullet.** Fold problems into the list as achievements — *"Surfaced 3 real
  defects through a live call: …"* — with the concrete cause in parentheses. Do not hide them.
- **Merge before you multiply.** Related pieces (a receiver *and* the box it runs on; an engine *and*
  the guard that protects it) go in one bullet, not several. Cut anything minor rather than pad.
- **One ⚠️ line at the end** listing what is unproven or broken. Never omit it. Same 2-sentence cap.
- Newest entry on top, under a `## <D Month YYYY>` heading.
- **Date by evidence, not by when you happened to write it.** Check [00-STATUS.md](00-STATUS.md)'s
  dated rows and any source file that carries its own timestamp (a snapshot README's findings
  section, a commit date) before filing a bullet under a day. A single writing session often covers
  work that actually happened across two calendar days — split it into two entries. Never bundle the
  later day's findings under the earlier heading just because they were drafted together.

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

**Technical, and understandable by a non-technical reader. Both, in the same sentence.** The reader
is smart and pays attention but does not write code. Name the real thing — TypeScript, Python,
Postgres, Vapi, n8n — then say what it does in the same breath, so the name teaches rather than
excludes.

That is the whole trick: *"Python's schema tools use developer comments as public descriptions"*
is technical **and** readable. It names the real mechanism and needs no glossary.

Three ways a bullet goes wrong:

| Too vague | Too technical | Right |
|---|---|---|
| "improved the diffing logic" | "compares `remote` against `deepMerge(remote, local)` so materialised server defaults are excluded" | "we can now tell whether what's running matches what we intended — Vapi silently fills in dozens of its own defaults, which made the obvious version of this check useless" |
| "fixed schema issues" | "Vapi rejects `anyOf`, emitted by a constrained `.nullable()`" | "two settings Vapi rejects outright used to fail halfway through a deployment; they now fail instantly, with an explanation" |
| "added idempotency" | "idempotency keyed on `callId:toolCallId`" | "if the same request arrives twice we only act on it once, so a stutter on the line cannot double-book someone" |

Rules of thumb:

- **Lead with what it means, mechanism second** — but do include the mechanism. A bullet with no
  mechanism is a status update, not a log entry.
- **Keep the numbers.** How many tools, rules, tests, lines, problems fixed. Numbers survive
  translation and make the entry checkable.
- **Give the symptom for bugs.** "Grace said 'Monday the third' for a Tuesday" beats "timezone bug"
  for every reader, technical or not.
- **No code, no file paths, no field or function names.** Product and technology names are
  encouraged; identifiers from the source are not. Those belong in the technical log.

## Reference bar

Not from this project — kept here so the target bullet quality never needs re-explaining. This is
what a day's bullets should read like: verb-first, technical, self-contained, specifics in
parentheses.

> - Scaffolded the full backend architecture — FastAPI + arq worker processes, PostgreSQL models,
>   Alembic migrations, REST routers.
> - Built a dual-engine scraping foundation on Crawlee (HTTP-impersonation + real browser
>   automation), fixing a bug where repeated scrapes silently returned empty.
> - Built the end-to-end pipeline: YouTube video → search query → SearXNG search → TikTok candidates
>   found → all hydrated with real data.
> - Stood up supporting infrastructure — MinIO object storage and a self-hosted SearXNG search
>   engine, both running via Docker.
> - Found and fixed 3 real bugs through live testing against actual TikTok/YouTube data (a
>   URL-cleanup bug breaking oEmbed, a fake unusable video-link bug, and a mismatched test assumption).

What makes it work: **every bullet opens with a past-tense verb** and earns its place with a concrete
mechanism or count, never a vague adjective. No bold lead, no hedging, no "should" or "we tried to" —
state what was done. Problems found are listed as achievements (*"Found and fixed 3 real bugs…"*),
with the cause named in parentheses.

**The one deliberate difference here:** name *this* project's real technology (Vapi, n8n, PostgreSQL,
RingCentral, Cloudflare tunnel) where the example names its own — a proper noun teaches more than a
generic phrase to a technical reader.

## Honesty rules

The point of the log is that it can be trusted.

1. **"Deployed" and "verified working" are different words.** Use the accurate one.
2. **The ⚠️ line is mandatory**, including on good days. If everything landed, name the next risk.
3. **Report self-inflicted bugs and reversals** as plainly as wins.
4. If a claim is not backed by evidence in [00-STATUS.md](00-STATUS.md), soften it or cut it.

## Wrap-up checklist

1. Read the day's commits and `git diff` against the last commit — raw material, not the output.
   Uncommitted work is still today's material; do not wait for a commit to exist before logging it.
2. Confirm the actual date of each item against [00-STATUS.md](00-STATUS.md)'s dated rows or a
   source file's own timestamp, and split across `## <date>` headings accordingly — see the dating
   rule under Format.
3. Discard everything in the exclusion table.
4. Keep only the items with real effect on what the system can do, per day; merge related ones and
   cut the minor — the list should be as short as it can be without dropping something major.
5. For each, state the mechanism and one concrete number or symptom, in at most two sentences.
6. Write ⚠️ from [05-pending-and-blocked.md](05-pending-and-blocked.md), or from what is still open
   in [00-STATUS.md](00-STATUS.md) if that file does not exist yet.
7. Refresh **Last updated** in [00-STATUS.md](00-STATUS.md); commit as `docs: daily log <date>`.
