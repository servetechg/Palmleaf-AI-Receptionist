# 04 — Mock Tool Server, Web Harness and Tests

**Completed:** 3 August 2026 · **Commit:** `298c9fc`

---

## Why this exists

Core API does not exist. Without a stand-in, every tool returns nothing on a web call, Grace
says "I'm having trouble" on every turn, and **none** of the prompt, grounding rule, medical
gate, PCI refusal, endpointing, filler timing or generated schemas can be validated. That is
the entire value of a platform-only phase.

It is also not throwaway: when Core API lands it becomes the contract-test double that proves
both implementations agree on all 13 envelopes.

---

## What it does

`platform/vapi/mock-server/` — `node:http`, no framework. Same two routes as Core API
(`POST /vapi/tools`, `POST /webhooks/vapi/events`), same envelope, so the switch is one env var.

Its real job is **validating every tool call against the real zod schemas from
`@grace/contracts`** — which is what proves the JSON Schema published to Vapi and the schema
our handlers expect actually agree, under a live model, before Core API exists.

| Capability | Detail |
|---|---|
| Schema validation | real zod; rejects with a spoken retry and a loud console error, never a 500 |
| Spoken formatters | `speech.ts` — times, dates, prices, ≤3-item lists |
| Deterministic clock | `GRACE_MOCK_NOW` freezes "now" so dates are reproducible |
| Fault injection | `GRACE_MOCK_LATENCY_MS`, `_FAIL=<tool>`, `_TIMEOUT=<tool>` |
| Idempotency | in-memory map keyed `${callId}:${toolCallId}`; replays the stored response |
| Whisper priming | captures `flagEscalation.summary`, serves it on `transfer-destination-request` (60s TTL) |
| Medical gate | refuses to book when `medicalScreenPassed` is false — server-side, not prompt-only (I4) |

---

## Verified behaviour

Live against the running server:

```
checkAvailability  →  "I have five fifteen with Maria, six thirty with James, or seven
                       fifteen with Maria on Tuesday the fourth. Which works?"

getServicesAndPricing (isMember)
                   →  "We have the 60-minute massage at one fifteen or the 90-minute
                       massage at one sixty."

createBooking (medicalScreenPassed: false)
                   →  "Before I book, I'd like one of our team to go over a couple of
                       health questions with you."

checkAvailability + {urgency:"high"}   ← invented parameter
                   →  "Sorry, I didn't catch that properly — could you say it again?"
                      SCHEMA ✗ checkAvailability — (root): Unrecognized key(s): 'urgency'

createBooking × 2, same toolCallId
                   →  identical response both times
                      IDEMPOT createBooking replayed for c9:tSAME
```

That covers: spoken number formatting, member pricing, `.strict()` enforcement, the
server-side medical gate, and idempotent replay.

---

## Three formatter bugs the mock server found

All three would have been audible on a real call. All three are now locked by tests.

### 1. Off-by-one day — Grace said "Monday the third" for a Tuesday

`new Date('2026-08-04')` parses as **UTC midnight**, which renders as the *previous day* in
America/Chicago. A bare `YYYY-MM-DD` from the model means a Chicago calendar date, not UTC.
Fixed with `chicagoDate()`, which measures the zone's actual offset on that date so CST/CDT
is handled without hardcoding.

### 2. `speakPrice` could not say teens

11500 came out **"one 10-five"** instead of "one fifteen" — the tens table had no entry
below 20. Rewritten with a proper 0–999 word conversion.

### 3. Times and prices hyphenated inconsistently

"five forty five" alongside "one thirty-five" in the same sentence. Unified.

---

## Tests

`speech.test.ts` — 14 tests, all passing. Cases are things a caller would actually hear:

- hour alone on the hour; "oh" for single-digit minutes; noon/midnight as twelve not zero
- bare `YYYY-MM-DD` as a Chicago date (the regression above)
- irregular ordinals — first, second, third, fifth, ninth, twelfth, twentieth, twenty-first, thirty-first
- prices: "one thirty-five", "one fifteen" (regression), "ninety-nine", "one oh five", "two hundred"
- `speakList` never reads more than three options aloud

---

## Web harness

`platform/vapi/web-harness/` — the only channel that can talk to Grace this phase.

- `@vapi-ai/web` 2.6.1 via esm.sh; live transcript, tool-call log, error surface
- `serve.ts` serves it over http (the SDK needs a real origin, not `file://`) and generates
  `harness-config.js` from `.lock.json` + `VAPI_PUBLIC_KEY`, so the assistant id is never
  hand-copied and the public key is never committed
- Refuses to run against anything but `env: dev`

Web calls use the exact stored assistant config, so this is a faithful test of the prompt,
the grounding rule, the medical gate, the PCI refusal and endpointing — **except transfer**,
which is reportedly unsupported on web calls (A-14).

---

## Not done in this area

- **The harness has never been run against a live call** — needs a tunnel. This is the single
  biggest untested gap; see `06-pending-and-blocked.md`.
- No tests for `fixtures.ts` itself, only for `speech.ts`
- No contract test asserting mock and Core API agree (Core API does not exist)
- `GRACE_MOCK_TIMEOUT` sleeps 60s rather than modelling the real deadline middleware
