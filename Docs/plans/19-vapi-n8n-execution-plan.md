# Vapi + n8n Layers — Doc Correction and Platform Implementation

## Context

Access to Vagaro, RingCentral, Stripe and Google is limited, but we have full access to **Vapi** and **n8n Cloud**. Those two are the core of the product; the rest are integrations. So we pivot to building them now.

The repo is **docs-only** — 20 markdown files, zero code. Before writing any code, the two governing documents were verified against the live Vapi and n8n APIs. **They contain config that does not work.** Not style issues — fields that no longer exist, a subscription list that silently disables half the system, and a credential scheme that deploys green and then throws at runtime. Building from them as written produces a broken assistant.

This plan does three things: connect MCP, correct the docs against verified API reality, then implement the platform layers.

**Scope decisions (already made, not revisiting):**
- Build **platform layers only** — `packages/contracts` + `platform/vapi/` + `platform/n8n/`. No Core API, no Postgres, no workers.
- **Web/test calls only.** No phone number. RingCentral BYO-SIP stays blocked.
- **One n8n Cloud instance** (pay-as-you-go), dev/prod separated by tags + name prefix. Invariant I9 is deliberately relaxed and needs an ADR.
- Docs: rewrite `08` and `09`, add `18-platform-setup.md`, surgical fixes to `01`/`03`/`04`/`17`.

---

## Step 0 — Connect MCP (YOU do this before anything else)

Nothing else in this plan starts until `/mcp` shows three connected servers. Follow these steps in order.

### 0.1 — Get your Vapi private API key

1. Go to **https://dashboard.vapi.ai**
2. Left sidebar → **Organization Settings** → **API Keys** (on some accounts it is just **API Keys**)
3. Copy the **Private Key**. It is the one that starts with a UUID-looking string, *not* the Public Key.
   - The **Public Key** is a different value — you will need it later in Step B4 for the web-call harness, so copy that too and keep it somewhere separate.
4. ⚠️ The private key has full org access. Do not paste it into a file that git tracks.

### 0.2 — Turn on instance-level MCP in n8n Cloud and get the token

1. Log in to your n8n Cloud instance (`https://<your-name>.app.n8n.cloud`)
2. Bottom-left → **Settings**
3. Look for **Instance-level MCP** (may appear as **MCP Server**). Requires n8n **v2.2.0+** — Cloud is current, so it will be there.
4. Toggle it **on**
5. Click **Create MCP Access Token** (or **Generate token**)
6. **Copy the token immediately — it is shown exactly once.** If you lose it, revoke and regenerate.
7. **On that same page, copy the MCP server URL it displays.** Do not guess this URL or construct it by hand — n8n prints the exact one for your instance. It looks roughly like `https://<your-name>.app.n8n.cloud/mcp-server/...`, but use whatever is shown verbatim.

### 0.3 — Get your n8n public API key (separate from the MCP token)

The MCP token is for agent authoring. The public API key is what `platform/n8n/deploy.ts` will use later in CI. Get it now while you are in Settings:

1. **Settings** → **n8n API**
2. **Create an API key** → give it a label (`grace-ci`) and an expiration
3. Copy it. Header name is `X-N8N-API-KEY`.
4. ⚠️ On Starter/Pro this key has **full access to every workflow, credential and execution** — scopes are Enterprise-only. Treat it like a root password.

### 0.4 — Export the environment variables

Add these to `~/.bashrc` (so they persist across terminals), replacing the placeholder values:

```bash
# --- PalmLeaf Grace: Vapi ---
export VAPI_API_KEY='paste-your-vapi-private-key'
export VAPI_PUBLIC_KEY='paste-your-vapi-public-key'

# --- PalmLeaf Grace: n8n Cloud ---
export N8N_API_URL='https://your-name.app.n8n.cloud'
export N8N_MCP_URL='paste-the-exact-url-from-step-0.2'
export N8N_MCP_TOKEN='paste-your-mcp-access-token'
export N8N_API_KEY='paste-your-n8n-public-api-key'
```

Then load them:

```bash
source ~/.bashrc
```

Verify all five are set (this prints only lengths, never the values):

```bash
for v in VAPI_API_KEY VAPI_PUBLIC_KEY N8N_API_URL N8N_MCP_URL N8N_MCP_TOKEN N8N_API_KEY; do
  printf '%-16s %s\n' "$v" "$([ -n "${!v}" ] && echo "set (${#v} chars)" || echo 'MISSING')"
done
```

Every line must say `set`. If any says `MISSING`, fix it before continuing.

### 0.5 — Restart Claude Code

**This is the step people skip.** Claude Code reads environment variables at launch. Variables exported after launch are invisible to it, and MCP servers are loaded at startup.

Fully quit Claude Code (close the VSCode extension session / exit the CLI) and start it again from a terminal where `source ~/.bashrc` has run.

### 0.6 — What I do once you confirm

I create `.mcp.json` in the project root using `${VAR}` expansion, so **no secret is ever written to disk or into this transcript**:

| Server | Endpoint | Auth |
|---|---|---|
| `vapi` | `https://mcp.vapi.ai/mcp` (streamable HTTP) | `Authorization: Bearer ${VAPI_API_KEY}` |
| `vapi-docs` | `https://docs.vapi.ai/_mcp/server` | none — public docs server |
| `n8n` | `${N8N_MCP_URL}` | `Authorization: Bearer ${N8N_MCP_TOKEN}` |

I also add `.mcp.json` to `.gitignore` and commit a `.mcp.json.example` with placeholders, per [09-n8n-layer.md:190](Docs/plans/09-n8n-layer.md#L190).

Then **you restart Claude Code once more** (new `.mcp.json` = another startup read).

### 0.7 — Verify the connection

Run `/mcp`. You should see three servers listed as **connected**. Then I confirm each is actually usable:

- `vapi` → call `list_assistants` (expect an empty list on a fresh org — that is success, not failure)
- `vapi-docs` → a docs search returns results
- `n8n` → call `search_workflows` (expect empty or your existing workflows)

If a server shows **failed**, the cause is almost always one of: env var not exported before launch, Claude Code not restarted, or a token copied with trailing whitespace.

### 0.8 — Two facts from this that shape the whole design

⚠️ The **Vapi** MCP server has **no** `update_assistant` and **no** `create_tool`/`update_tool`. It physically cannot mutate existing config — which independently strengthens ADR-0010's config-as-code position.

⚠️ The **n8n** MCP server **does** expose `publish_workflow`, and its `search_workflows` sees every workflow regardless of the per-workflow "Available in MCP" opt-in. On a single Cloud instance that is a live, unguarded path to production. This is the central risk ADR-0013 must address honestly rather than paper over — the mitigation is convention plus hourly drift detection, **not** permissions, because non-Enterprise n8n has no scoping to offer.

---

## Part A — Correct the documents

### A1. Rewrite `Docs/plans/08-vapi-layer.md`

Verified against `docs.vapi.ai`. Six defects, each of which breaks something.

**1. `serverMessages: ["tool-calls"]` disables the end-of-call report.**
Setting the field *replaces* the default list, it does not extend it. [08-vapi-layer.md:103](Docs/plans/08-vapi-layer.md#L103) therefore unsubscribes from `end-of-call-report`, `status-update`, `hang` and `transfer-destination-request` — killing the call-summary, QA and redaction pipeline that [04-core-api-service.md:99](Docs/plans/04-core-api-service.md#L99) depends on. Fix: subscribe to all five.

The §3.1 justification ("mixing them makes the router handle two payload shapes") is also wrong — Vapi documents a server-URL **priority stack**: *Custom Tool → Assistant → Phone Number → Account*. So the split is native: each tool's `server.url` → `/vapi/tools`; the assistant's `server.url` → `/webhooks/vapi/events`. Replace the rationale with the real one: we deliberately do **not** subscribe to `conversation-update`/`transcript`/`speech-update`, because those stream raw caller utterances — including medical detail (I6) and card digits mid-read (I5) — to our server ahead of redaction.

**2. `server.secret` does not exist.** The current `Server` schema is `{ url, credentialId, headers, timeoutSeconds, backoffPlan, staticIpAddressesEnabled, encryptedPaths }`. Auth is credential-based now. Remove the dead field; create two HMAC Custom Credentials in the dashboard (`grace-dev-webhook`, `grace-prod-webhook`) with algorithm SHA256, signature header `x-vapi-signature`, timestamp header `x-vapi-timestamp`, and reference them by `credentialId` injected from env.

This largely **resolves A-02**: the scheme is no longer an assumption about Vapi, it is true by construction. What remains unverified is only the credential's *Payload Format* value — a 10-minute dashboard check, recorded as a new **A-13**.

**3. `analysisPlan` is deprecated in its entirety.** *(Corrected 3 Aug 2026 after checking `api.vapi.ai/api-json` directly — an earlier draft of this plan said to migrate to `structuredDataPlan.schema`, but the spec marks **every** `AnalysisPlan` property `deprecated`, including the nested plans. Both shapes in circulation are dead ends.)*

| Shape | Status |
|---|---|
| `analysisPlan.summaryPrompt` / `.structuredDataSchema` (flat; still on the Call Analysis docs page) | deprecated |
| `analysisPlan.summaryPlan.messages` / `.structuredDataPlan.schema` (nested) | **also deprecated** |

The live mechanism is the first-class **StructuredOutput** resource (`POST /structured-output`, then `GET|PATCH|DELETE /structured-output/{id}`), referenced from the assistant via **`artifactPlan.structuredOutputIds`**. Results still read back at `call.analysis.structuredData`. `artifactPlan.scorecardIds` supersedes `successEvaluationPlan`. Also fold `recordingEnabled` into `artifactPlan` and add `compliancePlan`.

While rewriting the schema, replace the free-text `escalationReason` with a closed enum — an LLM-generated free-text field summarising a transcript that may contain health disclosures is a direct PHI route into a persisted column (I6).

**4. Vapi does not retry failed tool calls.** `Server.backoffPlan` "defaults to undefined (the request will not be retried)". [06-availability-engine.md](Docs/plans/06-availability-engine.md) §6.1 asserts retry-with-same-`toolCallId` as fact. Remove the claim. Idempotency stays — it protects against our own retries and duplicate model turns — but add an opt-in `backoffPlan` on **read** tools only, never the five write tools.

**5. `transferToHuman` cannot work as a function tool.** A function tool returns a string the model reads aloud; it cannot transfer a call. Convert it to a `type: "transferCall"` tool with `destinations: []` (empty ⇒ Vapi asks our server), handled by `transfer-destination-request` on the events webhook. `warm-transfer-experimental` is the only mode giving both whisper **and** return-to-assistant on no-answer, matching §7's flow — flag it as experimental.

**Bonus: A-04 is solved by config.** `TransferDestinationNumber.callerId` accepts `'{{customer.number}}'`. The RingCentral caller-ID risk is a setting, not an open question — downgrade A-04 from assumption to config line item (keep the spoken number as belt-and-braces).

**The companion escalation tool is mandatory, not a mitigation.** *(Confirmed 3 Aug 2026 from the spec.)* `CreateTransferCallToolDTO` is exactly `{ messages, type, destinations, rejectionPlan }` — it has **no `function` property**, so no `parameters`, so the model cannot pass `reason`/`urgency`/`summary` to it at all. The `transfer-destination-request` payload is `{ message: { type, call } }` and carries no tool arguments either. So context for the whisper and the `staff_tasks` row *must* come via a separate async `flagEscalation(reason, urgency, summary)` function tool, which the prompt requires immediately before transfer, priming the whisper under `call.id`. This is now tool #14 — the catalogue is 14 tools, not 13.

**6. Test Suites is deprecated and needs a phone number** — doubly blocked for us. Replace §9 with **Simulations** (`POST /eval/simulation/*`), which targets an `assistantId` directly, runs over `vapi.webchat` or `vapi.websocket`, and supports scenario-level **`toolMocks`** for fully deterministic runs with no tool server.

This also fixes the impossible "16 voice calls in an 8-minute PR pipeline" ([13-testing-strategy.md](Docs/plans/13-testing-strategy.md) §9). Three tiers:

| Tier | Trigger | Budget | Mechanism |
|---|---|---|---|
| **T1 Static** | every PR | <90s, $0 | Tool-JSON determinism, I7 greeting greps, validate `grace.json` against Vapi's published OpenAPI so a bad key fails locally, n8n lint, drift check. No calls. |
| **T2 Chat sim** | PRs touching prompts/tools/contracts | 3–5 min | 10 simulations, `vapi.webchat`, `toolMocks` on all 13 tools. Gates merge. |
| **T3 Voice sim** | nightly + release tag | 20–30 min | All 16, `vapi.websocket`, real mock server. Gates release, not merge. |

Scenarios 5 (mid-turn interruption) and 16 (mumbling) are voice-only — chat cannot test `endpointing` or `stopSpeakingPlan`. AC-08.6 (no card digits in transcript) is only meaningful in T3. Simulations evaluations accept **primitives only**, so each rubric line becomes its own boolean structured output. Split **AC-08.5** into 8.5a (T2 green per PR) and 8.5b (T3 green nightly).

**Also in the rewrite:** §8 drift must diff `remote` ⟷ `deepMerge(remote, local)`, not `local` ⟷ `remote` — Vapi materialises every server default, so a naive diff is red forever and re-reds each time Vapi ships a new default. Add a `MANAGED_PATHS` allowlist plus a `FORBIDDEN_DRIFT` hard-fail subset (`firstMessage`, system prompt, `serverMessages`, all `server.url`, all tool `parameters`, `compliancePlan`). Add an **hourly** scheduled drift job — that, not the PR check, is what catches a dashboard edit.

Smaller corrections: close the I7 hole (§3 hardcodes `firstMessage` while §6 protects only `first-message.txt`; AC-08.3 tests the file that isn't shipped — make `grace.json` inject from it); `endCallFunctionEnabled` adds a built-in tool so "all 13 tools" in AC-08.4 is imprecise; concurrency is **10 by default** per account and must be raised for the 25-sustained/50-burst target in [01-architecture-foundation.md](Docs/plans/01-architecture-foundation.md) §5; `maxDurationSeconds` default is 600, our 900 is an explicit override; **no per-call or account spend cap exists** in Vapi — state that plainly; explicitly record that Vapi's knowledge-base/files API is **rejected**, because the GROUNDING rule forbids any fact not returned by a tool.

### A2. Rewrite `Docs/plans/09-n8n-layer.md`

**1. The credential scheme is broken — this is the worst defect in either document.** §4.1 reduces credentials to `{ id: "<name>", name: "<name>" }`. n8n resolves credentials **strictly by `id`, with no name fallback** (confirmed in `packages/cli/src/credentials-helper.ts` — `CredentialNotFoundError`). Such a workflow `PUT`s 200 OK, publishes happily, and throws on its **first execution**. The verification step compares JSON, so it would not catch it. Replace with a resolvable placeholder `__CRED__:slack`, resolved by `deploy.ts` via `GET /api/v1/credentials`, with a **hard deploy failure** on any unresolved placeholder.

**2. `active` cannot be set via `PUT`** — it is `readOnly`. The `PUT` body must be **exactly** `{ name, nodes, connections, settings }` — the schema is `additionalProperties: false`, so anything extra is a 400.

*(Corrected 3 Aug 2026 by probing the live instance — an earlier draft said to use `POST /workflows/{id}/publish` and called `/activate` deprecated. On `palmleafmassage.app.n8n.cloud` today it is the **opposite**: `/publish` and `/unpublish` return **404**, while `/activate` and `/deactivate` exist. Hard-coding `/publish` would have 404'd on every single deploy.)*

`deploy.ts` must therefore **try `/publish`, fall back to `/activate` on 404** — n8n Cloud auto-updates, so pinning either route guarantees a future break. Verification compares against the active/published version where the instance exposes that distinction; where `/publish` is absent, the draft is what runs.

**3. Normalisation over-strips.** Do **not** strip node `id` (regenerated UUIDs cause diff churn) or node **`webhookId`** (it determines the webhook URL when `path` is unset — stripping it silently changes the production webhook URL). Use `?excludePinnedData=true` instead of hand-stripping `pinData`. `settings.errorWorkflow` is a workflow **ID** and needs the same placeholder treatment as credentials.

**4. Replace §4.2 with the single-Cloud-instance scheme:**

| Axis | Dev | Prod |
|---|---|---|
| Name | `[dev] WF-12 …` | `[prod] WF-12 …` |
| Committed file | unprefixed; env applied at deploy | same file |
| Tags | `env:dev`, `managed:git` | `env:prod`, `managed:git` |
| Webhook `path` | `dev/escalation` (always explicit) | `prod/escalation` |
| Credentials | `PalmLeaf Slack (dev)` | `… (prod)` |
| Slack app | `PalmLeaf Grace (dev)` | `PalmLeaf Grace` |

`deploy.ts --env prod` filters on `?tags=managed:git,env:prod`, refuses to touch anything lacking the prefix or the tag, and fails on orphans. (Do not combine `projectId` with `tags` — n8n bug #19283.)

**5. Add lint rules 9–15** to the existing 8: no env prefix in committed names; explicit `{{ENV}}/`-prefixed webhook paths; credential ids must match `^__CRED__:`; `errorWorkflow` must be `__WF__:`; no `executionTimeout` on Wait-node workflows (bug #15123 kills waiting executions); no sub-65s Wait used as a durability boundary; Slack webhooks need Raw Body + `responseNode` + a respond node within 2 nodes of signature verification.

**6. Resolve the three-way WF-12 trigger contradiction** in favour of `staff.notify` → outbox → `sync-worker` → signed HTTP → n8n. This is the only reading consistent with [04-core-api-service.md:16](Docs/plans/04-core-api-service.md#L16) and [01-architecture-foundation.md:111](Docs/plans/01-architecture-foundation.md#L111). Define the missing `GRACE_N8N_WEBHOOK_SECRET` and its exact HMAC construction — **no secret exists today for this direction**, while every other direction has one.

**7. Specify the seven unspecified workflows.** Only WF-12 has a spec. Also: give the global error workflow a real number (**WF-00**) and put it in the inventory; fix the arithmetic (§57 says "six workflows move into code" — it is ten; [17-open-decisions.md](Docs/plans/17-open-decisions.md) D-7 says seven remain — it is eight); flag that **WF-12/WF-18 send staff SMS via an n8n Twilio node, bypassing the adapter's 10DLC/opt-out enforcement** ([05-provider-adapters.md](Docs/plans/05-provider-adapters.md) §6) — route them back through `/internal/*`.

**Good news to record:** n8n Cloud closes several gaps for free. Public HTTPS ingress is solved (Slack can reach it). Wait nodes **≥65s offload to the database and survive restarts** — so WF-12's 15-min and WF-18's 30-min timers are durable without queue mode. Constraints to note: Starter gives **5 concurrent executions** and **7-day execution retention** shared between dev and prod (a dev loop can starve prod); **non-Enterprise API keys have full access to everything** — unmitigable; Slack allows **one Request URL per app**, so dev and prod need **two Slack apps**.

### A3. New `Docs/plans/18-platform-setup.md`

The account-connection runbook, which currently has no home: Vapi org setup, API keys, HMAC credential creation, concurrency raise, MCP config; n8n Cloud API key, tags, credential inventory, two Slack apps with scopes and signing secrets; the local run loop (mock server → tunnel → deploy dev → web harness); and the GitHub Actions secret inventory.

### A4. Surgical cross-doc fixes

| File | Fix |
|---|---|
| [01-architecture-foundation.md](Docs/plans/01-architecture-foundation.md) | Add **ADR-0013** (I9 relaxed for one n8n instance — CI is the only *publisher*; n8n v2's draft/publish split means dashboard edits do not reach prod without a deliberate publish; hourly drift detection; exit criteria: Business tier or a second client). Fix ADR-0002's stale text still claiming n8n owns SMS dispatch and end-of-call processing. Clarify that §5's latency numbers are **p95 targets, not hard deadlines** — [04-core-api-service.md](Docs/plans/04-core-api-service.md) §6.4 currently races handlers against a p95 target, which fires the error sentence on 1 call in 20 by construction. |
| [03-data-model.md](Docs/plans/03-data-model.md) | Add `staff_tasks.acknowledged_at` (WF-18's "unacknowledged for 15 min" is unanswerable without it); add the unique index [07-booking-write-path.md:112](Docs/plans/07-booking-write-path.md#L112) already depends on; document the `"P1"`→smallint mapping; constrain `staff_tasks.type`. |
| [04-core-api-service.md](Docs/plans/04-core-api-service.md) | Rewrite §6.1 around `credentialId` instead of `server.secret`; write the single authoritative `/internal/*` route table and resolve the `:type` vs `:id` collision; separate deadline from p95 budget. |
| [17-open-decisions.md](Docs/plans/17-open-decisions.md) | Rewrite A-02; downgrade A-04 to config; add A-13 (HMAC payload format), A-14 (`transferCall` reportedly unsupported on web calls — **our only test channel**), A-15 (`warm-transfer-experimental` honouring a 25s ring). |

---

## Part B — Implement

### B1. Repo skeleton
pnpm workspace, TypeScript strict, `tsx`, vitest, ESLint per [02-repository-and-tooling.md](Docs/plans/02-repository-and-tooling.md) §1 — trimmed to what the platform layers need. No Docker, no Postgres.

### B2. `packages/contracts`
Zod input/output schemas for all 13 tools (roadmap task **B-01**), zero deps but zod. Follow the fully-worked `CheckAvailabilityInput` pattern at [02-repository-and-tooling.md](Docs/plans/02-repository-and-tooling.md) §4 — `.strict()` mandatory, `.describe()` on every field (it becomes model-visible prompt text).

### B3. `platform/vapi/`
`generate-tools.ts` (zod → JSON Schema → tool JSON, CI-drift-checked); `assistants/grace.json` with all six corrections; `prompts/sections/` assembled into `system.md`, with `first-message.txt` as the injected source of truth for I7; `deploy.ts` with the merge-based diff, `.lock.json`, dirty-tree guard; `simulations/` for T2/T3.

`transferToHuman.json` is **hand-authored, not generated** — it is a `transferCall` tool, not a function tool.

### B4. `platform/vapi/mock-server/` + `web-harness/` ← the piece that makes this phase testable
Without it every tool returns nothing on a web call, Grace says "I'm having trouble" every turn, and we validate zero of: prompt structure, grounding rule, medical gate, PCI refusal, endpointing, filler timing, spoken-number formatting, or the generated schemas. That is the entire value of a platform-only phase. ~1 day.

A ~200-line `node:http` server exposing **the same two routes as Core API** with the same envelope and response shape, so switching later is one env var. It **validates arguments with the real zod schemas from `packages/contracts`** — proving the generated JSON Schema and the zod schema agree under a live model. Plus: frozen clock (`GRACE_MOCK_NOW`) for deterministic dates; fault injection (`GRACE_MOCK_LATENCY_MS`, `_FAIL`, `_TIMEOUT`) to exercise deadline fallbacks; an in-memory idempotency map; and a `transfer-destination-request` handler returning the canned destination.

It is a permanent asset — when Core API lands it becomes the contract-test double proving both implementations agree on all 13 envelopes.

The web harness is ~60 lines: `@vapi-ai/web` 2.6.1, public key, dev `assistantId`. Web calls use the exact stored assistant config, so this is a faithful test channel — except for transfer (A-14).

### B5. `platform/n8n/`
`export.ts` (normalise per the corrected rules), `deploy.ts` (tag-filtered, credential-resolving, publish-not-activate, `activeVersion` verification), `lint.ts` (15 rules), `credentials.example.json`, and WF-00/07/11/12/14/15/16/18 authored via MCP against `[dev]`-tagged workflows.

---

## Verification

1. `pnpm check` — typecheck, lint, unit tests green.
2. `pnpm platform:vapi:generate` twice → byte-identical; CI fails if uncommitted.
3. Every tool JSON and `grace.json` validate against Vapi's published OpenAPI **locally** — this is what catches a `structuredDataSchema`-class error before deploy.
4. Delete "may be recorded" from `first-message.txt` → CI fails (AC-08.3).
5. `pnpm platform:vapi:deploy --env dev --apply` → re-run `--diff` → zero drift (AC-08.1). Dirty tree → refuses (AC-08.8).
6. **End-to-end web call**: mock server + tunnel + web harness. Book an appointment start to finish. Confirm the medical gate fires, a read card number is refused, times are spoken as "two fifteen", and `request-start` fillers cover tool latency.
7. `GRACE_MOCK_FAIL=checkAvailability` → Grace speaks the graceful fallback, never invents availability.
8. T2 chat simulations green (AC-08.5a); T3 voice suite green overnight (AC-08.5b).
9. Vapi dashboard: `end-of-call-report` **actually arrives** at the events URL with a populated `structuredData` — the single clearest proof the §3 rewrite was necessary.
10. n8n: `lint.ts` fails a deliberately broken workflow (AC-09.1); `export.ts` twice → identical (AC-09.2); deploy a workflow with an unresolved `__CRED__` placeholder → **hard fail** (the new AC covering the worst defect); WF-12 delivers a P1 to Slack from a signed curl fixture.

---

## Handoff to Claude Sonnet

On approval, before Step 0, this plan is copied into the repo as **`Docs/plans/19-vapi-n8n-execution-plan.md`** and linked from [00-INDEX.md](Docs/plans/00-INDEX.md), so it survives this session and Sonnet can execute it directly.

Suggested execution order for Sonnet, each a separate commit:

| # | Work | Deliverable |
|---|---|---|
| 1 | Step 0 | `.mcp.json`, `.mcp.json.example`, `.gitignore` |
| 2 | A1 | Rewritten `08-vapi-layer.md` |
| 3 | A2 | Rewritten `09-n8n-layer.md` |
| 4 | A3 | New `18-platform-setup.md` |
| 5 | A4 | Surgical fixes to `01`/`03`/`04`/`17` |
| 6 | B1–B2 | Repo skeleton + `packages/contracts` (13 zod schemas) |
| 7 | B3 | `platform/vapi/` — generate, assistant, prompts, deploy |
| 8 | B4 | Mock server + web harness → **first working web call** |
| 9 | B5 | `platform/n8n/` — export, deploy, lint, workflows |

Steps 2–5 are documentation only and can be reviewed before any code is written. Step 8 is the first point where you can hear Grace.

---

## Risks

- **n8n MCP exposes `publish_workflow` on a single instance.** An agent can reach production. Guarded by convention, lint and hourly drift detection — not by permission. Documented honestly in ADR-0013 rather than papered over.
- **Non-Enterprise n8n API keys have full instance access.** No mitigation exists below Enterprise; keys stay in GitHub Actions secrets with short expirations.
- **`transferCall` may not work on web calls** (community-reported, unverified) — our only test channel cannot exercise transfer. We test the *decision* to transfer via chat simulation with `toolMocks`, and defer live verification to when a number exists.
- **Tool JSON depends on `packages/contracts`**, so a small contracts package is unavoidable inside "platform only". This is roadmap task B-01 and is unblocked.
