# PalmLeaf "Grace" — Foundational Architecture & Implementation Plan

**Status:** Foundational baseline — approved for build
**Version:** 1.0
**Date:** 1 August 2026
**Supersedes:** nothing. **Extends:** `Docs/PalmLeaf_AI_Receptionist_Architecture.md` (the design brief)
**Audience:** the implementing agent (Claude Sonnet), plus any human reviewer

---

## What this document set is

`Docs/PalmLeaf_AI_Receptionist_Architecture.md` is a **design brief**. It establishes *what* Grace does,
*why* Vagaro is a blocker, and *what* the commercial and legal constraints are. It is correct and it is
the source of truth for product intent.

This plan set is the **engineering foundation**. It converts that brief into a buildable system:
concrete repository layout, database DDL, module boundaries, interface signatures, error taxonomies,
deployment topology, and an ordered task list where every task has an acceptance test.

> **Rule for the implementing agent:** if this plan set and the design brief conflict on a *technical*
> matter, this plan set wins and the conflict must be logged in `17-open-decisions.md`.
> If they conflict on a *product, policy, legal or commercial* matter, the design brief wins and you must stop
> and ask. Never resolve a policy conflict yourself.

---

## Reading order

Read **01**, **02**, **03** before writing any code. They are load-bearing for everything else.

| # | Document | What it settles | Read before |
|---|---|---|---|
| [01](01-architecture-foundation.md) | Architecture Foundation & ADRs | Layers, boundaries, the 12 architectural decisions and their rationale | anything |
| [02](02-repository-and-tooling.md) | Repository, Tooling & Conventions | Monorepo layout, package graph, TS config, lint, commit and CI conventions | writing any file |
| [03](03-data-model.md) | Data Model | Complete Postgres DDL, migrations, indexes, constraints, RLS, invariants | any DB work |
| [04](04-core-api-service.md) | Core API Service | Fastify app, middleware chain, request lifecycle, error model, tool endpoints | Phase B |
| [05](05-provider-adapters.md) | Provider Adapters | The PMS port/adapter contract, Vagaro, Google Calendar, Stripe, Twilio adapters | Phase B |
| [06](06-availability-engine.md) | Availability Engine | Slot computation, occupancy model, holds, concurrency, idempotency | Phase B |
| [07](07-booking-write-path.md) | Booking Write Path | Track A/B/C/D orchestration, saga states, outbox, compensation | Phase C |
| [08](08-vapi-layer.md) | Vapi Conversation Layer | Assistant config-as-code, 13 tool definitions, system prompt, latency tuning | Phase C |
| [09](09-n8n-layer.md) | n8n Orchestration Layer | Workflow inventory, JSON-as-code, dev/prod split, deploy pipeline | Phase C |
| [10](10-telephony-and-messaging.md) | Telephony & Messaging | Twilio Elastic SIP, RingCentral forwarding, A2P 10DLC, SMS templates | Phase D |
| [11](11-security-and-compliance.md) | Security & Compliance | IL all-party consent, BIPA, PHI redaction, PCI boundary, secrets, authn/authz | continuously |
| [12](12-observability-and-slo.md) | Observability & SLOs | Logs, metrics, traces, dashboards, alert thresholds, error budgets | Phase B |
| [13](13-testing-strategy.md) | Testing Strategy | Test pyramid, contract tests, voice regression, load profile, CI gates | Phase B |
| [14](14-infrastructure-and-deployment.md) | Infrastructure & Deployment | Docker, environments, CI/CD, migrations in CI, rollback, DR | Phase A |
| [15](15-implementation-roadmap.md) | **Implementation Roadmap** | **The ordered, step-by-step task list to execute** | **this is the work** |
| [16](16-runbooks.md) | Operational Runbooks | Kill switch, incident response, on-call, common failures | before go-live |
| [17](17-open-decisions.md) | Open Decisions & Assumptions | Blocking gates, assumption register, decision log | continuously |
| [18](18-platform-setup.md) | Platform Account Setup Runbook | Vapi keys/credentials/concurrency, n8n tokens/tags/credentials, Slack apps, MCP, secret inventory | the first platform deploy |
| [19](19-vapi-n8n-execution-plan.md) | **Vapi + n8n Execution Plan** | **⚡ ACTIVE — corrects verified API defects in 08/09, then builds the platform layers** | **08, 09, or any platform work** |

> ⚡ **Current work is [19-vapi-n8n-execution-plan.md](19-vapi-n8n-execution-plan.md).** Vagaro,
> RingCentral, Stripe and Google are blocked; Vapi and n8n Cloud are fully accessible, so the build order
> pivots to the conversation and orchestration layers first.
>
> Docs **08** and **09** were rewritten on 2026-08-03 against the live Vapi OpenAPI spec and a live probe
> of the n8n Cloud instance. Both carry a **§Corrections** table listing what was wrong and why it
> mattered. Where 08/09 and an older doc disagree on a Vapi or n8n technical matter, **08/09 win** —
> their claims are verified, the older ones were not.

---

## The one-paragraph summary of the system

A caller dials PalmLeaf's number. The call arrives at **Vapi**, which runs the "Grace" assistant
(speech-to-text → LLM → text-to-speech). When Grace needs a fact or an action she calls a **tool**,
which is an HTTPS request to the **Core API** — a typed TypeScript service that answers from a local
**Postgres availability mirror** in tens of milliseconds, never from Vagaro live. Anything that must
happen but must not block the conversation (SMS, payment links, writing the booking into Vagaro,
staff alerts) is written to a transactional **outbox** and executed by **workers** and **n8n** after
the tool has already returned. Vagaro is reconciled continuously in the background via webhooks and
polling. Every failure path degrades to a slower human path — never to a dropped caller.

---

## Non-negotiable invariants

These hold across every phase. A change that violates one of these is a rejected change.

| # | Invariant | Enforced by |
|---|---|---|
| **I1** | Vagaro is **never** called on the synchronous tool path | Lint rule + adapter layering + latency test |
| **I2** | No two active occupancy rows may overlap for the same provider | Postgres `EXCLUDE` constraint (§03) |
| **I3** | Every write tool is idempotent on `Idempotency-Key` | Middleware + `UNIQUE` index (§04, §06) |
| **I4** | Money and date-boundary decisions live in code, never in a prompt | `@grace/domain` pure functions + unit tests (§01) |
| **I5** | Grace never receives, transcribes, or stores a card number | Prompt guardrail + PCI boundary (§11) |
| **I6** | Medical disclosures set a boolean and are redacted; detail is never persisted | Redaction pass + column-level policy (§11) |
| **I7** | Recording disclosure is in the first utterance, always | Vapi `firstMessage` is a protected field in CI (§08) |
| **I8** | Every side effect that must survive a crash goes through the outbox | Transactional outbox (§07) |
| **I9** | No agent, MCP server, or human edits production directly | CI-only deploy, prod tokens absent from dev (§14) |
| **I10** | A tool call that exceeds its budget returns a graceful sentence, never a timeout | Deadline middleware (§04) |

---

## Phase map (what order things get built)

Phases here are **engineering** phases. They map onto, but are not identical to, the commercial
rollout phases in the design brief §14.

```
PHASE A — Foundation          (no external dependency, start immediately)
   Repo, tooling, CI, Docker, Postgres schema, migrations, config, observability skeleton
   ↓
PHASE B — Core domain          (no Vagaro access required)
   Domain package, availability engine, occupancy + holds, Core API, tool endpoints 1–4,
   idempotency, contract tests, load test
   ↓
PHASE C — Integration          (needs Vagaro creds, Vapi account, Google/Stripe/Twilio)
   Adapters, outbox + workers, booking saga, Track A/C, Vapi assistant, n8n workflows
   ↓
PHASE D — Telephony & launch   (needs carrier + client sign-off)
   Twilio SIP trunk, RingCentral forwarding, A2P 10DLC, after-hours pilot, kill switch drill
   ↓
PHASE E — Write-path hardening (gated on the Vagaro answer — see 17-open-decisions.md)
   Track B Playwright worker OR native Vagaro write API, reconciliation, drift monitoring
   ↓
PHASE F — Scale & optimize
   Multi-tenant onboarding, second PMS adapter, waitlist, reminders, Spanish assistant
```

**Phases A and B require no external approval and no third-party credential.** Begin there on day one;
they absorb the entire Vagaro and 10DLC waiting period.

---

## Conventions used throughout this plan set

- `MUST` / `MUST NOT` / `SHOULD` / `MAY` carry RFC 2119 weight. `MUST` items are CI-enforced where possible.
- Code blocks marked `// TARGET` are the intended final shape and may be written verbatim.
- Code blocks marked `// SKETCH` illustrate intent; the implementer chooses the exact form.
- `⛔ GATE` marks a point where work must stop until an external answer arrives.
- `✅ AC` marks an acceptance criterion. Every roadmap task in §15 has at least one.
- Identifiers in `snake_case` are database objects; `camelCase` are TypeScript; `kebab-case` are packages, files and URLs.
- All timestamps are `timestamptz`, stored UTC, rendered in `America/Chicago` at the edge only.

---

## How the implementing agent should work

1. Open [15-implementation-roadmap.md](15-implementation-roadmap.md). It is the task list.
2. Execute tasks **in order**. Each task names the documents you must have read to do it.
3. Do not skip a task's acceptance criteria. If an AC cannot be met, stop and log it in §17 rather than proceeding.
4. When a task requires a decision the plan does not cover, log it in §17 §Assumption Register, choose the
   most reversible option, and continue. Do not block on non-blocking ambiguity.
5. Commit per task, using the conventional-commit format in §02.
