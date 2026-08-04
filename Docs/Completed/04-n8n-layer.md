# 05 — n8n Layer

**Completed:** 3 August 2026 · **Commit:** `298c9fc` (+ Slack removal)
**Status:** 3 workflows live and active on `palmleafmassage.app.n8n.cloud`.

---

## Slack is out of scope — and that turned out to be an improvement

Slack is not on the platform list, so **every Slack node was removed**. All outbound
notification now goes through Core API:

```
n8n  →  POST /internal/notify/staff   (escalations)
     →  POST /internal/notify/ops     (workflow failures)
     →  POST /internal/notify/sms     (manager SMS)
```

This is better than the original design, not a downgrade:

- **n8n holds no third-party credentials at all** — one Header Auth credential, nothing else.
  The credential-bootstrap problem largely disappears.
- **The 10DLC bypass is closed uniformly.** Doc 09 §3.4 flagged that an n8n Twilio node
  bypasses the messaging adapter's opt-out, consent and STOP/HELP enforcement, meaning staff
  SMS would be carrier-filtered and escalations would fail silently. Routing everything
  through `/internal/notify/*` fixes that for every channel at once.
- **Adding Slack later needs no workflow change** — it becomes a Core API notification
  channel behind the same endpoint.

The cost: those three endpoints do not exist yet, so the workflows are structurally live but
have nothing to call. Recorded in `05-pending-and-blocked.md`.

---

## What is deployed

| Workflow | Id | Trigger | Job |
|---|---|---|---|
| `[dev] WF-00 Global Error Handler` | `TskMxWsdNPdtyzwz` | n8n error trigger | Every workflow's `errorWorkflow`. Posts workflow/node/error to ops — **never the failing payload**, which may contain caller utterances (I6). |
| `[dev] WF-12 Escalation & Alerting` | `Nig7UzGSTwVZuFLg` | signed webhook | The reference workflow. HMAC verify → ACK → route by priority → P1 notify + SMS + 15-min unacknowledged check → WF-18. |
| `[dev] WF-18 On-call Escalation` | `IvXEhYoHdxT3e7oA` | called by WF-12 | Repeat SMS → wait 30 min → recheck → final P1. Stops short of a voice call (Phase F, A-20). |

All three tagged `managed:git` + `env:dev` and **active**. The pre-existing `AI Agent workflow`
is untagged and correctly ignored by the deploy filter.

Credential `PalmLeaf Core API (dev)` (`MLPOdQtg1zcSlYUJ`) — Header Auth, **placeholder token**,
must be rotated when Core API is real.

---

## WF-12 shape

```
Webhook (POST, rawBody, responseNode, path prod/escalation)
  → Verify signature      HMAC-SHA256 over `${timestamp}.${rawBody}`, ±300s skew, timing-safe
  → Authenticated?        ──false──► Respond 401
  → Respond 200           ← ACK HERE. Everything below is fire-and-forget.
  → Switch on priority
      P1 → Notify staff (@here) → SMS manager → Wait 15 min → recheck → WF-18
      P2 → Notify staff
      P3 → Append to digest
```

**The ACK placement is the correction.** The original responded *after* a 15-minute Wait,
which would have held the HTTP connection open for 15 minutes and timed out the caller.

Wait nodes are 15 and 30 minutes — both above the 65-second threshold at which n8n offloads
the execution to the database, so they survive a Cloud restart. Under 65s they would not.

---

## Tooling

### `lint.ts` — 15 rules

POST + `responseNode`; every path reaches a Respond node (graph reachability); no hardcoded
secrets; no localhost/tunnel URLs; HTTP nodes have timeouts; `errorWorkflow` set (WF-00
exempt); filename ↔ name with no committed env prefix; no `pinData`; explicit `{{ENV}}/`
webhook paths; `__CRED__:` credential ids; `__WF__:` workflow refs; no `executionTimeout`
beside a Wait; no sub-65s durability Wait; Slack webhooks need rawBody + a near respond node;
crons pin `America/Chicago`.

**Verified (AC-09.1):** injecting five defects produced five failures —

```
[rule 12]  Wait node + settings.executionTimeout, which would kill it mid-wait
[rule 14]  webhook must enable Raw Body (signatures cover exact bytes)
[rule 10]  credential slackApi.id must be __CRED__:<alias>, got "PalmLeaf Slack (prod)"
           (n8n resolves credentials strictly by id — a name deploys green and throws at runtime)
[rule  5]  HTTP node "SMS manager" has no timeout
[rule 13]  Wait node is 30s; under 65s it is lost on restart
```

then green again after restore.

### `deploy.ts`

Tag-filtered (`?tags=managed:git,env:dev`), resolves `__CRED__:`/`__WF__:` placeholders,
applies the env name and webhook-path prefix, PUTs exactly `{name, nodes, connections,
settings}`, tags, activates, fails on orphans.

**Verified (AC-09.8):** an unresolved credential placeholder aborts the deploy *before*
touching the instance, with the reason and the fix. That is the defect doc 09 called the worst
in the document — n8n would otherwise accept and activate the workflow, then throw on its
first execution.

---

## Three deploy defects found by actually deploying

| # | Defect | Fix |
|---|---|---|
| 1 | `/publish` returns **405**, not 404 — the fallback only caught 404 | Fall back on both. Activated via `/activate` (AC-09.9). |
| 2 | n8n refuses to publish a workflow whose sub-workflow is unpublished | Topological activation: build a dependency graph from `__WF__:` refs and activate in order. |
| 3 | Failed runs left **untagged orphan duplicates** — the placeholder-creation pass ran before later steps aborted | Tag placeholders immediately at creation, so a partial run stays inside the managed set. Three orphans deleted. |

Defect 2 also exposed a bug in my own fix: the activation loop bounded `pass` against
`queue.length`, which shrinks each iteration, so it exited one pass early and silently left
the last workflow unactivated. Bounded on the original length instead.

---

## Not done in this area

- **`export.ts` is still a stub.** AC-09.2 (export twice → byte-identical) is unverified.
- **WF-18 re-reports drift on every `--apply`.** n8n materialises node defaults and the
  comparison is not normalised, so the deploy is not yet idempotent. It converges — it just
  does redundant writes. Needs the same `normalise()` treatment the Vapi drift check has.
- **Six workflows not built:** WF-07, WF-11, WF-14, WF-15, WF-16, WF-17.
  WF-14 is deferred with Slack (it is entirely Slack interactivity + slash command).
- **No live execution has ever run.** WF-12 has never received a signed request; AC-09.4,
  AC-09.5, AC-09.7 and AC-09.10 are all unverified.
- `GRACE_N8N_WEBHOOK_SECRET` is defined in the design but not set on the instance.
- No prod deploy; `env:prod` tag does not exist yet.
