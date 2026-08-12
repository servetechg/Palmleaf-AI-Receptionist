# 04 — n8n Orchestration Layer

**Status:** Active
**Read before:** authoring or deploying any workflow.
**Implements:** ADR-0002, ADR-0010, ADR-0013
**Enforces:** I8, I9
**Last verified:** 2026-08-05 against the live instance `palmleafmassage.app.n8n.cloud` and the thirteen workflow JSON files in `platform/n8n/workflows/`.

> **In one paragraph:** this document settles what n8n is allowed to own, how work reaches it,
> what each workflow does, and how workflows are linted and deployed as code. It draws a hard
> line that earlier revisions blurred: **three workflows run real work today (WF-20/21/22, §5),
> and three are correct but completely dormant (WF-00/12/18, §4)** because every endpoint they
> call belongs to a Core API that does not exist yet. It deliberately does **not** document each
> workflow node-by-node; that is generated into [Docs/generated/workflows/](../generated/workflows/).
>
> **Acceptance-criterion IDs keep the `AC-09.x` prefix** from this document's former number —
> they are cited as delivery evidence in [`Docs/Completed/`](../Completed/00-STATUS.md).

> **Verification status.** Every API claim below was probed on **3 August 2026** against the live
> instance `palmleafmassage.app.n8n.cloud` with the project's own API key, and cross-checked against
> n8n's public-API OpenAPI source. Endpoint availability differs between n8n versions — **§4.4 records
> what this instance actually exposes today**, and `deploy.py` is written to tolerate both shapes.
>
> The previous version specified a credential-normalisation scheme that deploys green and then throws at
> first execution, and told `deploy.py` to set `active` via `PUT`, which is read-only. §12 lists every
> correction.

---

## 1. What n8n owns — and what it does not

Per ADR-0002, n8n is **not** on the synchronous voice path. It owns the operational plumbing where its
strengths — visual routing, connector breadth, and editability by a non-developer — are real advantages.

| n8n owns | Core API / workers own |
|---|---|
| Staff notification fan-out (email, SMS, on-call) | Vapi tool endpoints |
| Escalation routing and rota logic | Availability and booking |
| Daily/weekly operational digests | Outbox dispatch |
| Nightly reconciliation *reporting* (not the reconciling) | PMS/Calendar/Stripe/Twilio adapter calls |
| Ad-hoc client-requested integrations (CRM, reviews, marketing) | Anything with a latency budget |
| Manual staff actions (approve a task, resend a link) | Anything transactional |
| Vagaro webhook *fan-out* to secondary consumers | Vagaro webhook *ingestion* (needs the 20s ACK) |

> **Boundary rule:** if it has a latency budget, a transaction, or money attached, it is not an n8n
> workflow. If it is a notification, a report, or something the client may want to tweak, it is.
>
> WF-07 and WF-20 touch money-adjacent data (reconciliation, deposits outstanding) but are **read-only
> reporting** — they observe, never write. That is the line.

n8n reaches the system through `POST /internal/*` endpoints on the Core API with a bearer token — it
never touches Postgres directly. That keeps RLS, validation, and the state machine intact.

---

## 2. How work reaches n8n

The previous version gave three mutually incompatible answers ("Webhook from Core API" in §2 and §3,
`staff.notify` outbox in AC-09.4) while [core-api](../reference/core-api.md) §16 and [01-architecture](01-architecture.md) both **forbid Core API from calling n8n**.

**Resolved:** the cold path calls n8n. Core API never does.

```
tool handler (hot path)
  └─ writes staff_tasks row + outbox row `staff.notify`   [one transaction]
                                   │
                          sync-worker picks it up          [cold path]
                                   │
                          HMAC-signed POST ──────────────► n8n WF-12
```

This is the only reading consistent with ADR-0002, [core-api](../reference/core-api.md) §16, [01-architecture](01-architecture.md) and AC-09.4. The same path serves
WF-17 (via a new `webhook.fanout` outbox event) and WF-18.

### 2.1 Outbound authentication — n8n's native Header Auth

Every *inbound* direction has a secret (`GRACE_VAPI_WEBHOOK_SECRET`, `GRACE_VAGARO_WEBHOOK_TOKEN`,
`GRACE_STRIPE_WEBHOOK_SECRET`, `GRACE_TWILIO_AUTH_TOKEN`). Worker → n8n had none;
[05-security-and-compliance](05-security-and-compliance.md)'s auth matrix has no row for it either.

**The scheme, as actually built.** Both inbound webhooks — WF-12 and WF-17 — set the Webhook
node's `authentication: "headerAuth"` and attach the `n8n-inbound` Header Auth credential. n8n
verifies the header **before the workflow starts**, so an unauthenticated POST never reaches a node
and never costs an execution.

```
Credential (created by hand, once per environment, never committed):
  alias   n8n-inbound
  names   "PalmLeaf n8n Inbound (dev)" / "(prod)"
  type    Header Auth  —  a header name and a >=32-character bearer value

sync-worker sends that header on every POST to WF-12 / WF-17.
Raw Body stays ON (lint rule 14) so the body arrives as exact bytes for the parse node.
```

The earlier design in this section — an `x-grace-signature` HMAC over `timestamp.rawBody`, verified
in a Code node reading `GRACE_N8N_WEBHOOK_SECRET` — was replaced by the Header Auth scheme above,
because a Code node on n8n Cloud can read neither the environment nor a credential (Q-04.5, §7.1);
that env var no longer exists anywhere in the workflow set.

The trade-off, stated plainly and unchanged from §7.1: a bearer token proves the *caller*, whereas
an HMAC over the body proves the caller **and** that the bytes were not altered, and gives replay
protection via the timestamp. Over TLS, on an internal worker-to-n8n hop, with a 32-character
secret, the bearer is defensible — and it is the only one of the two that functions on this tier.

Add the matching row to [05-security-and-compliance](05-security-and-compliance.md)'s auth matrix. Rotation follows the same current+previous 24h window as
every other secret ([infrastructure](../reference/infrastructure.md)).

---

## 3. Workflow inventory

Renumbered from the design brief §13 to reflect the ADR-0002 split.

| ID | Workflow | Trigger | Owner | Notes |
|---|---|---|---|---|
| `WF-00` | **Global Error Handler** | n8n error trigger | n8n | ★ New. Every workflow's `errorWorkflow` points here. See §3.2. |
| `WF-01` | ~~Tool Router~~ | — | **→ Core API** | Moved. ADR-0002. |
| `WF-02` | ~~Availability Query~~ | — | **→ Core API** | Moved. |
| `WF-03` | ~~Create Booking~~ | — | **→ Core API** | Moved. |
| `WF-04` | ~~Reschedule/Cancel~~ | — | **→ Core API** | Moved. |
| `WF-05` | ~~Vagaro Webhook Receiver~~ | — | **→ Core API** | Moved — the 20s ACK needs a fast dedicated endpoint. |
| `WF-06` | ~~Vagaro Poller~~ | — | **→ sync-worker** | Moved. |
| `WF-07` | **Nightly Reconciliation Report** | Called by WF-25 (was its own cron) | n8n | ★ **Built & deployed.** Records a row either way, then hands the summary to WF-26 to email. §8, §10.5. |
| `WF-08` | ~~Track B Worker~~ | — | **→ booking-worker** | Moved. |
| `WF-09` | ~~SMS Dispatcher~~ | — | **→ sync-worker** | Moved — must be transactional with the outbox. |
| `WF-10` | ~~Payment Handler~~ | — | **→ Core API webhook** | Moved — signature verification + state machine. |
| `WF-11` | **Hourly Call Digest** | Called by WF-25 (was its own cron) | n8n | ★ **Built & deployed.** Staff digest of normal activity — distinct from WF-22, which reports faults. §8, §10.5. |
| `WF-12` | **Escalation & Alerting** | Signed webhook from sync-worker | n8n | ★ The reference workflow. §4. |
| `WF-13` | ~~Hold Expiry Sweeper~~ | — | **→ sync-worker** | Moved — 30s cadence, transactional. |
| `WF-15` | ~~Daily Operations Digest~~ | — | **→ WF-20** | **Merged.** Same schedule and purpose as WF-20. When Core API exists, WF-20 gains bookings, open tasks and deposits outstanding — it is not a second workflow. |
| `WF-16` | ~~Weekly QA Sampler~~ | — | **→ WF-21** | **Merged.** Identical name, schedule and description to WF-21. Two workflows would have fired at Mon 09:00 doing the same job. |
| `WF-17` | **Vagaro Webhook Fan-out** | Signed webhook from sync-worker | n8n | ★ **Deployed and active.** The `n8n-inbound` credential now exists — see §7.2. |
| `WF-19` | **Platform Heartbeat** | Cron every 15 min | n8n | ★ **Runs today.** Proves n8n is alive and Vapi is reachable. §6. |
| `WF-18` | **On-call Escalation** | Called by WF-12 | n8n | P1 unacknowledged 15 min → SMS manager → 30 min → call manager. §3.3. |
| `WF-20` | **Daily Call Digest** | Called by WF-25 (was its own cron) | n8n | ★ **Runs today.** Yesterday's calls from the Vapi API. §5, §10.5. |
| `WF-21` | **Weekly QA Sampler** | Called by WF-25 (was its own cron) | n8n | ★ **Runs today.** 20 random calls with recording links. §5, §10.5. |
| `WF-22` | **Call Quality Alert** | Called by WF-25 (was its own cron) | n8n | ★ **Runs today.** Errored, ultra-short, or escalated calls. §5, §10.5. |
| `WF-23` | **Core API Report Fetch** | Called by WF-07/WF-11 | n8n | ★ New library sub-workflow. The "fetch a report, degrade gracefully" logic, written once. §10.5. |
| `WF-24` | **Vapi Call Fetch & Normalise** | Called by WF-20/21/22 | n8n | ★ New library sub-workflow. The "fetch calls, extract per-call fields" logic, written once. §10.5. |
| `WF-25` | **Reporting Orchestrator** | Five crons, America/Chicago | n8n | ★ New. The single on/off switch for all five reports. §10.5. |
| `WF-26` | **Send Report Email** | Called by WF-07/20/21/22 | n8n | ★ New library sub-workflow. Takes `{subject, body}`, sends one email. Blocked on the `smtp` credential. See the library-sub-workflows subsection under §10. |

**Net: ten workflows move into code; fourteen files remain in n8n** (WF-00, 07, 11, 12, 17, 18,
19, 20, 21, 22, 23, 24, 25, 26). Only **five of them are entry points** — WF-00 (error trigger),
WF-12 and WF-17 (webhooks), WF-19 (heartbeat cron) and WF-25 (the five report crons). The other
nine are sub-workflows whose only trigger is `executeWorkflowTrigger`, so they cannot fire unless
a parent calls them. **That is the one-stop property:** deactivating WF-25 stops all five reports
at once, because none of them owns a schedule any more. ~~WF-14~~ is withdrawn — it served a chat
platform that is out of scope. ~~WF-15~~ and ~~WF-16~~ are **merged into WF-20 and WF-21**, which
already do their jobs against Vapi directly; when Core API exists those two gain the extra fields
rather than being duplicated.

**Every workflow in this inventory is now built.** Nothing is left to implement — what remains is
configuration. Four run and produce output today (WF-19/20/21/22, reading Vapi directly); three are
correct but inert until Core API exists (WF-00/12/18); three are built and deployed but report
"Core API unreachable" until that service arrives (WF-07/11/17); one is written but not deployed at
all (WF-26, skipped until the `smtp` credential exists). See §8.

> ⛔ Two older counts were both wrong. An earlier revision said "six workflows move into code", and
> [09-open-decisions](09-open-decisions.md) D-7 said "7 workflows in n8n, 6 moved into code".
> Strike-through rows number ten, and the surviving set is eleven once WF-00 and the three new
> reporting workflows are counted. Corrected here and in [09-open-decisions](09-open-decisions.md).

> **Only four of these fourteen can do anything today.** WF-19, WF-20, WF-21 and WF-22 read the
> Vapi API (WF-20/21/22 now through WF-24) and need nothing else. The rest call Core API endpoints
> that do not exist, or are plumbing for the ones that do — so they are published, correct, and
> inert — see §4. Earlier revisions did not say so, which is why the n8n dashboard looked broken
> rather than pending.

**Cron timezone.** All crons run `America/Chicago`, set explicitly on the workflow that owns the
schedule — do not rely on the instance default, and do not write "CT" (ambiguous between CST/CDT).
Only two files now carry a schedule trigger at all: WF-25 (the five reports) and WF-19 (the
heartbeat). WF-25's 03:15 branch deliberately trails the reconciliation job that finishes by 03:00
([01-architecture](01-architecture.md)); that ordering is a real dependency.

### 3.1 WF-14 is withdrawn, not deferred

Earlier revisions gave WF-14 ("Staff Action Handler") two jobs: an interactive "Resolved" button,
and a `/grace-kill` slash command that was the kill switch's only human-triggerable surface. Both
were surfaces on a chat platform that is **out of scope**, and both were harder than the one-line
description admitted — neither is served by n8n's trigger node for that platform, so each needed a
raw webhook plus hand-written signature verification.

**The workflow is removed rather than rewritten.** What mattered about it survives elsewhere:

| What WF-14 did | Where it lives now |
|---|---|
| Staff marks a task resolved | `POST /internal/tasks/:id/resolve` — a Core API endpoint, callable from any future staff surface |
| `/grace-kill` kill switch | The runbook procedure in [runbooks](../reference/runbooks.md) §28, against `POST /internal/tenants/:slug/kill-switch` |

> ⚠️ **The kill switch no longer has a one-click surface.** It is an authenticated API call made by
> someone following a runbook. That is slower under pressure than a button, and it is a real
> regression — recorded honestly here rather than quietly dropped. Restoring a one-click surface is
> a Phase F task and belongs with the staff dashboard, not with a chat integration.

Assumption **A-19** (who may invoke `/grace-kill`) is retired with the workflow. The authorization
question does not disappear — it moves to whoever builds the next staff surface, and is re-raised
in [09-open-decisions](09-open-decisions.md).

### 3.2 WF-00 — the global error handler

The previous version required `errorWorkflow` on every workflow (checklist + lint rule 6) but never
created the workflow, never gave it a number, and never put it in the inventory or in task C-13.

WF-00 receives n8n's error trigger and posts to `#palmleaf-ops-log` with workflow name, execution id,
node, and error message. It is **exempt from lint rule 6** (it cannot point at itself) — the lint must
encode that exemption explicitly.

> **There is no alert anywhere for "n8n is down."** [observability](../reference/observability.md)'s 24 alerts contain none, and [booking-write-path](../reference/booking-write-path.md)'s failure
> catalogue has no n8n row. Under ADR-0002 n8n is off the call path, so the brief's old detection
> ("n8n unreachable → tool timeout → Grace apologises") no longer exists and nothing replaced it. If n8n
> dies, **every P1 staff escalation disappears silently.** Add to [observability](../reference/observability.md): a heartbeat workflow plus a
> "no n8n execution in 60 min" alert at P2. Carried into [EXECUTED-vapi-n8n-plan](../Completed/EXECUTED-vapi-n8n-plan.md) §A4.

### 3.3 WF-18 has no independent trigger

The previous version gave WF-18 trigger "Webhook" *and* had WF-12's P1 branch call it after a Wait —
two escalation timers with no arbitration. **Resolved:** WF-12 owns the timer and invokes WF-18 directly.
WF-18 has no webhook of its own.

⚠️ WF-18's final step is "call manager". Nothing specifies how a voice call is placed:
`VoicePort.createOutboundCall` is Phase F ([provider-adapters](../reference/provider-adapters.md)), and a direct Twilio Voice node is not specified
either. Until Phase F, WF-18 terminates at a repeat SMS plus a P1 staff notification. Do not silently drop the
escalation. Logged as **A-20**.

### 3.4 Staff SMS bypasses the messaging adapter — must be fixed

WF-12 and WF-18 SMS the manager from an **n8n Twilio node**. [provider-adapters](../reference/provider-adapters.md) states messaging rules are
"enforced **inside the adapter**, so no caller can bypass them" — opt-out enforcement, consent checks,
STOP/HELP footer, and the `GRACE_SMS_10DLC_READY` gate behind **GATE-09**.

An n8n Twilio node bypasses all of it. Unregistered staff SMS will be **carrier-filtered**, and the
escalation path fails silently — the exact failure mode the escalation exists to prevent.

**Decision:** WF-12/WF-18 send staff SMS by calling `POST /internal/notify/sms`, never a Twilio node.
Every staff-facing notification channel goes through `/internal/notify/*` for the same reason —
consent, opt-out and 10DLC enforcement then live in exactly one place and cannot be bypassed by
adding a node to a canvas. Also resolves the duplicated Twilio credential noted in
[05-security-and-compliance](05-security-and-compliance.md) §18's threat model.

---

## 4. WF-12, WF-00 and WF-18 — correct, published, and dormant

These three are the escalation scaffolding. They are deployed and tagged, they lint clean, and
**none of them can run**, because every HTTP node in them calls a Core API endpoint that does not
exist yet. Saying so plainly is the point of this section: they are pending, not broken.

WF-12 is the reference workflow — the shape every future webhook-triggered workflow copies.

```
[Webhook]  POST /{{ENV}}/escalation, Raw Body ON, responseMode=responseNode
           authentication=headerAuth, credential n8n-inbound (§2.1)
           n8n rejects an unauthenticated POST here, before any node runs
      │
      ▼
[Respond 200]     ← ACK EARLY. Everything below is fire-and-forget.
      │
      ▼
[Parse event]     Code node — parses the raw bytes into the fields below
      │
      ▼
[Route by priority]
  ├─ P1 ──► [Notify P1]  POST /internal/notify/staff
  │           └─► [SMS manager]  POST /internal/notify/sms      (§3.4, never a Twilio node)
  │                 └─► [Wait 15 min] ─► [Still unacknowledged?]  GET /internal/tasks/:id
  │                        └─► [Escalate to on-call] ─► WF-18
  ├─ P2 ──► [Notify P2]        POST /internal/notify/staff
  └─ P3 ──► [Append to digest] POST /internal/digest/append      (§4.2)
```

> **This diagram is now generated-and-checked, not hand-drawn.** Earlier revisions carried an ASCII
> sketch that **contradicted the deployed workflow** — it showed chat-platform nodes that were never
> built and a `default` branch that does not exist. The authoritative node-by-node listing, with the
> live workflow ID and a mermaid graph, is
> [Docs/generated/workflows/WF-12.md](../generated/workflows/WF-12.md), written by `make docs` from
> the workflow JSON itself. If this sketch and that page ever disagree, **the generated page is
> right** — and the disagreement is a bug in this document.

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
- [ ] `authentication: "headerAuth"` on the Webhook node with the `n8n-inbound` credential (§2.1) —
      n8n verifies before the workflow starts, so no verification node is needed or wanted
- [ ] "Continue On Fail" on external nodes, with the failure branch routed to a respond node
- [ ] `errorWorkflow` set to WF-00
- [ ] **No `settings.executionTimeout`** if the workflow contains a Wait node (see §4.3)
- [ ] Workflow published

### 4.2 The "daily digest store" — now a real endpoint

The previous P3 branch said `[Append to daily digest store]`. **That store was defined nowhere** — not a
table in [data-model](../reference/data-model.md), not Redis, not n8n static data. Replaced with `POST /internal/digest/append`, backed by a
real table. This is one of five `/internal/*` endpoints that doc 09 assumed and doc 04 never declared —
all now carried into [EXECUTED-vapi-n8n-plan](../Completed/EXECUTED-vapi-n8n-plan.md) §A4 for the [core-api](../reference/core-api.md) §4 route table:

| Endpoint | Consumer |
|---|---|
| `GET /internal/reports/reconciliation` | WF-07 |
| `GET /internal/reports/calls?window=1h` | WF-11 |
| `GET /internal/reports/daily` | WF-20, once Core API exists — it currently reads Vapi directly |
| `GET /internal/reports/qa-sample?n=20` | WF-21, same |
| `POST /internal/digest/append` | WF-12 P3 |
| `POST /internal/notify/sms` | WF-12, WF-18 (§3.4) |
| `GET /internal/tenants/:slug/settings` | all — see §11 |

**Containment** deserves special note: it exists only as the Prometheus gauge
`grace_containment_ratio{tenant}` ([observability](../reference/observability.md) §70), and `/metrics` is network-restricted ([core-api](../reference/core-api.md)). WF-15 cannot
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
- Execution retention on lower Cloud tiers is limited (see §6.1). A waiting execution can be pruned before
  it resumes if the wait outlives retention. 15–30 minutes is safe; **never design a multi-day wait.**

---

## 5. WF-20, WF-21, WF-22 — the workflows that do real work today

These three exist because the others cannot run. They read **the Vapi call API** — through WF-24
since the consolidation (§10.5) — so they depend on nothing that is blocked: no Core API, no
Postgres, no Vagaro, no phone number. They are the reason the n8n dashboard shows genuine activity.

| ID | Workflow | Schedule | What it reports |
|---|---|---|---|
| `WF-20` | **Daily Call Digest** | 07:30 America/Chicago, from WF-25 | Yesterday's calls: total, booked, escalated, medical holds, average duration, containment rate |
| `WF-21` | **Weekly QA Sampler** | Mon 09:00 America/Chicago, from WF-25 | 20 random calls with recording links and the structured outcome, for human review |
| `WF-22` | **Call Quality Alert** | hourly, from WF-25 | Calls that errored, ended under 15 seconds, or escalated — the signals that mean something is wrong |

Each has the same shape — six nodes since the WF-24 extraction (§10.5), and the same six in all
three, which is the point:

```
[Called by WF-25]                      executeWorkflowTrigger; no schedule of its own
      ▼
[Code: shape the request]              window and page size — the only per-report difference
      ▼
[Execute Sub-workflow: WF-24  → Vapi]  the shared fetch + per-call normalise
      ▼
[Code: analyse]                        counts, rates, sampling — no PHI, no transcripts
      ▼
[Data Table: insert]                   works today, visible in the n8n UI
      ▼
[Postgres: insert]  ← DISABLED         the durable path, switched on later (§8)
```

**One new credential covers all three:** a Vapi API key as Header Auth
(`Authorization: Bearer <key>`), aliased `vapi` — held by WF-24 now, not by each report.
That is the entire prerequisite.

**What they deliberately do not collect.** No transcript, no caller name, no phone number, no
health detail — invariant **I6** applies to reporting exactly as it applies to the call path.
Recording URLs are *pointers into Vapi*, governed by Vapi's retention; nothing is copied out. A
reporting pipeline is the easiest place to accidentally create a second, unlogged copy of
sensitive data, so the constraint is stated here rather than assumed.

**A quiet day must still produce a report.** If no calls happened, these workflows emit a zero row
rather than nothing. A missing report is ambiguous — it could mean no calls, or a broken workflow,
and those need different responses. A zero row is unambiguous.

> ⚠️ **They will return empty results until Grace takes a real call.** They run, they succeed, and
> they have nothing to report yet. That is expected, and is not a defect to investigate.

Node-by-node detail, credentials and live workflow IDs:
[WF-20](../generated/workflows/WF-20.md) · [WF-21](../generated/workflows/WF-21.md) ·
[WF-22](../generated/workflows/WF-22.md).

---

## 6. WF-19 — the platform heartbeat

**The gap this closes.** Under ADR-0002 n8n sits off the call path, which is right for latency but
removed the only way we used to notice it had died: an n8n outage no longer surfaces as a tool
timeout. Nothing replaced that. **If n8n stops, every P1 staff escalation disappears silently** —
no alert exists for it anywhere in [observability](../reference/observability.md).

WF-19 runs every 15 minutes and does two things:

1. **Writes a heartbeat row** to the `platform_heartbeat` Data Table, recording the gap since the
   previous beat. The previous timestamp is kept in n8n's per-workflow static data, so no read-back
   node is needed.
2. **Probes Vapi** with a one-record call fetch. This is a real dependency check rather than a ping:
   it proves the API answers *and* that our key is still accepted.

The HTTP node sets `neverError` with `fullResponse`, so a 4xx or 5xx arrives as data instead of
throwing. A Vapi outage is then *recorded* rather than destroying the heartbeat that was supposed to
report it — without that, the workflow would fail exactly when its output matters most.

**A gap materially over 15 minutes means n8n missed a window.** The row is written with
`healthy: false` and a reason naming the gap in minutes.

> ⚠️ **State the limit plainly: this cannot alert while n8n is fully down.** Nothing runs, so nothing
> raises the alarm. What it does give is continuous proof of liveness, detection of a missed window
> once n8n returns, and — the genuinely new coverage — a Vapi outage or revoked key caught within 15
> minutes, which today has no detection at all.
>
> A true dead-man's switch needs a watchdog **outside** n8n. Recorded as **Q-04.4**; the cheapest
> version is an external cron that reads the heartbeat table and alerts on staleness.

---

## 7. WF-07, WF-11, WF-17 — built ahead of the access we are waiting on

These three complete the inventory. **Nothing about them is left to implement** — every node,
schedule, query, table and error path exists. What remains is configuration: a credential, a URL,
an email account.

That is the deliberate strategy of this phase. Vagaro, email, RingCentral and a phone number are
all outstanding, and building the workflows *now* means the day access arrives is a day of
configuration rather than a day of development.

| ID | Runs | Reads | Writes | What is still needed |
|---|---|---|---|---|
| **WF-07** Nightly Reconciliation | 03:15 daily, from WF-25 | Core API `/internal/reports/reconciliation`, via WF-23 | `reconciliation_reports` | Core API; the `smtp` credential and `GRACE_REPORTS_EMAIL_TO`, which WF-26 needs |
| **WF-11** Hourly Call Digest | hourly at :20, from WF-25 | Core API `/internal/reports/calls?window=1h`, via WF-23 | `call_digests` | Core API |
| **WF-17** Vagaro Fan-out | authenticated webhook | the worker's `webhook.fanout` event | `fanout_log` | the `n8n-inbound` credential; consumer URLs |

WF-07 and WF-11 no longer hold a fetch node at all: each shapes a `{path}` and hands it to WF-23,
which owns the HTTP call and returns `{ok, statusCode, body, unreachableMessage}` (§10.5). Their
schedules moved to WF-25.

**WF-07 no longer owns an email node either.** It used to carry a disabled `emailSend` node whose
`toEmail` read `{{ $json.email_to }}` — a field nothing upstream ever set, so enabling it would have
sent to an undefined recipient. That node is deleted. WF-07 now saves its row, shapes
`{subject, body}`, and calls **WF-26** (§10.5), which owns the single `emailSend` node and gets its
recipient from `GRACE_REPORTS_EMAIL_TO` at deploy time. Until the `smtp` credential exists, WF-26 is
skipped by `deploy.py` — written and committed, not deployed.

**They already run rather than crash.** WF-23's fetch sets `neverError` with `fullResponse`, so a
missing Core API arrives as data and the calling workflow records a row saying *"Core API
unreachable — not yet built"*. That is the same reasoning as the quiet-day zero row in §5: a report
that says it could not run is useful, and silence is indistinguishable from a broken workflow.

**WF-11 is not a duplicate of WF-22.** WF-11 reports *normal activity* — calls, bookings, open
staff tasks — and reads Core API because Vapi cannot know about bookings or tasks. WF-22 reports
*faults*. Both run hourly; they answer different questions.

### 7.1 Both webhooks use n8n's native header auth, not an HMAC in a Code node

WF-12 used to verify its inbound signature inside a Code node, which **cannot work on n8n Cloud** —
a Code node can read neither the environment nor a credential (Q-04.5). WF-17 avoided that from the
start by using the Webhook node's built-in **Header Auth**, which n8n verifies itself before the
workflow runs.

The trade-off, stated plainly: a bearer token proves the *caller*, whereas an HMAC over the body
proves the caller **and** that the bytes were not altered, and gives replay protection via the
timestamp. Over TLS, on an internal worker-to-n8n hop, with a 32-character secret, the bearer is
defensible — and it is the only one of the two that functions on this tier.

**WF-12 was migrated to the same scheme on 5 August 2026, closing Q-04.5.** Its "Verify signature",
"Authenticated?" and "Respond 401" nodes are gone; a "Parse event" Code node does nothing but read
the raw body. That removed the last `$env` read in the workflow set, so lint's
`ENV_ACCESS_KNOWN_BLOCKED` allowlist is now **empty** and must stay empty — rule 17 has no
exceptions left to hide behind.

### 7.2 WF-17 and WF-12 — deployed, still waiting on a caller

Both were held back by `make n8n-apply`'s skip-on-missing-credential behaviour (§8) until the
`n8n-inbound` credential existed on the instance — n8n would otherwise accept a workflow
referencing a missing credential and throw on first execution, the failure mode lint rule 14 and
AC-09.8 exist to prevent. **The credential was created on 5 August 2026; both deployed and
activated on the next `make n8n-apply` run, with no further changes needed.**

Being deployed is not the same as being useful: WF-17 will acknowledge and log a signed fan-out
event today, and WF-12 will accept a signed escalation, but nothing yet sends either one — the
caller for both is the Core API worker, which does not exist. They are correctly published and
correctly idle, the same state as WF-00 and WF-18 in §4.

---

## 8. One Cloud instance — dev and prod by convention (ADR-0013)

We have a **single n8n Cloud instance**. The previous §4.2 assumed two (`n8n-dev` on :5679 + `n8n-prod`,
CI-only). That model is what invariant **I9** relied on, so I9 is deliberately relaxed — see ADR-0013 in
[01-architecture](01-architecture.md), and read §6.2 before assuming this is safe.

| Axis | Dev | Prod |
|---|---|---|
| Workflow name | `[dev] WF-12 Escalation & Alerting` | `[prod] WF-12 Escalation & Alerting` |
| Committed file | `WF-12-escalation-alerting.json`, name **unprefixed** | same file |
| Tags | `env:dev`, `managed:git` | `env:prod`, `managed:git` |
| Webhook `path` | `dev/escalation` | `prod/escalation` |
| Credentials | `PalmLeaf Vapi (dev)` | `PalmLeaf Vapi (prod)` |
| `errorWorkflow` | `[dev] WF-00` | `[prod] WF-00` |

One committed, environment-neutral file per workflow; the environment is materialised at deploy time.

**One credential per environment, per alias.** The dev and prod Vapi keys are distinct credentials
with distinct names; the workflow JSON names neither, only the alias.

### 6.1 What this instance actually provides

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
§10 correctly ignores both — a useful accidental test of the scheme.

**Plan-tier constraints to design around:** shared concurrency and execution retention across dev *and*
prod on one instance — a dev test loop can consume prod's quota. Keep WF-16 (20 calls weekly) and any
polling workflow dev-disabled until the tier is raised.

### 6.2 Residual risk versus true I9 — state honestly

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
   `/publish` route is absent on this instance (§6.1) even though `activeVersion` appears in the workflow
   payload — so do not lean on this argument until the route exists. Logged as **A-21**.

**Exit criteria for ADR-0013:** move to true two-instance environments the moment the account reaches a
tier with environments/source-control, or the moment a second client shares the instance.

---

## 9. Postgres — skeleton now, wired later

The reporting workflows write to **n8n Data Tables**, which work today and are viewable in the n8n
UI, but are capped in size and cannot be queried with SQL. Postgres is the durable answer, and it
is blocked for one mundane reason: **n8n Cloud cannot reach a database running on a laptop.** It
needs a hosted instance — a Neon or Supabase free tier is sufficient.

Rather than defer the design until then, the persistence path ships **present but switched off**:

1. **A disabled Postgres node** already sits after the Data Table write in each of WF-20/21/22,
   with its query written and its credential referencing `__CRED__:postgres`.
2. **`platform/postgres/schema.sql`** defines `call_metrics` (one row per day), `call_samples`
   (calls chosen for review) and `call_flags` (calls that tripped a quality signal).
3. **`credentials.example.json`** lists `postgres` under `deferred`, with the blocker and the
   enabling steps recorded next to it.
4. **The n8n linter gained rule 14** (§12), permitting a *disabled* node to hold an unresolved
   `__CRED__:` placeholder. Without that exemption the existing hard-fail on unresolved
   placeholders — which is the correct default, and catches a real class of runtime breakage —
   would block every deploy.

That fourth point is the one that makes this work rather than merely look tidy. Shipping a
half-wired integration normally means weakening a safety check for everyone; scoping the exemption
to disabled nodes keeps the check at full strength everywhere it matters.

**Turning it on is five steps and no redesign:** create the hosted database, run `schema.sql`, add
a `PalmLeaf Postgres (dev)` credential in n8n, enable the node in each workflow, `make n8n-apply`.
No workflow is restructured and no document changes.

---

## 10. Workflows-as-code

```
platform/n8n/
├── workflows/
│   ├── WF-00-global-error-handler.json
│   ├── WF-12-escalation-alerting.json
│   └── ...
├── lint.py                 # structural checks (§11)
├── export.py               # pull from the instance → normalise → write files
├── deploy.py               # tag-filtered push, activate, verify
└── credentials.example.json
```

### 10.1 Normalisation on export

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
credentials (§10.2). Keys are sorted so diffs are deterministic.

### 10.2 Credentials — the previous scheme was broken

> ⛔ The previous §4.1 reduced credential objects to `{ id: "<name>", name: "<name>" }`. **n8n resolves
> credentials strictly by `id`, with no name fallback** — confirmed in
> `src/grace_platform/credentials_helper.py`, which throws `CredentialNotFoundError` when the id does not
> resolve. Such a workflow `PUT`s 200 OK, activates happily, and throws on its **first execution**. Worse,
> the old verification step compared JSON only, so it would never catch it. This was the most damaging
> defect in the document.

Committed workflows carry a resolvable placeholder instead:

```jsonc
"credentials": {
  "httpHeaderAuth": { "id": "__CRED__:vapi", "name": "__CRED__:vapi" }
}
```

`deploy.py` resolves `__CRED__:vapi` → `PalmLeaf Vapi (prod)` → the real id via
`GET /api/v1/credentials` (verified: returns `{id, name, type}` and no secret material).
`export.py` performs the reverse mapping. **Any unresolved placeholder is a hard deploy failure** —
because n8n itself will not fail, it will publish and then break at runtime.

Credentials are **never** deployed. They are created once per instance by hand and referenced by name;
`credentials.example.json` documents which must exist. ⚠️ Hand-created credentials sit outside the
secret manager and outside the current+previous rotation window promised in [05-security-and-compliance](05-security-and-compliance.md) — note the gap.

### 10.3 Deploy

```
src/grace_platform/n8n/deploy.py --env prod
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
  8. Activate: POST /workflows/{id}/publish, falling back to /activate on 404   ← §10.4
  9. Re-fetch and assert equality against the ACTIVE version, not the draft
 10. Any env:prod + managed:git workflow with no local file → orphan → FAIL
```

Fail loudly on any mismatch — silent partial deploys are worse than no deploy.

### 10.4 `active` is read-only — and which route to call

> ⛔ The previous step 3 said "Activate workflows marked `active: true`". `active` is **read-only** on the
> workflow body; setting it via `PUT` does nothing.

Activation is a separate endpoint, and **which one depends on the n8n version**:

| Route | This instance (3 Aug 2026) | Notes |
|---|---|---|
| `POST /workflows/{id}/activate` | ✅ exists | what we use today |
| `POST /workflows/{id}/publish` | ❌ 404 | newer route; some docs call `/activate` deprecated |

`deploy.py` **tries `/publish` first and falls back to `/activate` on 404.** n8n Cloud auto-updates, so
hard-coding either one guarantees a future breakage. This version-tolerance is required, not defensive
padding — the plan originally specified `/publish` only, which would fail on every deploy here today.

Similarly, step 9 must compare against the **active/published** version rather than the draft wherever
the instance exposes that distinction; on an instance without `/publish`, the draft *is* what runs.

⚠️ `PUT` on a published workflow may auto-republish, and may return **409** on an open workflow review or
a webhook path conflict. Handle 409 explicitly rather than retrying blindly. A path collision between dev
and prod is a *useful* guard — do not suppress it.

### 10.5 Domain orchestrators and library sub-workflows

Eleven flat workflows on one canvas list is a set nobody can stop, restart, or reason about as a
group. The reporting domain was therefore reshaped on 5 August 2026 into **one orchestrator plus
sub-workflows**, using two n8n mechanisms that were already proven on this instance by WF-12 → WF-18:

- a sub-workflow's only trigger is `n8n-nodes-base.executeWorkflowTrigger`, so it **cannot fire
  unless a parent calls it**;
- a parent references it as `"workflowId": "__WF__:wf-24"`, a placeholder `deploy.py` resolves to the
  real id at deploy time — the same treatment credentials and base URLs get (§10.2), and lint rule 18
  now rejects a raw id there for exactly the reason rule 11 rejects one in `errorWorkflow`.

```
ENTRY POINT (stoppable)                REPORT SUB-WORKFLOWS         LIBRARY SUB-WORKFLOWS
WF-25 Reporting Orchestrator  ──┬──►   WF-07 Nightly Recon    ──►   WF-23 Core API Fetch
  five scheduleTriggers,        ├──►   WF-11 Hourly Digest    ──►   WF-23
  America/Chicago               ├──►   WF-20 Daily Digest     ──►   WF-24 Vapi Call Fetch
                                ├──►   WF-21 Weekly QA        ──►   WF-24
                                └──►   WF-22 Quality Alert    ──►   WF-24

                                       WF-07/20/21/22         ──►   WF-26 Send Report Email
                                       (WF-11 deliberately not wired — see below)
```

**The one-switch property.** Deactivating `[dev] WF-25` stops all five reports, because none of them
owns a schedule any more. Nothing else is affected — the heartbeat, the error handler and both
webhooks keep running. That is what "stoppable groups" means here, and it is checkable in one click
rather than five.

**WF-23 and WF-24 are libraries, not steps.** Each holds one copy of logic that was previously
pasted into two or three workflows: WF-23 fetches a Core API report and normalises the outcome to
`{ok, statusCode, body, unreachableMessage}`; WF-24 fetches Vapi calls and returns one item shaped
`{calls: [...]}` with per-call `booked`, `escalated`, `medicalHold`, `intent`, `durationSeconds` and
`recordingUrl`. A change to how a call is classified is now one edit, not three.

**WF-26 Send Report Email — the third library sub-workflow (added 5 August 2026).** Same shape as
WF-23 and WF-24: an `executeWorkflowTrigger` and nothing else, so it cannot fire on its own.

| | |
|---|---|
| **Input contract** | one item, `{subject, body}` — both plain strings, `body` is plain text, not HTML |
| **Output** | one email, sent from `grace@palmleafmassage.com` to the address in `GRACE_REPORTS_EMAIL_TO` |
| **Called by** | WF-07 (nightly), WF-20 (daily), WF-21 (weekly), WF-22 (only when a call is flagged) |
| **Not called by** | WF-11 — deliberate, see below |
| **Blocked on** | the `smtp` credential and `GRACE_REPORTS_EMAIL_TO`; until both exist `deploy.py` skips it |

Each caller keeps a small `Shape the email` Code node immediately before its `Email via WF-26` node.
That node is the only place a report's wording lives, and it is where the two different item shapes
are reconciled: WF-07 and WF-20 read `$input.first()` because their summarise step already produced
one row, whereas WF-21 and WF-22 read **`$input.all()`** because their save step ran once per sampled
or flagged call — twenty separate emails would be worse than none. WF-22 additionally returns `[]`
when it has zero items, preserving the property that a clean hour sends nothing at all; its "Flag
problem calls" node already returns nothing on a clean run, so the guard is belt-and-braces rather
than the only defence.

> **WF-11 is deliberately excluded, and should stay excluded.** It runs hourly. Wiring it to WF-26
> would mean twenty-four emails a day of routine activity, which is how a reporting channel becomes
> something staff filter into a folder and stop reading — taking the four reports that *do* matter
> with it. WF-11's rows remain in the `call_digests` Data Table, which is where an hourly figure
> belongs. This is a settled decision, not an oversight to be tidied up later.

**`__EMAIL__:` — a placeholder that blocks instead of falling back.** WF-26's `toEmail` is committed
as `"=__EMAIL__:reports-to"`, which `deploy.py` resolves from `GRACE_REPORTS_EMAIL_TO` at deploy
time. The *mechanism* mirrors `__URL__:` (§10.2, and `URL_VARS` in `deploy.py`) and exists for the
same reason: n8n Cloud blocks `$env` inside nodes, so the value cannot be read at runtime.

The one deliberate difference is what happens when the environment variable is unset. `__URL__:`
substitutes `URL_UNSET` (`https://core-api.not-built.invalid`) and lets the deploy proceed, because
an unreachable URL fails harmlessly and visibly. **There is no equivalent safe value for an email
address.** A wrong one either bounces somewhere unintended or silently reaches nobody — and "silently
reaches nobody" looks exactly like success from inside n8n. So an unset `GRACE_REPORTS_EMAIL_TO` is
recorded as *unresolved*, which makes `render()` return `None` and the deploy **skip WF-26 entirely**,
exactly as it already does for a missing credential (§8). The rest of the set still deploys; the one
workflow with an unconfigured real-world side effect does not.

Because WF-07/20/21/22 reference `__WF__:wf-26`, they cannot be published until WF-26 exists on the
instance — the same transient state WF-07 and WF-11 passed through before WF-23 was created, and it
clears on the first `make n8n-apply` after the credential is added.

**The cost, stated honestly: executions roughly triple for reports.** Every Execute Sub-workflow call
is a separate n8n execution counted against the Cloud plan's shared dev+prod quota (§6.1). A report
run that used to cost 1 execution now costs about 3 — the parent branch, the report, and the library
fetch. Across the five reports that is roughly 50/day → 150/day. This was accepted deliberately in
exchange for the one-switch property and the deduplicated logic; WF-19's every-15-minute heartbeat
was left at one execution per run precisely because it is the highest-frequency workflow we own.

**Why WF-19, WF-00 and WF-17 deliberately stay standalone.** Do not "finish" this consolidation by
folding them in:

| Workflow | Why it must keep its own trigger |
|---|---|
| **WF-19** Platform Heartbeat | A watchdog must not share a switch with what it watches. If the heartbeat can be stopped by the same click that stops reporting, it stops reporting *that* — see §6's limits, which are already uncomfortable enough. |
| **WF-00** Global Error Handler | n8n's error trigger is per-instance wiring; every workflow names WF-00 in `settings.errorWorkflow`. It has no parent by construction. |
| **WF-17** Vagaro Fan-out | An ingress webhook has its own lifecycle — a public URL, a credential, and a caller outside this system. Grouping it under a switch would let an internal decision silently drop external traffic. |

### 10.6 Why there is no Vapi-facing orchestrator — asked 5 August 2026

The obvious next thought, once WF-25 exists, is to build its mirror image on the call side: one n8n
workflow that receives every Vapi tool call, routes it to the right sub-workflow, and returns the
answer to Vapi. **That workflow is exactly what ADR-0002 rejects, and it already exists elsewhere in
the design** — it is the Core API tool router, `grace_api`. The question is recorded here because the
orchestrator pattern below invites it, and the answer is not obvious from this document alone.

The routing *idea* is right. The placement is what differs, for four reasons that do not apply to
reporting:

| | Reporting (WF-25) | A voice tool call |
|---|---|---|
| **Deadline** | None. A digest is as good at 07:31 as 07:30. | p95 **400 ms**, and voice quality is decided by the tail, not the median. |
| **Executions per request** | ~3, and nobody waits. | ~3 hops of queue time on a shared dev+prod instance (§6.1) — a caller hears every one of them as silence. |
| **Transactions** | None. Each write stands alone. | Promoting a hold, writing the booking and enqueuing the notifications must be **one** transaction. n8n has no primitive spanning nodes; a crash mid-chain leaves a hold with no booking. |
| **Testability** | Output is a report; a wrong number is visible. | The 48-hour rule and pricing are money logic under invariant I4 and must be unit-tested in CI. A Code node in a canvas cannot be. |

The execution-multiplication line is not theoretical: the consolidation immediately above measured
it, one report run going from 1 execution to roughly 3. That trade is free when nobody is waiting and
unaffordable when somebody is mid-sentence.

**What n8n keeps is unchanged**, and it is genuinely the better tool for it: everything reached
*after* a call ends, or *outside* one — escalation, reporting, fan-out, alerting. The boundary rule in
§1 already draws this line; this subsection only records that the orchestrator pattern does not move
it. Should a stakeholder still require n8n on the hot path, ADR-0002 documents the fallback — n8n
calling the same domain logic through one internal endpoint per tool, roughly a day's work — so the
decision is reversible, not a one-way door.

---

## 11. Multi-tenancy — unhandled, and it will break at tenant two

ADR-0008 makes every table tenant-scoped, and `tenants.settings` carries `managerMobile` and the
notification routing ([data-model](../reference/data-model.md)). **But n8n cannot read tenant settings** — no `/internal/tenants/:slug/settings`
endpoint exists — so WF-12's manager mobile and routing must be hardcoded or held as n8n credentials.

The first non-PalmLeaf tenant breaks every workflow. This is not flagged as a risk anywhere in the current
plan set, and A-01 explicitly assumes PalmLeaf is "tenant one of a productized service".

**Decision for now:** hardcode PalmLeaf, and add `GET /internal/tenants/:slug/settings` to the §4.2
endpoint list so workflows can be parameterised in Phase F. Registered as risk **R-n8n-1** in [09-open-decisions](09-open-decisions.md).

---

## 12. Workflow CI lint

```text
TARGET — src/grace_platform/n8n/lint.py   asserts, per workflow:
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
14. A node may hold an unresolved `__CRED__:` placeholder ONLY if that node is disabled  (§8)
15. Every cron node sets timezone explicitly to America/Chicago
16. An HTTP node sets alwaysOutputData when the file has a scheduleTrigger OR an
    executeWorkflowTrigger — the gate covers library workflows too, since WF-23/WF-24 now
    hold the report fetches the rule was written for  (§10.5)
17. No node reads $env.X — n8n Cloud denies it; the allowlist of exceptions is EMPTY  (§7.1)
18. Every executeWorkflow node's workflowId is '__WF__:<alias>', never a raw id  (§10.5)
```

Rules 2 and 14 need reachability analysis over the connection graph including `Continue On Fail`
branches. ⚠️ The previous version estimated "an hour to write" for rule 2 — that is optimistic for a
correct implementation; budget half a day.

---

## 13. MCP usage policy

| Allowed | Forbidden |
|---|---|
| Authoring and iterating on `[dev]`-prefixed workflows | Touching any `[prod]` workflow |
| `validate_workflow` / `validate_node_config` | `publish_workflow` on anything |
| Searching templates for a starting point | Bypassing export → PR → CI |
| `test_workflow` against dev | Editing a live workflow to "fix" an incident |

The flow is always: **author on `[dev]` via MCP → `export.py` → review the diff → PR → CI deploys to
`[prod]`.**

⚠️ On one instance this policy is **convention, not enforcement** — see §6.2. The MCP server can publish,
and cannot be scoped below Enterprise. The hourly drift job is what actually catches a violation.

`.mcp.json` is gitignored and resolves credentials from environment variables; `.mcp.json.example` is
committed with placeholders ([EXECUTED-vapi-n8n-plan](../Completed/EXECUTED-vapi-n8n-plan.md) Step 0).

---

## 14. Corrections applied in this revision

| # | Was | Now | Impact if unfixed |
|---|---|---|---|
| 1 | credentials as `{id: "<name>"}` | `__CRED__:` placeholder resolved at deploy (§10.2) | Deploys green, throws on first execution |
| 2 | `active: true` set via `PUT` | separate activate route, `/publish`→`/activate` fallback (§10.4) | Workflows never activate |
| 3 | `/publish` assumed present | **absent on this instance**; version-tolerant fallback (§10.4) | Every deploy 404s |
| 4 | Three contradictory WF-12 triggers | sync-worker → signed webhook (§2) | Nothing triggers the main workflow |
| 5 | No secret for worker → n8n | the `n8n-inbound` Header Auth credential on both webhooks (§2.1) — this replaced the `GRACE_N8N_WEBHOOK_SECRET` HMAC scheme, which a Cloud Code node cannot read | Unauthenticated public webhook |
| 6 | Respond-to-Webhook last, after a 15-min Wait | ACK immediately after validation (§4) | Caller connection held open 15 min |
| 7 | "daily digest store" undefined | `POST /internal/digest/append` (§4.2) | P3 branch writes nowhere |
| 8 | Error workflow unnumbered, unbuilt | WF-00, in the inventory, lint-exempt (§3.2) | Lint rule 6 unsatisfiable |
| 9 | WF-18 had its own webhook + WF-12 timer | WF-12 owns the timer (§3.3) | Two competing escalation timers |
| 10 | Staff SMS via n8n Twilio node | via `/internal/notify/sms` (§3.4) | 10DLC/opt-out bypass; carrier-filtered, silent |
| 11 | WF-14 = "click Resolved" + `/grace-kill` | **withdrawn** — both surfaces were on an out-of-scope chat platform (§3.1) | Two unbuildable surfaces presented as planned work |
| 12 | strip node `position`/`pinData` by hand | `?excludePinnedData=true`; keep node `id` + `webhookId` (§10.1) | Diff churn; **changed prod webhook URL** |
| 13 | "six workflows move into code"; [09-open-decisions](09-open-decisions.md) D-7 "7 remain" | ten move, nine remain (§3) | Arithmetic wrong in two docs |
| 14 | two instances, I9 intact | one instance, ADR-0013, detection-based control (§6) | Security posture misstated |
| 15 | crons "03:15 CT" | explicit `America/Chicago` per workflow (§3) | CST/CDT ambiguity, instance-default drift |
| 16 | multi-tenancy unaddressed | hardcode + endpoint for Phase F, risk R-n8n-1 (§11) | Breaks at tenant two, unflagged |

**New assumptions for [09-open-decisions](09-open-decisions.md):** A-19 (`/grace-kill` authorization), A-20 (WF-18 voice call, Phase F),
A-21 (draft/publish availability on this instance).

---

## 15. Acceptance criteria

✅ **AC-09.1** `lint.py` fails a deliberately broken workflow (missing respond node on an error branch).
✅ **AC-09.2** `export.py` run twice against an unchanged instance produces byte-identical files.
✅ **AC-09.3** `deploy.py --env prod` is impossible without the CI secret (clear failure locally).
✅ **AC-09.4** WF-12 delivers a P1 staff notification and SMS within 30s of a `staff.notify` outbox
event. *(Blocked until Core API exists — see §4.)*
✅ **AC-09.5** WF-12 responds 200 on every branch, verified by injecting a failure into each external node.
✅ **AC-09.6** No workflow JSON contains a credential value (secret-scanner clean).
✅ **AC-09.7** A P1 left unacknowledged 15 minutes triggers WF-18 in a test run with a compressed timer.
✅ **AC-09.8** Deploying a workflow with an unresolved `__CRED__:` placeholder **fails the deploy** — the
regression test for correction #1.
✅ **AC-09.9** `deploy.py` activates successfully on an instance exposing only `/activate`, and on one
exposing `/publish` — correction #3.
✅ **AC-09.10** An unsigned or stale-timestamp POST to WF-12's webhook is rejected 401 — correction #5.
✅ **AC-09.11** The untagged `AI Agent workflow` already on the instance is untouched by
`deploy.py --env prod` and is not reported as an orphan.

✅ **AC-09.12** WF-20 triggered manually produces a real n8n Execution with real output, and a row
lands in the Data Table. This is the criterion that distinguishes "deployed" from "working", and it
is the first one in this document that could be met without Core API.
✅ **AC-09.13** `make n8n-apply` succeeds while `__CRED__:postgres` is unresolved, **because the node
holding it is disabled** — the regression test for lint rule 14 (§8).
✅ **AC-09.14** `make docs` regenerates [Docs/generated/workflows/](../generated/workflows/) with every
deployed node listed, and `make docs-check` fails CI when a workflow changes without regeneration.

✅ **AC-09.15** The five reports write rows with **identical column shapes before and after** the
WF-25/WF-23/WF-24 refactor (§10.5). The Data Table and Postgres nodes were carried across unchanged;
a changed row shape would be a silent data break, not a visible failure.
✅ **AC-09.16** Deactivating `[dev] WF-25` stops all five reports and **nothing else** — WF-19's
heartbeat still beats at the next 15-minute window. This is the one-switch property, tested rather
than assumed.
✅ **AC-09.17** `make n8n-lint` **rejects** an `executeWorkflow` node whose `workflowId` is a raw id
instead of `__WF__:<alias>` — the regression test for rule 18.
✅ **AC-09.18** With `GRACE_TRANSFER_NUMBER` unset, the Vapi deploy renders `transferToHuman` with an
**empty** `destinations` list and prints a waiting-on-configuration notice — it never substitutes a
stand-in number, because an invalid number would make Vapi attempt a real transfer mid-call.

## 16. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-04.1** | Where will the reporting Postgres actually be hosted? | §8 ships the path switched off pending a hosted instance. Neon and Supabase free tiers are both adequate; nobody has picked one or created it. Until then, Data Tables are capped and the durable record does not exist. | Engineering — small, unblocked, worth doing soon |
| **Q-04.2** | What replaces the kill switch's one-click surface? | Withdrawing WF-14 (§3.1) left the kill switch as an authenticated API call driven from a runbook. That is materially slower under pressure. A staff dashboard is Phase F, which may be too late. | Product / client |
| **A-20** | How does WF-18 place its final "call the manager" step? | `VoicePort.createOutboundCall` is Phase F ([provider-adapters](../reference/provider-adapters.md)), and a direct Twilio Voice node is not specified. Until then WF-18 terminates at a repeat SMS plus a staff notification — degraded, but never silently dropped. | Engineering, at Phase F |
| **A-21** | Does this instance expose draft/publish, or only activate? | §10.4 handles both shapes because the probe found only `/activate`. If a Cloud upgrade adds `/publish`, the fallback becomes dead code worth removing rather than carrying. | Re-probe at each n8n upgrade |
| **Q-04.5** | ~~How does WF-12 verify an inbound HMAC on n8n Cloud?~~ **RESOLVED 2026-08-05.** | It does not — it no longer verifies anything itself. WF-12 was migrated to the Webhook node's native Header Auth with the `n8n-inbound` credential, the scheme WF-17 already used; see §2.1 and §7.1. The "Verify signature", "Authenticated?" and "Respond 401" nodes are deleted, the last `$env` read in the workflow set is gone, and lint's allowlist is empty. | Closed |
| **Q-04.4** | What provides the dead-man's switch *outside* n8n? | WF-19 (§6) proves liveness and catches a missed window after the fact, but **cannot alert while n8n is fully down** — nothing runs to raise the alarm. The cheapest fix is an external cron reading the heartbeat table and alerting on staleness. Until then, a total n8n outage is still silent. | Engineering |
| **Q-04.3** | When does multi-tenancy in n8n stop being deferrable? | §11 is explicit that tenant two breaks every workflow, since n8n cannot read tenant settings. Registered as **R-n8n-1**. It costs one endpoint plus parameterisation to fix, and nothing until the second tenant exists. | Engineering, at Phase F |
