# 01 — Documentation Corrections

**Completed:** 3 August 2026 · **Commit:** `34e3f4d`
**Files:** `Docs/plans/08`, `09` (rewritten), `18` (new), `19` (new), `01`/`03`/`04`/`17` (surgical)

---

## Why this was necessary

Docs 08 and 09 were written from convention and from Vapi/n8n prose documentation, not
from the APIs themselves. Verifying them against `api.vapi.ai/api-json` and a live probe of
the n8n Cloud instance found configuration that **does not work** — not style problems.

Building from them as written would have produced an assistant that appeared to deploy
and then silently failed in ways nobody would notice for weeks.

---

## Doc 08 — Vapi layer (16 corrections)

The four that would have caused real, hard-to-diagnose damage:

### 1. The end-of-call report was silently disabled

`"serverMessages": ["tool-calls"]`. Setting this field **replaces** the default list rather
than extending it, so the assistant unsubscribed from `end-of-call-report`. Nothing errors —
the reports simply never arrive, taking the call-summary, QA and redaction pipeline with them.

### 2. `analysisPlan` is deprecated in its entirety

Every property of `AnalysisPlan` carries `deprecated` in the spec — including the nested
`summaryPlan` / `structuredDataPlan` that an interim draft of the fix recommended migrating to.
Both shapes in circulation are dead ends. The live mechanism is the first-class
**StructuredOutput** resource referenced from `artifactPlan.structuredOutputIds`.

### 3. `transferToHuman` could not transfer a call

It was specified as a `function` tool. A function tool returns a string the model reads aloud.
Transferring requires `type: "transferCall"` — and `CreateTransferCallToolDTO` has **no
`function` property**, so it accepts no arguments at all. The `transfer-destination-request`
webhook carries none either.

**Consequence:** a companion `flagEscalation` tool is not a nicety, it is the only path by
which whisper context and the `staff_tasks` row can exist. The catalogue became 14, then 15.

### 4. `server.secret` does not exist

The `Server` schema is `{ url, headers, credentialId, timeoutSeconds, backoffPlan,
staticIpAddressesEnabled, encryptedPaths }`. Auth is a dashboard-created Custom Credential.

### The rest

| # | Correction |
|---|---|
| 5 | `escalationReason` free text → closed enum (LLM-authored free text summarising a transcript is a PHI route into a persisted column, I6) |
| 6 | Test Suites deprecated **and** needs a phone number → Simulations, three tiers |
| 7 | Drift diff `local` vs `remote` → `remote` vs `merge(remote, local)`, or AC-08.1 never converges |
| 8 | Greeting was inlined in `grace.json` while CI protected only `first-message.txt` |
| 9 | "Vapi retries with the same `toolCallId`" — it does not retry at all by default |
| 10 | Async tools acked via `result`, which never reaches the model → `request-start` |
| 11 | Per-tool p95 budgets raced as hard deadlines → fires the fallback on ~5% of healthy calls |
| 12–15 | `silenceTimeoutSeconds`, `backchannelingEnabled`, `endCallFunctionEnabled` not in the API; `backgroundDenoisingEnabled` renamed |
| 16 | us-west-2 citation pointed at the n8n section, not core-api |

---

## Doc 09 — n8n layer (16 corrections)

### 1. The credential scheme deployed green and threw at runtime

`{ id: "<name>", name: "<name>" }`. n8n resolves credentials **strictly by id, with no name
fallback** (`credentials-helper.ts` → `CredentialNotFoundError`). Such a workflow `PUT`s 200,
activates happily, and throws on its **first execution** — and the old verification step
compared JSON only, so it would never have caught it. The single worst defect in either doc.

### 2. `/publish` does not exist on this instance

The plan said to use `POST /workflows/{id}/publish` and called `/activate` deprecated. On
`palmleafmassage.app.n8n.cloud` it is the opposite: `/publish` is absent, `/activate` works.
Hard-coding either guarantees a break, since Cloud auto-updates.

### 3. Nothing triggered the main workflow

WF-12's trigger was specified three incompatible ways across the doc set, while two other docs
forbade Core API from calling n8n at all. Resolved to `staff.notify` → outbox → sync-worker →
HMAC-signed webhook, and the missing `GRACE_N8N_WEBHOOK_SECRET` was defined.

### 4. The webhook held the connection open for 15 minutes

Respond-to-Webhook came *after* a `Wait 15 min` node. The ACK belongs immediately after
validation; everything downstream is fire-and-forget.

### The rest

`active` is read-only on `PUT`; normalisation stripped `webhookId` (which silently changes the
production webhook URL); the "daily digest store" was defined nowhere; the error workflow was
required but never created (now WF-00); WF-18 had two competing timers; staff SMS bypassed the
messaging adapter's 10DLC enforcement; WF-14 needs two Slack surfaces, not one; the
move-to-code arithmetic was wrong in two documents; crons said "CT" (ambiguous); multi-tenancy
breaks at tenant two.

---

## Cross-document changes

| Doc | Change |
|---|---|
| **01** | **ADR-0013** — one n8n Cloud instance, I9 relaxed to "CI is the only publisher", with the residual risks stated plainly rather than glossed. ADR-0002's stale text corrected. Deadline vs p95 separated. |
| **03** | `staff_tasks.acknowledged_at` (WF-18 was unanswerable without it); the two unique indexes doc 07 already assumed; priority 1–5 semantics and the `"P1"`→smallint mapping; `staff_task_type` became an enum |
| **04** | §6.1 rewritten around `credentialId`; the authoritative `/internal/*` route table; `:type` vs `:id` collision resolved; deadline separated from budget with two distinct metrics |
| **17** | A-02 largely discharged, A-04 downgraded to config, **A-13…A-21** added, D-7 arithmetic fixed, D-8 added |
| **18** | **New** — the account setup runbook that had no home |
| **19** | **New** — the execution plan, kept corrected as findings landed |

---

## What is deliberately NOT corrected

- Docs 02, 05, 06, 07, 10–16 are untouched except where a Vapi/n8n contract crossed into them.
  They describe Core API, adapters and the write path, none of which is in this phase.
- Doc 06 §6.1's retry claim is flagged in doc 08 §4.1 but **not yet edited in place**.
- Doc 12 still has no "n8n is down" alert. Flagged in doc 09 §3.2; not added.
- Doc 02 §50 still says `/internal/*` is "mTLS/token-gated". mTLS appears nowhere else and is
  not implemented. Flagged in doc 04, not resolved.
