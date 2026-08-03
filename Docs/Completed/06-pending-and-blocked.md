# 06 — Pending and Blocked

**Last updated:** 3 August 2026

> Everything the other files in this folder do **not** claim. If a capability is not listed as
> verified in `00-STATUS.md`, it is here or it does not exist yet.

---

## The honest headline

**Grace has never taken a call.** Every layer is built, deployed and independently verified —
but the assistant currently points at `placeholder.invalid`, so on a real call every tool
would fail and Grace would say "I'm having trouble" on every turn.

Everything below flows from that.

---

## 1. Blocked on a tunnel — the one thing standing between here and a working call

The mock server needs a public HTTPS URL for Vapi to reach it. That requires a tunnel process
running for the duration of a test, which cannot be left running unattended.

```bash
# terminal 1
pnpm platform:vapi:mock

# terminal 2 — copy the https URL it prints
cloudflared tunnel --url http://localhost:4242
#   or: ngrok http 4242
#   NOT `vapi listen` — that is a local forwarder, not a public tunnel

# terminal 3 — point the assistant at the tunnel
GRACE_TOOLS_URL=https://<tunnel>/vapi/tools \
GRACE_EVENTS_URL=https://<tunnel>/webhooks/vapi/events \
  pnpm platform:vapi:deploy --env dev --apply

pnpm platform:vapi:harness      # then open http://localhost:4243
```

**What that unlocks, all currently unverified:**

| Check | Criterion |
|---|---|
| Grace opens with the recording disclosure | I7, end to end |
| A booking completes: service → availability → screening → book | — |
| The medical gate fires on a "yes" and blocks the booking | AC-08.7 |
| Grace refuses a spoken card number | AC-08.6 |
| Times sound like "two fifteen", prices like "one thirty-five" | doc 04 §5.2 |
| `request-start` fillers actually cover tool latency | doc 08 §11.1 |
| **`end-of-call-report` arrives with populated `structuredData`** | **AC-08.9** — the direct regression test for the worst doc defect |
| `GRACE_MOCK_FAIL=checkAvailability` → graceful fallback, no invented availability | — |

AC-08.9 is the important one. It is the only thing that proves the `serverMessages` correction
actually works in practice rather than only on paper.

---

## 2. Not built at all

| Item | Notes |
|---|---|
| **Vapi Simulations** (T2 chat, T3 voice) | `simulations/` is empty. The three-tier strategy is designed (doc 08 §9) but no scenario is authored. T1 is the only tier running. |
| **`platform/n8n/export.ts`** | Stub. AC-09.2 unverified — we cannot yet round-trip a dashboard edit back into git. |
| **6 n8n workflows** | WF-07 reconciliation report, WF-11 hourly digest, WF-15 daily digest, WF-16 QA sampler, WF-17 Vagaro fan-out. |
| **WF-14 staff actions** | Deferred with Slack — it is entirely Slack interactivity + the `/grace-kill` slash command. |
| **Hourly drift cron** | Designed (doc 08 §8.1, ADR-0013). CI has a push-triggered drift job but no schedule — and the hourly job is what actually catches a dashboard edit. |
| **Core API** | Out of scope. Resumes from doc 15. |

---

## 3. Built but unverified

| Item | Why it is unproven |
|---|---|
| The whole n8n runtime path | WF-12 has never received a signed request. AC-09.4, 09.5, 09.7, 09.10 all unverified. |
| `/internal/notify/{staff,ops,sms}` | The workflows call these. **They do not exist.** Every notification currently 404s. |
| WF-18 deploy idempotency | Re-reports drift on every `--apply` — n8n materialises node defaults and the comparison is not normalised. Converges, but does redundant writes. |
| Transfer path | Cannot be tested on web calls (A-14). Needs a phone number. |
| Prod environment | Nothing deployed to `env:prod`; the tag does not exist. |

---

## 4. Configuration gaps

| Gap | Impact | Where |
|---|---|---|
| **Vapi HMAC webhook credential not created** | Webhooks are unauthenticated. A-13 undischarged. | doc 18 §1.2 |
| **Vapi concurrency still at the default 10** | Target is 25 sustained / 50 burst. Billing action with lead time. | doc 18 §1.3 |
| `GRACE_N8N_WEBHOOK_SECRET` not set on the instance | WF-12's signature check would fail | doc 09 §2.1 |
| Core API credential holds a **placeholder token** | Rotate when Core API exists | `MLPOdQtg1zcSlYUJ` |
| Vapi credentials were exposed in a session transcript | User declined rotation; recorded as accepted risk | — |

---

## 5. Client gates still open

Unchanged by this work — these need PalmLeaf, not engineering.

| Gate | Blocks |
|---|---|
| **GATE-05** greeting wording + provider roster | production launch. Current greeting is the architect's recommendation. |
| **GATE-02** cancellation policy wording | Grace quoting a cancellation fee |
| **GATE-04** full service catalogue | Grace quoting any price. Mock data is invented. |
| **GATE-09** A2P 10DLC | production SMS volume |
| **GATE-11** RingCentral | any phone number at all, and therefore the transfer path |

Also: `voiceId: "sarah"` is a placeholder, not a client-approved voice.

---

## 6. Known issues in code

| Issue | Severity | Location |
|---|---|---|
| WF-18 drift on every apply | low — redundant writes only | `platform/n8n/deploy.ts` |
| `GRACE_MOCK_TIMEOUT` sleeps 60s rather than modelling the deadline middleware | low | `mock-server/server.ts` |
| No tests for `fixtures.ts` | medium — only `speech.ts` is covered | — |
| Doc 06 §6.1's false retry claim flagged but not edited in place | low | `Docs/plans/06` |
| Doc 12 has no "n8n is down" alert | **medium** — if n8n dies, every P1 escalation disappears silently | `Docs/plans/12` |
| Doc 02 §50 still says `/internal/*` is mTLS-gated; it is bearer only | low | `Docs/plans/02` |

---

## Suggested next order

1. **Tunnel + web call.** Highest value by a wide margin — it converts eight unverified
   behaviours into verified ones and proves AC-08.9.
2. **T2 chat simulations.** Cheap, deterministic via `toolMocks`, and gates prompt changes
   so the prompt cannot silently regress.
3. **`export.ts`** — closes the config-as-code loop; without it a dashboard edit cannot come back.
4. **Normalise the n8n drift comparison** — makes deploy genuinely idempotent.
5. **Remaining workflows**, once `/internal/*` exists to give them something to call.
