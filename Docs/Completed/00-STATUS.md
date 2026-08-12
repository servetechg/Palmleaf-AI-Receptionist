# Completed Work — Status Dashboard

**Last updated:** 7 August 2026
**Scope of this phase:** Vapi conversation layer + n8n orchestration layer, plus **read-only**
RingCentral access. Vagaro, Stripe, Google and Twilio are blocked; Core API is out of scope.

> **How to read this folder.** One file per work area. Each records what was built, what
> was *verified* (with the evidence), and what is explicitly **not** done. If something is
> not listed as verified here, treat it as unproven regardless of how finished the code looks.

---

**Plain-language summary for non-technical readers: [DAILY-LOG.md](DAILY-LOG.md).**
**Engineering detail — mechanisms, defects, root causes: [DAILY-LOG-TECHNICAL.md](DAILY-LOG-TECHNICAL.md).**

---

## At a glance

| Area | Status | Detail |
|---|---|---|
| Documentation corrections | ✅ Done | [01](01-foundation.md) |
| `packages/contracts` (13 tool schemas) | ✅ Done | [02](01-foundation.md) |
| Repo, tooling, CI | ✅ Done | [02](01-foundation.md) |
| Vapi layer — deployed and live | ✅ Done | [03](02-vapi-layer.md) |
| Mock tool server + web harness | ✅ Done | [04](03-testing-and-mock-server.md) |
| n8n layer — 14 committed workflow files | ✅ Done | [05](04-n8n-layer.md) — 9 deployed to dev, 5 held back by the `smtp` credential |
| **Live phone call with Grace** | ✅ **Done** 2026-08-06 | first real call answered end to end over a tunnel to the mock server — [06](05-pending-and-blocked.md) for what's still fake |
| Reporting workflows WF-20/21/22 | ✅ **Live** | deployed and active; now invoked by WF-25, fetching via WF-24 |
| **WF-25 Reporting Orchestrator** | ✅ **Live** | `2RQYvTa95jSt3Qeh` — owns all five report schedules; one switch stops every report |
| Library sub-workflows WF-23 / WF-24 | ✅ **Live** | `R83ajpEc5kBPOkW8` / `4wKh5fUagueLVmRH` — no independent trigger |
| **WF-26 Send Report Email** | 🔨 Built, **blocked** | Skipped by deploy: needs the `smtp` credential **and** `GRACE_REPORTS_EMAIL_TO`. WF-07/20/21/22 call it and are held back with it |
| Platform heartbeat WF-19 | ✅ **Live** | deployed and active 2026-08-04; beats every 15 min |
| n8n Data Tables (8) | ✅ Created | call_metrics, call_samples, call_flags, platform_heartbeat, workflow_errors, reconciliation_reports, call_digests, fanout_log |
| Reporting Postgres | ⚠️ Skeleton, switched off | needs a hosted database n8n Cloud can reach |
| Vapi Simulations (T2/T3) | ❌ Not started | [06](05-pending-and-blocked.md) |
| **All 14 committed n8n workflows** | ✅ **Built** | Only **5 are entry points** — WF-00, 12, 17, 19, 25; the other 9 are sub-workflows. 9 deployed; WF-26 and its four callers wait on the `smtp` credential |
| **Q-04.5 — WF-12 inbound auth** | ✅ **Resolved** 2026-08-05 | migrated to n8n's native Header Auth; lint's `$env` allowlist is now empty |
| WF-07 / WF-11 / WF-17 | ✅ Built ahead of access | integration points left as configuration |
| **RingCentral API access** | ✅ **Working** 2026-08-06 | Private JWT app authenticates against the production platform; every read succeeded first attempt, no scope errors |
| **RingCentral snapshot** (`make rc-snapshot`) | ✅ **Captured** | 21 files in `platform/ringcentral/snapshot/`; second run reports `✓ no drift`. Findings: `platform/ringcentral/README.md` |
| **RingCentral writes** | ❌ Not built, by design | No write code exists in the repository. Phase 2 adds it, restricted to `grace-*` rules |
| **Vapi phone-number deploy** | ✅ **Live** 2026-08-06 | `+1 651-386-9103` created via `make vapi-apply`; 847 was requested but unavailable on the account, so the deployer fell back to an offered area code. Not yet wired to PalmLeaf's real line (847.961.4800) — that needs RingCentral write access |
| **Vagaro API access** | ⏳ **Requested, in queue** | Application filed; Vagaro's stated activation window is up to 7 business days. $10/month, 5,000 calls/month |
| **Vagaro integration plan** | ✅ **Approved**, 🔨 not started | Full read discovery → real reads → gated writes plan, built from live Vagaro webhook docs (event types, retry/rate-limit rules) and approved by the client 2026-08-06. Zero implementation code exists yet |
| **Postgres schema — 20 tables, 15 migrations** | ✅ **Applied live** | local Postgres 16 via `make db-up`; double-booking exclusion constraint (I2) proven by a rejected overlapping insert |
| **PMS port + FakePms + resilient client** | ✅ Built | ahead of Vagaro credentials; write capabilities all default False until discovery proves otherwise |
| **Service catalogue seeded** | ⚠️ Deliberately unapproved | 3 services, 2 providers, `approved_at IS NULL` — Grace refuses to quote until GATE-04 sign-off |
| Vagaro API access | ⏳ Requested, queued | 7-business-day activation; $10/mo, 5,000 calls/month — the number the mirror architecture is sized against |
| **Core API (`grace_api`)** | ✅ **Running locally** | `make api-run`; tool endpoint, Vagaro webhook receiver, bearer-authed internal reports. Exercised live against the seeded database |
| **Availability engine** | ✅ **Proven** | 148 slots over 3 days from real shifts; one hold removes exactly its 5 grid positions; approval gate returns 0 slots when unsigned |
| **Invariant I1 enforced** | ✅ **Mechanical** | `make imports` — 3 import-linter contracts, negative-tested. Closes task A-08, open since the language port |
| Booking write path | 🔨 Next | state machine + outbox schema exist; `createBooking` still answers "let me get someone" |

---

## What is actually running right now

**Vapi** (org `ba7165f7`)

| Resource | Id | State |
|---|---|---|
| Assistant `Grace — PalmLeaf [dev]` | `51fd2d26-b00f-42a7-964d-adef6437ddaf` | live, 15 tools attached |
| 13 generated function tools | see `platform/vapi/.lock.json` | live |
| `transferToHuman` (`transferCall`) | `a0f89f8f-…` | live |
| `endCall` (`endCall`) | `523f2702-…` | live |
| Structured output `grace-call-outcome` | `3e25e0f5-…` | live |
| Phone number `Grace line (dev)` | `fe95f6cf-…` → `+1 651-386-9103` | live, answered a real call 2026-08-06 |

⚠️ Tool URLs currently point at a **laptop tunnel** (`cloudflared`), not a hosted service. **Calls
only work while that tunnel and the mock server are both running** — see
[06](05-pending-and-blocked.md).

**n8n** (`palmleafmassage.app.n8n.cloud`)

| Workflow | Id | State |
|---|---|---|
| `[dev] WF-00 Global Error Handler` | `TskMxWsdNPdtyzwz` | active, `managed:git` + `env:dev` |
| `[dev] WF-12 Escalation & Alerting` | `Nig7UzGSTwVZuFLg` | active, tagged |
| `[dev] WF-18 On-call Escalation` | `IvXEhYoHdxT3e7oA` | active, tagged |

Credential `PalmLeaf Core API (dev)` (`MLPOdQtg1zcSlYUJ`) exists with a **placeholder token**
— rotate when Core API is real. The pre-existing `AI Agent workflow` is untagged and is
correctly ignored by the deploy filter.

---

## Verification evidence

Only claims with evidence are listed. Everything else is in [06](05-pending-and-blocked.md).

| Acceptance criterion | Evidence |
|---|---|
| **AC-08.1** zero drift after apply | `platform:vapi:deploy --diff` → `✓ no drift`, against a live assistant with all server defaults materialised |
| **AC-08.2** generated tools are deterministic | `--check` passes immediately after `generate`; digest `e09fe29d7bf1` stable |
| **AC-08.3** I7 greeting protected | validator fails on a missing disclosure *and* on an inlined `firstMessage` |
| **AC-08.4** all 15 tools registered | `mcp__vapi__list_assistants` shows 15 `toolIds` |
| **AC-08.8** dirty-tree guard | `--apply` to prod refuses on a dirty tree |
| **AC-08.10** offline schema validation | `platform:vapi:validate` checks every key against the live `CreateAssistantDTO` |
| **AC-09.1** lint catches broken workflows | 5 injected defects → 5 failures, then green after restore |
| **AC-09.8** unresolved credential fails the deploy | deploy aborted before touching the instance |
| **AC-09.9** activation route fallback | activated via `/activate` after `/publish` returned 405 |
| Speech formatting | 14 unit tests, including 3 regressions the mock server found |
| **WF-19 works end to end** | execution 2026-08-04T13:45:10 `success`; row `id:1` written to `platform_heartbeat`; `vapi_ok:true` proves the Vapi key authenticates |
| **WF-22 runs on schedule** | 6 consecutive hourly `success` executions on 2026-08-04. ⚠️ All were *empty* runs — it writes no row unless a call trips a signal, so its sink is not yet proven |
| **RingCentral JWT authenticates** | `make rc-snapshot` on 2026-08-06 read account, service-info, numbers, 17 extensions, 9 company answering rules, IVR menus and call queues — no 401, no scope error |
| **RingCentral drift detection converges** | second consecutive `make rc-snapshot` → `✓ no drift` |
| **Snapshot carries no credentials** | `grep -riE '"(token\|accessToken\|refreshToken\|password\|authorization)"\|access_token='` over `platform/ringcentral/snapshot/` returns nothing |
| **GATE-11 concurrency question** | ⚠️ *Not* answered by the account: `service-info.limits` publishes no concurrent-call figure and `billingPlan.includedPhoneLines` is 0. Remains an empirical pilot observation |
| **L3 voicemail race** | ⚠️ Not answerable from configuration — no answering rule declares ring counts. Requires a live Stage A test call |
| n8n Data Tables exist | 8 created via API; previously zero, which is what broke WF-20 |
| Deploy skips a config-blocked workflow | `make n8n-apply` deployed 9 workflows and named WF-17 as waiting on a credential, instead of aborting |
| Activation is reconciled | WF-11 was deployed but inactive after an aborted run; the next apply detected and activated it |
| **AC-09.13** disabled node may hold an unresolved credential | `n8n-lint` green with `__CRED__:postgres` unresolved, because that node is disabled |
| **AC-09.17** lint rejects a raw sub-workflow id | rule 18 negative test: WF-07's target set to `abc123` → rejected, then reverted |
| Rule 16's widened gate | negative test: `alwaysOutputData` dropped from WF-24's fetch → rejected, then reverted |
| Consolidated set deploys clean | `make n8n-apply ENV=dev` → 8 changes applied; re-run `make n8n-diff ENV=dev` → `✓ no drift` |
| An unset email recipient blocks one workflow, not the run | `make n8n-diff ENV=dev` → WF-26 SKIPPED naming both `GRACE_REPORTS_EMAIL_TO` and the `smtp` credential; the nine deployed workflows still report `=` |
| Generated tool + workflow reference | `make docs` twice → byte-identical; `--check` fails when a description changes |
| Document template enforced | `make docs-lint` → 20 documents conform; wired into `make check` and CI |
| **Grace answered a real phone call** | `+1 651-386-9103` dialled 2026-08-06; greeting, recording disclosure and a mock booking conversation all completed over the live tunnel. User-confirmed: "working, not good but working" |
| **`.env` actually loads** | Live test: a blank `N8N_API_KEY=` in `.env` 401'd a real deploy, confirming `.env` overrides an inherited shell value — the precedence the blank-variable near-miss depended on |
| **Vagaro webhook contract confirmed from source** | Live fetch of `docs.vagaro.com` webhook pages: 6 event types, each carrying a dedupe-safe `id`; documented 20s ack window and 5-retry/15-min backoff; matches the frozen core-api design exactly (A-11) |
| **Vagaro rate limit confirmed** | 5,000 calls/month (~166/day) stated in Vagaro's own docs — validates the local-mirror architecture (I1): in-call reads must never hit Vagaro live |

---

## Commits

| SHA | Summary |
|---|---|
| `34e3f4d` | Doc corrections against live APIs + workspace skeleton |
| `e8db9cd` | Contracts, generator, validator, deploy — Grace live on dev |
| `298c9fc` | Mock server, web harness, n8n workflows, CI gate |
| `a335d9a` | Slack removed; n8n workflows deployed; `Docs/Completed/` created |
| `cf71434` | **Ported TypeScript → Python** (ADR-0014); n8n credential-name bug fixed |
| `8243e88` | ADR-0015…0018; document-template linter; generated per-tool and per-workflow reference |
| `ec1a73e` | **WF-20/21/22 reporting workflows**; Postgres schema skeleton, deployed switched off |
| `f32b025` | A quiet day emits an explicit zero rather than no row at all |
