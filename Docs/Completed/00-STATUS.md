# Completed Work — Status Dashboard

**Last updated:** 3 August 2026
**Scope of this phase:** Vapi conversation layer + n8n orchestration layer only.
Vagaro, RingCentral, Stripe, Google and Twilio are blocked; Core API is out of scope.

> **How to read this folder.** One file per work area. Each records what was built, what
> was *verified* (with the evidence), and what is explicitly **not** done. If something is
> not listed as verified here, treat it as unproven regardless of how finished the code looks.

---

**Plain-language summary for non-technical readers: [DAILY-LOG.md](DAILY-LOG.md).**

---

## At a glance

| Area | Status | Detail |
|---|---|---|
| Documentation corrections | ✅ Done | [01](01-documentation-corrections.md) |
| `packages/contracts` (13 tool schemas) | ✅ Done | [02](02-contracts-and-tooling.md) |
| Repo, tooling, CI | ✅ Done | [02](02-contracts-and-tooling.md) |
| Vapi layer — deployed and live | ✅ Done | [03](03-vapi-layer.md) |
| Mock tool server + web harness | ✅ Done | [04](04-mock-server-and-testing.md) |
| n8n layer — 3 workflows live | ✅ Done | [05](05-n8n-layer.md) |
| **Live web call with Grace** | ⏳ Blocked | needs a tunnel — [06](06-pending-and-blocked.md) |
| Vapi Simulations (T2/T3) | ❌ Not started | [06](06-pending-and-blocked.md) |
| Remaining 6 n8n workflows | ❌ Not started | [06](06-pending-and-blocked.md) |
| Core API | ❌ Out of scope | resumes from doc 15 |

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

⚠️ The assistant's tool URLs currently point at `placeholder.invalid`. **Tools will fail on
a real call until it is redeployed with a tunnel URL** — see [06](06-pending-and-blocked.md).

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

Only claims with evidence are listed. Everything else is in [06](06-pending-and-blocked.md).

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

---

## Commits

| SHA | Summary |
|---|---|
| `34e3f4d` | Doc corrections against live APIs + workspace skeleton |
| `e8db9cd` | Contracts, generator, validator, deploy — Grace live on dev |
| `298c9fc` | Mock server, web harness, n8n workflows, CI gate |
