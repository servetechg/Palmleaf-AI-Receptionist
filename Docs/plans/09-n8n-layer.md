# 09 — n8n Orchestration Layer

**Read before:** authoring any workflow.
**Implements:** ADR-0002, ADR-0010, **ADR-0013**.

> **Verification status.** Every API claim below was probed on **3 August 2026** against the live
> instance `palmleafmassage.app.n8n.cloud` with the project's own API key, and cross-checked against
> n8n's public-API OpenAPI source. Endpoint availability differs between n8n versions — **§4.4 records
> what this instance actually exposes today**, and `deploy.ts` is written to tolerate both shapes.
>
> The previous version specified a credential-normalisation scheme that deploys green and then throws at
> first execution, and told `deploy.ts` to set `active` via `PUT`, which is read-only. §8 lists every
> correction.

---

## 1. What n8n owns — and what it does not

Per ADR-0002, n8n is **not** on the synchronous voice path. It owns the operational plumbing where its
strengths — visual routing, connector breadth, and editability by a non-developer — are real advantages.

| n8n owns | Core API / workers own |
|---|---|
| Staff notification fan-out (Slack, email, SMS, on-call) | Vapi tool endpoints |
| Escalation routing and rota logic | Availability and booking |
| Daily/weekly operational digests | Outbox dispatch |
| Nightly reconciliation *reporting* (not the reconciling) | PMS/Calendar/Stripe/Twilio adapter calls |
| Ad-hoc client-requested integrations (CRM, reviews, marketing) | Anything with a latency budget |
| Manual staff actions (approve a task, resend a link) | Anything transactional |
| Vagaro webhook *fan-out* to secondary consumers | Vagaro webhook *ingestion* (needs the 20s ACK) |

> **Boundary rule:** if it has a latency budget, a transaction, or money attached, it is not an n8n
> workflow. If it is a notification, a report, or something the client may want to tweak, it is.
>
> WF-07 and WF-15 touch money-adjacent data (reconciliation, deposits outstanding) but are **read-only
> reporting** — they observe, never write. That is the line.

n8n reaches the system through `POST /internal/*` endpoints on the Core API with a bearer token — it
never touches Postgres directly. That keeps RLS, validation, and the state machine intact.

---

## 2. How work reaches n8n

The previous version gave three mutually incompatible answers ("Webhook from Core API" in §2 and §3,
`staff.notify` outbox in AC-09.4) while §04 §16 and §01 §111 both **forbid Core API from calling n8n**.

**Resolved:** the cold path calls n8n. Core API never does.

```
tool handler (hot path)
  └─ writes staff_tasks row + outbox row `staff.notify`   [one transaction]
                                   │
                          sync-worker picks it up          [cold path]
                                   │
                          HMAC-signed POST ──────────────► n8n WF-12
```

This is the only reading consistent with ADR-0002, §04 §16, §01 §111 and AC-09.4. The same path serves
WF-17 (via a new `webhook.fanout` outbox event) and WF-18.

### 2.1 Outbound authentication — currently undefined, must be specified

Every *inbound* direction has a secret (`GRACE_VAPI_WEBHOOK_SECRET`, `GRACE_VAGARO_WEBHOOK_TOKEN`,
`GRACE_STRIPE_WEBHOOK_SECRET`, `GRACE_TWILIO_AUTH_TOKEN`). **There is no secret for worker → n8n.**
§11 §210's auth matrix has no row for it either.

```
New env var:  GRACE_N8N_WEBHOOK_SECRET   (z.string().min(32), per environment)

Headers sent by sync-worker:
  x-grace-timestamp: <unix seconds>
  x-grace-signature: hex(HMAC-SHA256(secret, `${timestamp}.${rawBody}`))

n8n verifies, as the FIRST functional node after the trigger:
  - reject if |now - timestamp| > 300s          → 401
  - timing-safe compare                          → 401
  - Raw Body MUST be enabled on the Webhook node (the signature covers exact bytes)
```

Add the matching row to §11's auth matrix. Rotation follows the same current+previous 24h window as
every other secret (§14 §130).

---

## 3. Workflow inventory

Renumbered from the design brief §9 to reflect the ADR-0002 split.

| ID | Workflow | Trigger | Owner | Notes |
|---|---|---|---|---|
| `WF-00` | **Global Error Handler** | n8n error trigger | n8n | ★ New. Every workflow's `errorWorkflow` points here. See §3.2. |
| `WF-01` | ~~Tool Router~~ | — | **→ Core API** | Moved. ADR-0002. |
| `WF-02` | ~~Availability Query~~ | — | **→ Core API** | Moved. |
| `WF-03` | ~~Create Booking~~ | — | **→ Core API** | Moved. |
| `WF-04` | ~~Reschedule/Cancel~~ | — | **→ Core API** | Moved. |
| `WF-05` | ~~Vagaro Webhook Receiver~~ | — | **→ Core API** | Moved — the 20s ACK needs a fast dedicated endpoint. |
| `WF-06` | ~~Vagaro Poller~~ | — | **→ sync-worker** | Moved. |
| `WF-07` | **Nightly Reconciliation Report** | Cron 03:15 America/Chicago | n8n | Reads `/internal/reports/reconciliation`, formats, posts to Slack + email |
| `WF-08` | ~~Track B Worker~~ | — | **→ booking-worker** | Moved. |
| `WF-09` | ~~SMS Dispatcher~~ | — | **→ sync-worker** | Moved — must be transactional with the outbox. |
| `WF-10` | ~~Payment Handler~~ | — | **→ Core API webhook** | Moved — signature verification + state machine. |
| `WF-11` | **Hourly Call Digest** | Cron hourly | n8n | Summarises the hour's calls for staff. *Renamed* — the brief's WF-11 was the End-of-Call **Processor**, which is now `call.process_transcript` in sync-worker. Same number, different job; do not cross-reference the brief. |
| `WF-12` | **Escalation & Alerting** | Signed webhook from sync-worker | n8n | ★ The reference workflow. §4. |
| `WF-13` | ~~Hold Expiry Sweeper~~ | — | **→ sync-worker** | Moved — 30s cadence, transactional. |
| `WF-14` | **Staff Action Handler** | Slack interactivity + slash command | n8n | Two Slack surfaces, not one. §3.1. |
| `WF-15` | **Daily Operations Digest** | Cron 07:30 America/Chicago | n8n | Yesterday's calls, bookings, containment, open tasks, deposits outstanding |
| `WF-16` | **Weekly QA Sampler** | Cron Mon 09:00 America/Chicago | n8n | Pulls 20 random calls, builds a scoring sheet, assigns it (design brief §13) |
| `WF-17` | **Vagaro Webhook Fan-out** | Signed webhook from sync-worker | n8n | Secondary consumers (client CRM, marketing). Needs a `webhook.fanout` outbox event. |
| `WF-18` | **On-call Escalation** | Called by WF-12 | n8n | P1 unacknowledged 15 min → SMS manager → 30 min → call manager. §3.3. |

**Net: ten workflows move into code; nine remain in n8n** (WF-00, 07, 11, 12, 14, 15, 16, 17, 18).

> ⛔ The previous version said "six workflows move into code" (§57) and §17 D-7 said "7 workflows in n8n,
> 6 moved into code". Both are wrong: strike-through rows number ten, and the surviving set is nine once
> WF-00 is counted. Corrected here and in §17.

**Cron timezone.** All crons run `America/Chicago`, set explicitly per workflow — do not rely on the
instance default, and do not write "CT" (ambiguous between CST/CDT). WF-07 at 03:15 deliberately trails
the reconciliation job that finishes by 03:00 (§01 §206); that ordering is a real dependency.

### 3.1 WF-14 is two Slack surfaces

The one-line description hid a real problem. WF-14 handles **both**:

1. **Interactive block actions** — staff clicks "Resolved" → `POST /internal/tasks/:id/resolve`
2. **The `/grace-kill` slash command** (§16 §31, §10 §113) — a completely different Slack surface with a
   different payload encoding and its own authorization question: *who* may invoke it?

⚠️ Neither is served by n8n's **Slack Trigger node**, which covers the Events API only (`message`,
`app_mention`, `reaction_added`, …) — no `block_actions`, no slash commands. Both require a **raw Webhook
node**, and n8n provides **no built-in Slack signature verification there**. Implement it by hand:

```
HMAC-SHA256 over  v0:{x-slack-request-timestamp}:{rawBody}   keyed on the signing secret
compare to        x-slack-signature
reject if         |now - timestamp| > 300s
requires          Raw Body ENABLED on the Webhook node
```

**Slack's 3-second ACK is mandatory.** Response Mode = `responseNode`, and the Respond-to-Webhook node
must sit **immediately after signature verification**, before any HTTP call to Core API. Post the
"Resolved ✅" update afterwards via `response_url` (usable 5× within 30 minutes).

**Kill-switch authorization** is unresolved and must not ship open: restrict `/grace-kill` to an explicit
allowlist of Slack user ids held in n8n, and log every invocation. Logged as **A-19**.

### 3.2 WF-00 — the global error handler

The previous version required `errorWorkflow` on every workflow (checklist + lint rule 6) but never
created the workflow, never gave it a number, and never put it in the inventory or in task C-13.

WF-00 receives n8n's error trigger and posts to `#palmleaf-ops-log` with workflow name, execution id,
node, and error message. It is **exempt from lint rule 6** (it cannot point at itself) — the lint must
encode that exemption explicitly.

> **There is no alert anywhere for "n8n is down."** §12's 24 alerts contain none, and §07 §331's failure
> catalogue has no n8n row. Under ADR-0002 n8n is off the call path, so the brief's old detection
> ("n8n unreachable → tool timeout → Grace apologises") no longer exists and nothing replaced it. If n8n
> dies, **every P1 staff escalation disappears silently.** Add to §12: a heartbeat workflow plus a
> "no n8n execution in 60 min" alert at P2. Carried into §19 §A4.

### 3.3 WF-18 has no independent trigger

The previous version gave WF-18 trigger "Webhook" *and* had WF-12's P1 branch call it after a Wait —
two escalation timers with no arbitration. **Resolved:** WF-12 owns the timer and invokes WF-18 directly.
WF-18 has no webhook of its own.

⚠️ WF-18's final step is "call manager". Nothing specifies how a voice call is placed:
`VoicePort.createOutboundCall` is Phase F (§05 §242), and a direct Twilio Voice node is not specified
either. Until Phase F, WF-18 terminates at repeat-SMS + a P1 Slack `@here`. Do not silently drop the
escalation. Logged as **A-20**.

### 3.4 Staff SMS bypasses the messaging adapter — must be fixed

WF-12 and WF-18 SMS the manager from an **n8n Twilio node**. §05 §217 states messaging rules are
"enforced **inside the adapter**, so no caller can bypass them" — opt-out enforcement, consent checks,
STOP/HELP footer, and the `GRACE_SMS_10DLC_READY` gate behind **GATE-09**.

An n8n Twilio node bypasses all of it. Unregistered staff SMS will be **carrier-filtered**, and the
escalation path fails silently — the exact failure mode the escalation exists to prevent.

**Decision:** WF-12/WF-18 send staff SMS by calling `POST /internal/notify/sms`, not a Twilio node.
Slack remains a direct n8n node (no regulatory surface). Also resolves the duplicated Twilio credential
noted in §11 §18's threat model.

---

## 4. WF-12 — Escalation & Alerting (the reference workflow)

```
[Webhook: POST /prod/escalation]  (POST, Raw Body ON, responseMode=responseNode)
      │  auth: HMAC per §2.1 — FIRST functional node
      ▼
[Function: verify signature]  ──fail──► [Respond 401]
      ▼
[Function: validate + normalise]  → { taskId, type, priority, tenant, payload, occurredAt }
      ▼
[Respond to Webhook: 200 {ok:true}]      ← ACK EARLY. Everything below is fire-and-forget.
      ▼
[Switch on priority]
  ├─ P1 ──► [Slack: #palmleaf-alerts, @here]
  │         [HTTP: POST /internal/notify/sms  → manager]        (§3.4, not a Twilio node)
  │         [Wait 15 min] ─► [HTTP: GET /internal/tasks/:id] ─► [IF still unacknowledged] ─► [WF-18]
  ├─ P2 ──► [Slack: #palmleaf-alerts]
  │         [IF outside business hours] ─► [queue for 08:00 digest] : [immediate]
  ├─ P3 ──► [HTTP: POST /internal/digest/append]                 (§4.2)
  └─ default ─► [Slack: #palmleaf-ops-log]
```

**Respond early, then work.** The previous diagram responded *last*, after a 15-minute Wait — which would
hold the HTTP connection open for 15 minutes and time out the caller. The ACK belongs immediately after
validation.

### 4.1 Node requirements — the checklist

Every webhook-triggered workflow **must** have:

- [ ] Webhook node set to **POST**
- [ ] **Production** URL used by callers (never the test URL)
- [ ] Explicit `path`, prefixed with the environment (`dev/…` or `prod/…`) — never rely on `webhookId`
- [ ] **Raw Body** enabled wherever a signature is verified
- [ ] Response Mode = **"Using Respond to Webhook Node"**
- [ ] A **Respond to Webhook** node on **every** branch — including error branches
- [ ] Signature/token verification as the first functional node
- [ ] "Continue On Fail" on external nodes, with the failure branch routed to a respond node
- [ ] `errorWorkflow` set to WF-00
- [ ] **No `settings.executionTimeout`** if the workflow contains a Wait node (see §4.3)
- [ ] Workflow published

### 4.2 The "daily digest store" — now a real endpoint

The previous P3 branch said `[Append to daily digest store]`. **That store was defined nowhere** — not a
table in §03, not Redis, not n8n static data. Replaced with `POST /internal/digest/append`, backed by a
real table. This is one of five `/internal/*` endpoints that doc 09 assumed and doc 04 never declared —
all now carried into §19 §A4 for the §04 §4 route table:

| Endpoint | Consumer |
|---|---|
| `GET /internal/reports/reconciliation` | WF-07 |
| `GET /internal/reports/calls?window=1h` | WF-11 |
| `GET /internal/reports/daily` | WF-15 |
| `GET /internal/reports/qa-sample?n=20` | WF-16 |
| `POST /internal/digest/append` | WF-12 P3 |
| `POST /internal/notify/sms` | WF-12, WF-18 (§3.4) |
| `GET /internal/tenants/:slug/settings` | all — see §7 |

**Containment** deserves special note: it exists only as the Prometheus gauge
`grace_containment_ratio{tenant}` (§12 §70), and `/metrics` is network-restricted (§04 §102). WF-15 cannot
reach it. Either expose it through `/internal/reports/daily` or drop it from the digest — do not leave
the workflow reading a metric it cannot access.

### 4.3 Wait-node durability — verified, with limits

✅ n8n offloads a waiting execution to the database and reloads it on resume — **but only for waits ≥ 65
seconds**. Below that the process stays in memory and the wait is lost on restart. WF-12's 15-minute and
WF-18's 30-minute waits are therefore durable across a Cloud redeploy. Queue mode is not required for
this; DB persistence is what matters.

Two constraints:
- ⚠️ `settings.executionTimeout` **kills a waiting execution** (n8n#15123). Leave it unset on WF-12/WF-18;
  lint rule 13 enforces it.
- Execution retention on lower Cloud tiers is limited (see §5.1). A waiting execution can be pruned before
  it resumes if the wait outlives retention. 15–30 minutes is safe; **never design a multi-day wait.**

---

## 5. One Cloud instance — dev and prod by convention (ADR-0013)

We have a **single n8n Cloud instance**. The previous §4.2 assumed two (`n8n-dev` on :5679 + `n8n-prod`,
CI-only). That model is what invariant **I9** relied on, so I9 is deliberately relaxed — see ADR-0013 in
§01, and read §5.2 before assuming this is safe.

| Axis | Dev | Prod |
|---|---|---|
| Workflow name | `[dev] WF-12 Escalation & Alerting` | `[prod] WF-12 Escalation & Alerting` |
| Committed file | `WF-12-escalation-alerting.json`, name **unprefixed** | same file |
| Tags | `env:dev`, `managed:git` | `env:prod`, `managed:git` |
| Webhook `path` | `dev/escalation` | `prod/escalation` |
| Credentials | `PalmLeaf Slack (dev)` | `PalmLeaf Slack (prod)` |
| `errorWorkflow` | `[dev] WF-00` | `[prod] WF-00` |
| Slack app | `PalmLeaf Grace (dev)` | `PalmLeaf Grace` |

One committed, environment-neutral file per workflow; the environment is materialised at deploy time.

⚠️ **Slack requires two apps.** Slack allows exactly one Request URL per app, so dev and prod cannot share
one. Budget for two app registrations, two signing secrets, two bot tokens.

### 5.1 What this instance actually provides

Probed live on 3 August 2026 with the project API key:

| Surface | Result |
|---|---|
| `GET /api/v1/workflows` | ✅ 200 |
| `GET /api/v1/credentials` | ✅ 200 — returns `{id, name, type, createdAt, updatedAt, shared}`, **no secret data** |
| `GET /api/v1/tags` | ✅ 200 — currently **empty**; `env:dev`, `env:prod`, `managed:git` must be created |
| `GET /api/v1/projects` | ✅ 200 |
| `POST /workflows/{id}/activate` · `/deactivate` | ✅ **exist** |
| `POST /workflows/{id}/publish` · `/unpublish` | ❌ **404 — absent on this version** |

Existing content: one workflow (`AI Agent workflow`, inactive, **untagged**) and one credential
(`n8n free OpenAI API credits`, `openAiApi`). Neither is tagged `managed:git`, so the deploy filter in
§6 correctly ignores both — a useful accidental test of the scheme.

**Plan-tier constraints to design around:** shared concurrency and execution retention across dev *and*
prod on one instance — a dev test loop can consume prod's quota. Keep WF-16 (20 calls weekly) and any
polling workflow dev-disabled until the tier is raised.

### 5.2 Residual risk versus true I9 — state honestly

1. **API-key scoping does not exist below Enterprise.** Verified on the live instance: the key's `scopes`
   array includes `workflow:create/update/delete/publish` and credential access across *everything*. One
   key reaches dev and prod alike. **Unmitigable on this tier.**
2. **The MCP server can publish.** The n8n MCP server exposes `publish_workflow` / `unpublish_workflow`,
   and its `search_workflows` sees every workflow *regardless of the per-workflow "Available in MCP"
   setting*. An agent with MCP access has a live path to production. Guarded by convention and detection,
   **not by permission.**
3. **Detection is the actual control.** An hourly job compares the deployed workflow against git; any diff
   is a P2 alert. On lower Cloud tiers, short execution retention and workflow history mean **git is the
   only durable audit trail** — which makes that job non-optional, not a nice-to-have.
4. **Draft/publish narrows the blast radius, where available.** n8n v2 autosaves dashboard edits as a
   *draft*; production keeps running the published version. Where that model is active, I9 weakens from
   "no human edits production" to the much smaller **"no human *publishes* production."** ⚠️ Note the
   `/publish` route is absent on this instance (§5.1) even though `activeVersion` appears in the workflow
   payload — so do not lean on this argument until the route exists. Logged as **A-21**.

**Exit criteria for ADR-0013:** move to true two-instance environments the moment the account reaches a
tier with environments/source-control, or the moment a second client shares the instance.

---

## 6. Workflows-as-code

```
platform/n8n/
├── workflows/
│   ├── WF-00-global-error-handler.json
│   ├── WF-12-escalation-alerting.json
│   └── ...
├── lint.ts                 # structural checks (§7)
├── export.ts               # pull from the instance → normalise → write files
├── deploy.ts               # tag-filtered push, activate, verify
└── credentials.example.json
```

### 6.1 Normalisation on export

Raw exports contain volatile fields that make every diff unreadable. Verified live, `GET
/api/v1/workflows` returns: `active, activeVersion, activeVersionId, connections, createdAt, id,
isArchived, meta, name, nodeGroups, nodes, pinData, settings, shared, staticData, tags, triggerCount,
updatedAt, versionId`.

**Strip:** `id`, `versionId`, `activeVersionId`, `activeVersion`, `createdAt`, `updatedAt`, `meta`,
`shared`, `triggerCount`, `isArchived`, `active`, `tags`.
**Keep, and do not touch:**

- **node `id`** — stripping it makes n8n regenerate UUIDs, producing diff churn on every export.
- **node `webhookId`** — it determines the webhook URL when `path` is unset. Stripping it **silently
  changes the production webhook URL**. (This is also why §4.1 mandates an explicit `path`.)

> ⛔ The previous version stripped node `position` to a 20px grid and removed `pinData` by hand. Use
> `?excludePinnedData=true` on the request instead — the API does it server-side. Verified node keys are
> exactly `{id, name, parameters, position, type, typeVersion}`.

`settings.errorWorkflow` holds a workflow **ID**, so it needs the same placeholder treatment as
credentials (§6.2). Keys are sorted so diffs are deterministic.

### 6.2 Credentials — the previous scheme was broken

> ⛔ The previous §4.1 reduced credential objects to `{ id: "<name>", name: "<name>" }`. **n8n resolves
> credentials strictly by `id`, with no name fallback** — confirmed in
> `packages/cli/src/credentials-helper.ts`, which throws `CredentialNotFoundError` when the id does not
> resolve. Such a workflow `PUT`s 200 OK, activates happily, and throws on its **first execution**. Worse,
> the old verification step compared JSON only, so it would never catch it. This was the most damaging
> defect in the document.

Committed workflows carry a resolvable placeholder instead:

```jsonc
"credentials": {
  "slackApi": { "id": "__CRED__:slack", "name": "__CRED__:slack" }
}
```

`deploy.ts` resolves `__CRED__:slack` → `PalmLeaf Slack (prod)` → the real id via
`GET /api/v1/credentials` (verified: returns `{id, name, type}` and no secret material).
`export.ts` performs the reverse mapping. **Any unresolved placeholder is a hard deploy failure** —
because n8n itself will not fail, it will publish and then break at runtime.

Credentials are **never** deployed. They are created once per instance by hand and referenced by name;
`credentials.example.json` documents which must exist. ⚠️ Hand-created credentials sit outside the
secret manager and outside the current+previous rotation window promised in §11 §217 — note the gap.

### 6.3 Deploy

```
platform/n8n/deploy.ts --env prod
  1. GET /api/v1/workflows?tags=managed:git,env:prod&excludePinnedData=true   → name→id map
       (do NOT also pass projectId — n8n#19283: the two filters do not work together)
  2. GET /api/v1/credentials                                                  → name→id map
  3. GET /api/v1/tags                                                         → tag name→id map (create if missing)
  4. Render environment: name prefix, webhook path prefix, credential ids, errorWorkflow id
  5. REFUSE if a matched remote workflow lacks the env prefix or the managed:git tag,
     or if the target name collides with an env:dev workflow
  6. PUT /api/v1/workflows/{id}  with EXACTLY { name, nodes, connections, settings }
       (the schema is additionalProperties:false — anything extra is a 400)
     or POST /api/v1/workflows for a new one
  7. PUT /api/v1/workflows/{id}/tags   with resolved tag IDs (tags are read-only on the workflow body)
  8. Activate: POST /workflows/{id}/publish, falling back to /activate on 404   ← §6.4
  9. Re-fetch and assert equality against the ACTIVE version, not the draft
 10. Any env:prod + managed:git workflow with no local file → orphan → FAIL
```

Fail loudly on any mismatch — silent partial deploys are worse than no deploy.

### 6.4 `active` is read-only — and which route to call

> ⛔ The previous step 3 said "Activate workflows marked `active: true`". `active` is **read-only** on the
> workflow body; setting it via `PUT` does nothing.

Activation is a separate endpoint, and **which one depends on the n8n version**:

| Route | This instance (3 Aug 2026) | Notes |
|---|---|---|
| `POST /workflows/{id}/activate` | ✅ exists | what we use today |
| `POST /workflows/{id}/publish` | ❌ 404 | newer route; some docs call `/activate` deprecated |

`deploy.ts` **tries `/publish` first and falls back to `/activate` on 404.** n8n Cloud auto-updates, so
hard-coding either one guarantees a future breakage. This version-tolerance is required, not defensive
padding — the plan originally specified `/publish` only, which would fail on every deploy here today.

Similarly, step 9 must compare against the **active/published** version rather than the draft wherever
the instance exposes that distinction; on an instance without `/publish`, the draft *is* what runs.

⚠️ `PUT` on a published workflow may auto-republish, and may return **409** on an open workflow review or
a webhook path conflict. Handle 409 explicitly rather than retrying blindly. A path collision between dev
and prod is a *useful* guard — do not suppress it.

---

## 7. Multi-tenancy — unhandled, and it will break at tenant two

ADR-0008 makes every table tenant-scoped, and `tenants.settings` carries `escalationSlackChannel` and
`managerMobile` (§03 §113). **But n8n cannot read tenant settings** — no `/internal/tenants/:slug/settings`
endpoint exists — so WF-12's channel and manager mobile must be hardcoded or held as n8n credentials.

The first non-PalmLeaf tenant breaks every workflow. This is not flagged as a risk anywhere in the current
plan set, and A-01 explicitly assumes PalmLeaf is "tenant one of a productized service".

**Decision for now:** hardcode PalmLeaf, and add `GET /internal/tenants/:slug/settings` to the §4.2
endpoint list so workflows can be parameterised in Phase F. Registered as risk **R-n8n-1** in §17.

---

## 8. Workflow CI lint

```ts
// TARGET — platform/n8n/lint.ts   asserts, per workflow:
 1. Every webhook trigger has httpMethod === 'POST' and responseMode === 'responseNode'
 2. Every path from a webhook trigger terminates in a 'Respond to Webhook' node
 3. No node contains a hardcoded secret (regex: sk_, whsec_, Bearer , AC[0-9a-f]{32}, xoxb-, eyJ…)
 4. No node references a localhost or ngrok URL
 5. No HTTP Request node lacks a timeout
 6. Every workflow has errorWorkflow set  — EXCEPT WF-00, which is the handler (§3.2)
 7. Workflow name matches its filename, and carries NO [dev]/[prod] prefix in git
 8. No pinData present
 9. Every Webhook and Wait-on-webhook node has an explicit `path`
10. Every node.credentials.*.id matches /^__CRED__:[a-z0-9-]+$/  — never a raw id, never a bare name
11. settings.errorWorkflow is '__WF__:<alias>', never a raw id
12. No settings.executionTimeout on any workflow containing a Wait node   (n8n#15123)
13. No Wait node with interval < 65s used as a durability boundary        (§4.3)
14. Slack-facing webhooks: Raw Body on, and a Respond node within 2 hops of signature verification
15. Every cron node sets timezone explicitly to America/Chicago
```

Rules 2 and 14 need reachability analysis over the connection graph including `Continue On Fail`
branches. ⚠️ The previous version estimated "an hour to write" for rule 2 — that is optimistic for a
correct implementation; budget half a day.

---

## 9. MCP usage policy

| Allowed | Forbidden |
|---|---|
| Authoring and iterating on `[dev]`-prefixed workflows | Touching any `[prod]` workflow |
| `validate_workflow` / `validate_node_config` | `publish_workflow` on anything |
| Searching templates for a starting point | Bypassing export → PR → CI |
| `test_workflow` against dev | Editing a live workflow to "fix" an incident |

The flow is always: **author on `[dev]` via MCP → `export.ts` → review the diff → PR → CI deploys to
`[prod]`.**

⚠️ On one instance this policy is **convention, not enforcement** — see §5.2. The MCP server can publish,
and cannot be scoped below Enterprise. The hourly drift job is what actually catches a violation.

`.mcp.json` is gitignored and resolves credentials from environment variables; `.mcp.json.example` is
committed with placeholders (§19 Step 0).

---

## 10. Corrections applied in this revision

| # | Was | Now | Impact if unfixed |
|---|---|---|---|
| 1 | credentials as `{id: "<name>"}` | `__CRED__:` placeholder resolved at deploy (§6.2) | Deploys green, throws on first execution |
| 2 | `active: true` set via `PUT` | separate activate route, `/publish`→`/activate` fallback (§6.4) | Workflows never activate |
| 3 | `/publish` assumed present | **absent on this instance**; version-tolerant fallback (§6.4) | Every deploy 404s |
| 4 | Three contradictory WF-12 triggers | sync-worker → signed webhook (§2) | Nothing triggers the main workflow |
| 5 | No secret for worker → n8n | `GRACE_N8N_WEBHOOK_SECRET` + HMAC scheme (§2.1) | Unauthenticated public webhook |
| 6 | Respond-to-Webhook last, after a 15-min Wait | ACK immediately after validation (§4) | Caller connection held open 15 min |
| 7 | "daily digest store" undefined | `POST /internal/digest/append` (§4.2) | P3 branch writes nowhere |
| 8 | Error workflow unnumbered, unbuilt | WF-00, in the inventory, lint-exempt (§3.2) | Lint rule 6 unsatisfiable |
| 9 | WF-18 had its own webhook + WF-12 timer | WF-12 owns the timer (§3.3) | Two competing escalation timers |
| 10 | Staff SMS via n8n Twilio node | via `/internal/notify/sms` (§3.4) | 10DLC/opt-out bypass; carrier-filtered, silent |
| 11 | WF-14 = "click Resolved" | also `/grace-kill`; raw Webhook + manual Slack signing (§3.1) | Slash command unimplementable as specced |
| 12 | strip node `position`/`pinData` by hand | `?excludePinnedData=true`; keep node `id` + `webhookId` (§6.1) | Diff churn; **changed prod webhook URL** |
| 13 | "six workflows move into code"; §17 D-7 "7 remain" | ten move, nine remain (§3) | Arithmetic wrong in two docs |
| 14 | two instances, I9 intact | one instance, ADR-0013, detection-based control (§5) | Security posture misstated |
| 15 | crons "03:15 CT" | explicit `America/Chicago` per workflow (§3) | CST/CDT ambiguity, instance-default drift |
| 16 | multi-tenancy unaddressed | hardcode + endpoint for Phase F, risk R-n8n-1 (§7) | Breaks at tenant two, unflagged |

**New assumptions for §17:** A-19 (`/grace-kill` authorization), A-20 (WF-18 voice call, Phase F),
A-21 (draft/publish availability on this instance).

---

## 11. Acceptance criteria

✅ **AC-09.1** `lint.ts` fails a deliberately broken workflow (missing respond node on an error branch).
✅ **AC-09.2** `export.ts` run twice against an unchanged instance produces byte-identical files.
✅ **AC-09.3** `deploy.ts --env prod` is impossible without the CI secret (clear failure locally).
✅ **AC-09.4** WF-12 delivers a P1 to Slack and SMS within 30s of a `staff.notify` outbox event.
✅ **AC-09.5** WF-12 responds 200 on every branch, verified by injecting a failure into each external node.
✅ **AC-09.6** No workflow JSON contains a credential value (secret-scanner clean).
✅ **AC-09.7** A P1 left unacknowledged 15 minutes triggers WF-18 in a test run with a compressed timer.
✅ **AC-09.8** Deploying a workflow with an unresolved `__CRED__:` placeholder **fails the deploy** — the
regression test for correction #1.
✅ **AC-09.9** `deploy.ts` activates successfully on an instance exposing only `/activate`, and on one
exposing `/publish` — correction #3.
✅ **AC-09.10** An unsigned or stale-timestamp POST to WF-12's webhook is rejected 401 — correction #5.
✅ **AC-09.11** The untagged `AI Agent workflow` already on the instance is untouched by
`deploy.ts --env prod` and is not reported as an orphan.
