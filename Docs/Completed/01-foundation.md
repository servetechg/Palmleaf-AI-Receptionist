# 01 — Foundation: contracts, tooling, CI, and the documentation audit

**Completed:** 3 August 2026 · **Ported to Python:** 4 August 2026
**Commits:** `34e3f4d`, `e8db9cd`, `298c9fc`, `cf71434`

Three things that are really one piece of work: auditing the plans against the real APIs,
building the schema/tooling layer that came out of that audit, and the CI that keeps both
honest.

---

## Part A — The documentation audit


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


---

## Part B — Contracts, tooling and CI


## `packages/contracts`

**13 function-tool schemas**, each with an input and output zod schema, plus a registry that
is the single source everything else derives from.

| File | Contents |
|---|---|
| `tools/_shared.ts` | `LocalDate`, `Instant`, `PublicSlotId`, `BookingRef`, `PhoneE164`, `TimePreference`, `EscalationReason`, `Urgency`, `ToolAck` |
| `tools/read-tools.ts` | 1–4: `getBusinessInfo`, `lookupCustomer`, `getServicesAndPricing`, `checkAvailability` |
| `tools/write-tools.ts` | 5–7: `createBooking`, `rescheduleAppointment`, `cancelAppointment` |
| `tools/messaging-tools.ts` | 8–10: `sendIntakeForm`, `sendDepositLink`, `sendBookingConfirmation` |
| `tools/escalation-tools.ts` | 12–14: `takeMessage`, `flagMedicalHold`, `flagEscalation` |
| `tools/registry.ts` | `TOOL_REGISTRY` — name, description, schemas, budget, async, write |
| `vapi/envelope.ts` | The Vapi ⇄ Core API wire contract |

`transferToHuman` (11) and `endCall` (15) are absent by design: they are Vapi tool *types*
with no parameters and therefore no zod source.

### Conventions enforced

- **`.strict()` on every input.** An invented parameter is a loud validation error, never a
  silently ignored field. Verified live: the mock server rejects `{urgency:"high"}` on
  `checkAvailability` with a spoken retry.
- **`.describe()` on every field.** That text is what the model reads when deciding how to
  fill a parameter — prompt engineering, not documentation.
- **Never `.nullable()` on an input.** A constrained nullable renders as `anyOf`, which Vapi
  rejects. `.optional()` is also the better affordance: the model omits rather than reasoning
  about explicit null. Enforced statically by `generate-tools.ts`.
- **Never `z.literal()` on an input.** It renders as a scalar `const`, which Vapi rejects.
  Enforce the value in the handler instead — which is where I4 wants it anyway.

### The registry as single source

`TOOL_REGISTRY` drives three things that would otherwise drift:

1. `platform/vapi/tools/*.json` via `generate-tools.ts`
2. The `## TOOLS` table in the system prompt via `build-prompt.ts`
3. The mock server's dispatch and validation (and Core API's router, later)

Adding a tool is one registry row. Nothing else is hand-maintained.

---

## CI — the T1 static gate

`.github/workflows/ci.yml`. Target under 90 seconds, zero cost, no Vapi calls.

| Step | Catches |
|---|---|
| `typecheck` | type errors across all 4 packages |
| `lint` | style + the architecture boundary rules |
| `test` | 14 speech-formatter unit tests |
| I7 greps | missing recording/AI disclosure, **and** an inlined `firstMessage` |
| `vapi:generate --check` | generated tool JSON out of date vs the registry |
| `vapi:prompt --check` | `system.md` out of date vs `sections/` |
| `vapi:validate --refresh` | any `grace.json` key not in the **live** `CreateAssistantDTO`, or deprecated |
| `n8n:lint` | 15 structural workflow rules |
| secret scan | `sk_live_`, `whsec_`, `xoxb-`, Twilio SIDs |

A separate `drift` job runs the Vapi diff on pushes.

**`vapi:validate --refresh` is the highest-value step.** It is what found four dead assistant
fields, and it re-checks against current reality on every run — so if Vapi deprecates
something we use, CI tells us rather than a caller discovering it.

### A bug this work found in itself

`pnpm -r run test` **silently skips packages with no test script**. CI would have reported
green having run zero tests. The root `test` script now invokes vitest directly.

---

## Part C — The Python port (4 August 2026)

**Commit:** `cf71434` · **Decision:** ADR-0014, superseding ADR-0001's language choice.

### Why

TypeScript was chosen in ADR-0001 before the client was involved, and Python was dismissed in
one line — *"better ML ecosystem, irrelevant here — no model training"* — which is not an
argument against Python for an API service. ADR-0001's own exit criteria named the condition
that had now been met.

The strongest technical argument for TypeScript was generating tool definitions, the prompt
table and runtime validation from one schema source so they cannot drift. **Pydantic does this
identically** via `model_json_schema()`. Parity, not an advantage. What decided it was what the
team can maintain.

### What moved

| Was | Now |
|---|---|
| `packages/contracts` (zod) | `src/grace_contracts` (Pydantic v2) |
| `platform/*/**.ts` | `src/grace_platform/**` |
| pnpm + tsc + eslint + vitest | uv + mypy strict + ruff + pytest |
| `pnpm check` | `make check` |

The browser web-call harness stayed in JavaScript because it runs in a browser. n8n Code nodes
stayed JavaScript because n8n runs them.

### Verified at the boundary

The Python implementation was pointed at the **same live resources** the TypeScript one had
deployed — not a fresh environment:

- Vapi: `apply` then `diff` → **zero drift** on assistant `51fd2d26`
- n8n: **zero drift** on all three workflows
- the linter catches the same five injected defects
- the mock server returns byte-identical spoken output
- all 14 speech tests pass unchanged

### Four defects the port surfaced

Three are Pydantic-specific traps that did not exist in TypeScript:

1. **Class docstrings became model-facing text.** Pydantic uses a class docstring as the schema
   `description`, so internal implementation notes were being sent to Grace as instructions.
   The generator strips them; the validator fails if any reappear.
2. **Enums were hoisted into `$defs` and referenced.** Vapi has no `$ref` resolver, so this
   would have been a deploy-time 400. The generator inlines them.
3. **Python distinguishes `1` from `1.0`; JSON does not.** Vapi echoes `1`, our config said
   `1.0`, and the drift check went permanently red on the very first run. Integral floats are
   collapsed before comparison.

The fourth was **latent in both implementations** and only surfaced under review:

4. **The n8n credential `name` field was being overwritten with the credential id.** n8n rewrites
   it back on save, so every diff reported a change that could never clear. This was previously
   mis-recorded as a missing normalisation step affecting one workflow; it was a real bug
   affecting all three. Fixed — all three now converge.

### Not changed by the port

No live call has been placed, no workflow has executed, and `export.py` is still unwritten.
Porting the implementation does not move any of those forward.
