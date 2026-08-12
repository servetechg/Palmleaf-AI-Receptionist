# 00 — Index & Reading Order

**Status:** Active
**Read before:** anything else in this folder — it is the map.
**Last verified:** 2026-08-04 against the restructured document set and [`Docs/Completed/`](../Completed/00-STATUS.md).

> **In one paragraph:** this document is the entry point to the plan set. It says what each folder
> is for, which documents to read in which order, where the old numbered documents went, and the
> ten invariants that hold across every phase. It deliberately contains **no design** — every
> statement here is a pointer, so nothing in this file can drift out of step with the document it
> points at.

---

## 1. What this document set is

`Docs/PalmLeaf_AI_Receptionist_Architecture.md` is the **design brief**. It establishes *what*
Grace does, *why* Vagaro is a blocker, and what the commercial and legal constraints are. It is the
source of truth for product intent.

This set is the **engineering foundation**. It converts that brief into a buildable system:
repository layout, database DDL, module boundaries, interface signatures, error taxonomies,
deployment topology, and an ordered task list where every task has an acceptance test.

> **Rule when they conflict.** On a *technical* matter, this set wins and the conflict is logged in
> [09-open-decisions](09-open-decisions.md). On a *product, policy, legal or commercial* matter, the
> design brief wins and you must stop and ask. **Never resolve a policy conflict yourself.**

---

## 2. The four folders

| Folder | Contains | Edit by hand? |
|---|---|---|
| **`Docs/plans/`** | Everything buildable now. Eleven documents. **This folder.** | ✅ yes |
| **`Docs/reference/`** | Blocked work — the database, Core API, adapters, telephony, infrastructure. Rewritten for Python and **frozen** until access arrives. | ✅ yes |
| **`Docs/generated/`** | Per-tool and per-workflow reference, written from the code that defines it. | ⛔ **never** — run `make docs` |
| **`Docs/Completed/`** | The delivery record: what was built, what was *verified*, and with what evidence. | ✅ yes |

**Why plans and reference are separate.** Roughly 3,200 lines described work that cannot start —
Postgres, Core API, adapters, telephony, infrastructure — sitting in the same reading path as the
two layers actually being built. Splitting them means `plans/` can be read end to end in an
afternoon, and nothing is lost: every frozen document was **rewritten for Python before being
moved**, so pulling one back is a `git mv` and nothing else.

**Why `generated/` exists.** Per-tool documentation used to cover one tool out of fifteen, spread
across three documents, with its parameters shown as a code sample in the wrong document. It is now
generated from `TOOL_REGISTRY` and the workflow JSON, and `make docs-check` fails CI when it goes
stale. It physically cannot drift.

---

## 3. Reading order

**Read [01](01-architecture.md) and [02](02-python-and-repo.md) before writing any code.** They are
load-bearing for everything else.

| # | Document | What it settles | Read before |
|---|---|---|---|
| [01](01-architecture.md) | Architecture Foundation & ADRs | Layers, boundaries, the two paths, 18 decisions with exit criteria | anything |
| [02](02-python-and-repo.md) | Python, Repo & Conventions | Layout, uv, Pydantic, mypy, ruff, import boundaries, the Makefile | writing any file |
| [03](03-vapi-layer.md) | Vapi Conversation Layer | Assistant config, 15 tools, the prompt, greeting, transfer, drift-checked deploy | any Vapi work |
| [04](04-n8n-layer.md) | n8n Orchestration Layer | What n8n owns, 11 workflows, which run and which are dormant, deploy and lint | any workflow work |
| [05](05-security-and-compliance.md) | Security & Compliance | Consent, BIPA, PHI, the PCI boundary, secrets, authorization | continuously |
| [06](06-platform-setup.md) | Platform Setup Runbook | The manual click-through steps config-as-code cannot perform | the first deploy, or onboarding |
| [07](07-testing.md) | Testing | What is tested today, the CI gate, simulations, what is planned | writing a test |
| [08](08-roadmap.md) | **Implementation Roadmap** | **The ordered task list** | **this is the work** |
| [09](09-open-decisions.md) | Open Decisions & Assumptions | Gates, assumptions, divergences, the decision log | continuously |
| [10](10-access-and-credentials.md) | **Access & Credentials** | **What we still need, from whom, and what it unlocks — in plain terms** | asking the client for anything |
| [11](11-knowledge-intake.md) | **Knowledge Intake & Decision Pack** | **Every fact Grace needs, in the shape the system stores it — plus every question this project still has to ask** | any content, policy or scope conversation with the client |

Then, when a blocked area unblocks: [`Docs/reference/`](../reference/00-README.md).

> ⚡ **Where the work is right now.** Phases A and B are done — Grace is deployed with 15 tools and
> six n8n workflows are live. **Phase C (domain, database, Core API) is unblocked and not started;
> it is the entire remaining critical path.** Two half-day tasks come first: drive one live web call
> (B-12) and trigger WF-20 by hand (B-13). See [08-roadmap](08-roadmap.md) §8.
>
> 📋 **What is actually built:** [`Docs/Completed/`](../Completed/00-STATUS.md). Treat anything not
> listed as verified there as unproven, however finished the code looks.

---

## 4. Where the old documents went

The set was renumbered on 2026-08-04. Old links will not resolve; this is the map.

| Old | New | Note |
|---|---|---|
| `00-INDEX.md` | [00-INDEX](00-INDEX.md) | this document, rewritten |
| `01-architecture-foundation.md` | [01-architecture](01-architecture.md) | + ADR-0015…0018 |
| `02-repository-and-tooling.md` | [02-python-and-repo](02-python-and-repo.md) | **rewritten entirely** — the old content described a stack that no longer exists |
| `03-data-model.md` | [reference/data-model](../reference/data-model.md) | frozen |
| `04-core-api-service.md` | [reference/core-api](../reference/core-api.md) | frozen |
| `05-provider-adapters.md` | [reference/provider-adapters](../reference/provider-adapters.md) | frozen |
| `06-availability-engine.md` | [reference/availability-engine](../reference/availability-engine.md) | frozen |
| `07-booking-write-path.md` | [reference/booking-write-path](../reference/booking-write-path.md) | frozen |
| `08-vapi-layer.md` | [03-vapi-layer](03-vapi-layer.md) | |
| `09-n8n-layer.md` | [04-n8n-layer](04-n8n-layer.md) | |
| `10-telephony-and-messaging.md` | [reference/telephony](../reference/telephony.md) | frozen |
| `11-security-and-compliance.md` | [05-security-and-compliance](05-security-and-compliance.md) | |
| `12-observability-and-slo.md` | [reference/observability](../reference/observability.md) | frozen |
| `13-testing-strategy.md` | [07-testing](07-testing.md) | merged with the delivery record |
| `14-infrastructure-and-deployment.md` | [reference/infrastructure](../reference/infrastructure.md) | frozen |
| `15-implementation-roadmap.md` | [08-roadmap](08-roadmap.md) | re-cut, not rewritten |
| `16-runbooks.md` | [reference/runbooks](../reference/runbooks.md) | frozen |
| `17-open-decisions.md` | [09-open-decisions](09-open-decisions.md) | |
| `18-platform-setup.md` | [06-platform-setup](06-platform-setup.md) | |
| `19-vapi-n8n-execution-plan.md` | [`Completed/EXECUTED-vapi-n8n-plan.md`](../Completed/EXECUTED-vapi-n8n-plan.md) | executed; its output *is* `Completed/` |

**Acceptance-criterion IDs kept their original prefixes** — `AC-08.x`, `AC-09.x`, `AC-11.x`,
`AC-13.x`, `AC-15.x`, `AC-17.x` — even though the documents were renumbered. They are cited as
delivery evidence throughout `Docs/Completed/`, and renumbering them would orphan that record for
no gain.

---

## 5. The system in one paragraph

A caller dials PalmLeaf's number. The call arrives at **Vapi**, which runs the Grace assistant
(speech-to-text → LLM → text-to-speech). When Grace needs a fact or an action she calls a **tool**,
which is an HTTPS request to the **Core API** — a typed Python service that answers from a local
**Postgres availability mirror** in tens of milliseconds, never from Vagaro live. Anything that
must happen but must not block the conversation (SMS, payment links, writing the booking into
Vagaro, staff alerts) is written to a transactional **outbox** and executed by **workers** and
**n8n** after the tool has already returned. Vagaro is reconciled continuously in the background.
Every failure path degrades to a slower human path — never to a dropped caller.

---

## 6. Non-negotiable invariants

These hold across every phase. A change that violates one is a rejected change.

| # | Invariant | Enforced by |
|---|---|---|
| **I1** | Vagaro is **never** called on the synchronous tool path | `import-linter` contract + adapter layering + latency test |
| **I2** | No two active occupancy rows may overlap for one provider | Postgres `EXCLUDE` constraint ([data-model](../reference/data-model.md)) |
| **I3** | Every write tool is idempotent on its idempotency key | Middleware + `UNIQUE` index |
| **I4** | Money and date-boundary decisions live in code, never in a prompt | `grace_domain` pure functions + unit tests |
| **I5** | Grace never receives, transcribes, or stores a card number | Prompt guardrail + PCI boundary ([05](05-security-and-compliance.md)) |
| **I6** | Medical disclosures set a boolean and are redacted; detail is never persisted | Redaction pass + column-level policy |
| **I7** | Recording disclosure is in the first utterance, always | Two CI greps — the greeting file **and** its injection ([07](07-testing.md) §3) |
| **I8** | Every side effect that must survive a crash goes through the outbox | Transactional outbox |
| **I9** | No agent, MCP server, or human edits production directly | CI-only deploy; relaxed to "CI is the only publisher" by ADR-0013 |
| **I10** | A tool call that exceeds its budget returns a graceful sentence, never a timeout | Deadline middleware (ADR-0012) |

⚠️ **I1 is currently unenforced.** The boundary rules were lost in the language port, and their
replacement (ADR-0018) is task **A-08**, not yet done. Contract 1 is an hour's work and should not
wait for the rest.

---

## 7. Conventions used throughout

- `MUST` / `MUST NOT` / `SHOULD` / `MAY` carry RFC 2119 weight. `MUST` items are CI-enforced where
  possible.
- Blocks marked `TARGET` are the intended final shape and may be written close to verbatim.
- `⛔ GATE` marks a point where work stops until an external answer arrives.
- `✅ AC` marks an acceptance criterion. Every roadmap task has at least one.
- Cross-references are always `[document](path.md) §N` — **never a line number**, which rots on any
  edit. `make docs-lint` rejects the line-number form.
- All timestamps are `timestamptz`, stored UTC, rendered in `America/Chicago` at the edge only.
- Naming across the four syntaxes in play is settled in
  [02-python-and-repo](02-python-and-repo.md) §5.

---

## 8. The document template

Every document in `plans/` and `reference/` has the same header and shape, and `make docs-lint`
enforces it, so the inconsistency that produced this restructure cannot creep back.

```markdown
NN — Title                                  <- as an H1

**Status:** Active · or · Frozen — unblocks when <condition>
**Read before:** <the trigger that sends someone here>
**Implements:** ADR-xxxx, ADR-yyyy          (omit if none)
**Enforces:** I5, I7                        (omit if none)
**Last verified:** <date> against <what>

> **In one paragraph:** what this document settles, and what it deliberately does not.

1. …   2. …                                 <- as numbered H2s
N. Acceptance criteria                      <- always this exact heading, always last but one
N+1. Open questions                         <- always last; empty is fine, absent is not
```

The linter checks that the header block is complete; that there is exactly one H1, on the first
line; that sections are numbered contiguously from 1; that **no heading appears inside a fenced
block** — which is what made the Vapi prompt content show up as ten top-level sections; that only
one cross-reference syntax is used; and that the superseded stack is never named except on a line
explaining what replaced it.

---

## 9. Acceptance criteria

✅ **AC-00.1** `make docs-lint` passes on every document in `plans/` and `reference/`.
✅ **AC-00.2** Every link in §3 and §4 resolves to a file that exists.
✅ **AC-00.3** A recursive, case-insensitive search for the withdrawn chat platform across
`Docs/plans`, `Docs/reference`, `src` and `platform` returns nothing.
✅ **AC-00.4** The same search for the replaced stack — `typescript|pnpm|fastify|drizzle|bullmq|vitest|eslint|turborepo` — returns nothing except on a line naming what replaced it.
✅ **AC-00.5** `make docs` run twice is byte-identical, and `make docs-check` fails when a tool
description changes without regeneration.

## 10. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-00.1** | When does a `reference/` document come back into `plans/`? | Each carries an unblocking condition, but nothing watches for it. The weekly review ([09-open-decisions](09-open-decisions.md) §7) is the natural place, and it does not currently check. | Engineering, weekly |
| **Q-00.2** | Should the design brief be folded into this set? | It remains the source of truth for product intent and uses its own §-numbering — which is why cross-references to it are deliberately left un-rewritten. Two numbering schemes in one corpus is a standing source of confusion. | Product |
