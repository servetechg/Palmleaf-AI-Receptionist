# 09 — Open Decisions, Gates & Assumption Register

**Status:** Active
**Read before:** starting any blocked task — and then continuously.
**Last verified:** 2026-08-04 against the ADRs in [01-architecture](01-architecture.md) §4 and the restructured document set.

> **In one paragraph:** this is the living document. Everything else in the plan set is stable;
> this file changes weekly. It records the twelve external gates the build cannot answer for
> itself, the assumptions made so work could proceed anyway, the places this plan deliberately
> diverges from the design brief, and an append-only decision log. It deliberately holds **no
> design** — only the things not yet decided, and who decides them.
---

## 1. Blocking gates

A **gate** is an external answer the build cannot generate for itself. Each names exactly what is blocked
and — importantly — what is *not* blocked, so work never stops unnecessarily.

| ID | Question | Owner | Asked | Answer | Blocks | Does **not** block |
|---|---|---|---|---|---|---|
| **GATE-01** | Does Vagaro offer appointment create/update/cancel and availability search, today or under an enterprise agreement? | Vagaro Enterprise Sales + in-app form | ☐ | ☐ | Phase E path selection (E-01a vs E-01b) | Phases A–D entirely. The adapter, saga, and capability flag are built for either answer. |
| **GATE-02** | Cancellation policy: "100% charge" or "deposit non-refundable"? Exact spoken wording. | PalmLeaf | ☐ | ☐ | Grace quoting a cancellation fee | The 48-hour engine, which is built and tested; unapproved policy → graceful transfer |
| **GATE-03** | Vagaro numeric rate limits, pagination convention, error codes, OAuth token path/TTL, sandbox availability | Vagaro | ☐ | ☐ | Tuning the adapter's token bucket | Building the adapter — conservative defaults are in place |
| **GATE-04** | Full service catalog: durations, member/non-member prices, buffer times, deposit amounts | PalmLeaf | ☐ | ☐ | Grace quoting any price | Everything — seeds carry placeholders with `approved_at = NULL` |
| **GATE-05** | Approved greeting wording (four variants submitted); provider roster with names, specialties, schedules | PalmLeaf | ☐ | ☐ | Production launch | Development; the recommended greeting ships until replaced, and any replacement must pass the CI disclosure check |
| **GATE-06** | Recording and transcript retention period | PalmLeaf + counsel | ☐ | ☐ | Nothing — it is a config value | Everything |
| **GATE-07** | **Does a Google Calendar event synced into Vagaro actually *block* the slot, or is it cosmetic?** | us — 30-minute test in the live account | ☐ | ☐ | Track A implementation (C-07) and the whole composite write strategy | Phases A, B; Tracks C and D |
| **GATE-08** | Do Vagaro CC processing and Stripe deposits reconcile acceptably for the bookkeeper? | PalmLeaf bookkeeper | ☐ | ☐ | Which payments adapter ships | `PaymentsPort`, which is unchanged either way |
| **GATE-09** | A2P 10DLC brand + campaign verified | Twilio | ☐ | ☐ | Production SMS volume | Everything else; email fallback covers the gap |
| **GATE-10** | Written client authorization to automate their own booking widget + Vagaro ToS review | PalmLeaf + us | ☐ | ☐ | Track B (E-01b) | All other work |
| **GATE-11** | RingCentral: can 847.961.4800 be ported/forwarded? Forwarding concurrency limits? Is caller ID preserved on transfer back? | RingCentral | ☐ | ☐ | Final telephony topology | Twilio trunk build, which proceeds regardless |
| **GATE-12** | Massagebook → Vagaro cutover date. Is Vagaro the sole source of truth on day one? | PalmLeaf | ☐ | ☐ | Safe daytime rollout | After-hours pilot |

### 1.1 The three that actually matter

- **GATE-07** is the cheapest and the most consequential. It costs 30 minutes, no code, and determines
  whether the recommended write-path composite is viable at all. **Do it on day one.**
- **GATE-01** has the longest clock (7 business days) and decides whether an entire application
  (`booking-worker`) exists. Send it on day one.
- **GATE-12** is the one most likely to cause a customer-visible failure that looks like an AI bug but is
  an operations problem. Push hard for a hard cutover date before daytime rollout.

---

## 2. Assumption register

Assumptions made so work could proceed. Each is reversible; each names its blast radius.

| ID | Assumption | Basis | If wrong | Blast radius |
|---|---|---|---|---|
| **A-01** | PalmLeaf is tenant one of a productized service, not a one-off | The engagement is run by an agency (`servetechglobal.com`); design brief describes a repeatable pattern | Multi-tenant scaffolding is inert; nothing to remove | ~1 column + 1 policy per table. Negligible. |
| **A-02** | ~~Vapi signs `timestamp.rawBody` and sends `x-vapi-signature`~~ **LARGELY DISCHARGED 2026-08-03.** Verified against `api.vapi.ai/api-json`: `Server` has **no `secret` field**. Auth is a dashboard-created Custom Credential referenced by `credentialId`; the HMAC type lets us *choose* algorithm, signature header and timestamp header. The scheme is now true **by construction**, not by assumption — see [03-vapi-layer](03-vapi-layer.md) §3.3. Residual uncertainty moved to **A-13**. | Live OpenAPI spec | n/a | n/a |
| **A-03** | Vagaro OAuth token endpoint, region host pattern, and TTL are config-driven | Not documented publicly (Outreach Q19) | Config change only | Adapter config. |
| **A-04** | ~~Caller ID may be replaced on transfer back into RingCentral~~ **DOWNGRADED TO CONFIG 2026-08-03.** `TransferDestinationNumber.callerId` accepts `'{{customer.number}}'`, so preserving caller ID is a setting, not an open question ([03-vapi-layer](03-vapi-layer.md) §7.2). Keep the spoken number in the whisper as belt-and-braces. | Live OpenAPI spec | n/a | Config line item. |
| **A-05** | 15-minute slot grid suits massage booking | Industry norm | Change one constant | One constant + tests. |
| **A-06** | 4-min hold TTL / 15-min reservation TTL are right | Design brief §5.3 | Tenant settings, not code | Config. |
| **A-07** | A fast frontier model at temp 0.3 meets tool-selection accuracy | Design brief §4.1 | Model swap + full voice suite re-run | Config + a regression cycle. |
| **A-08** | us-west-2 minimises Vapi round-trip | Design brief §9 | Redeploy to another region | Infra, ~half a day. |
| **A-09** | ~45 calls/day, ~3 min average | Design brief §16, unvalidated | Cost model shifts; architecture does not | Commercial, not technical. **Validate with the 90-day RingCentral call logs.** |
| **A-10** | Providers each have a Google Calendar that can be shared with a service account | Track A prerequisite | Track A unavailable → Track C/D only | Depends on GATE-07 anyway. |
| **A-11** | Vagaro webhooks require a 2xx within 20s, retry 5× over 15 min | Design brief §5.1 | Receiver already ACKs in <100ms | None — the design is conservative. |
| **A-12** | The 90-day recording retention default is acceptable | Design brief §11.1 recommendation | Config change | Config (GATE-06). |

### 2.1 Assumptions raised by the 2026-08-03 API verification pass

Added while rewriting [03-vapi-layer](03-vapi-layer.md) and [04-n8n-layer](04-n8n-layer.md) against the live Vapi and n8n APIs. Each is a *residual* unknown —
the surrounding design is verified; only these specific points are not.

| ID | Assumption | Basis | If wrong | Blast radius |
|---|---|---|---|---|
| **A-13** | A Vapi HMAC custom credential can be configured to sign exactly `{timestamp}.{rawBody}` | Credential UI exposes a *Payload Format* field; its options are undocumented | Match [core-api](../reference/core-api.md) §6.1's verifier to whatever format it actually emits | One plugin. Discharge in the dashboard during C-11 — [06-platform-setup](06-platform-setup.md) §1.2. |
| **A-14** | `transferCall` to a PSTN number **does not work on web calls** | Community-reported; not confirmable in official docs | If it *does* work, we gain transfer testing earlier than expected | None — we already defer live transfer verification. Our only test channel this phase, so verify early. |
| **A-15** | `warm-transfer-experimental` honours `dialTimeout: 25` for ring-then-return | `dialTimeout` is documented against `sipVerb: 'dial'`; the mode is labelled experimental | Fall back to a `wait-for-operator` mode and accept no ring timeout | Transfer UX only. |
| **A-16** | A `backoffPlan` retry reuses the same `toolCallId` | HTTP-level retry of an identical body | Idempotency key would differ per retry → duplicate writes possible | **Directly threatens I3.** Verify in C-11 before enabling any `backoffPlan`. |
| **A-17** | `blocking: true\|false` behaves the same on async tools | Undocumented | Filler phrasing changes | Cosmetic. |
| **A-18** | `compliancePlan.recordingConsentPlan` is unsuitable for mid-call consent | Not investigated | `calls.recording_consent = false` becomes reachable; [03-vapi-layer](03-vapi-layer.md) §6.1 revisited | One config field. |
| ~~**A-19**~~ | ~~`/grace-kill` restricted by a chat-platform user-id allowlist held in n8n~~ **RETIRED 2026-08-04.** The workflow that would have carried the command (WF-14) is withdrawn along with the chat platform itself — [04-n8n-layer](04-n8n-layer.md) §3.1. **The authorization question survived the surface** and is re-raised as **Q-05.1**: today the kill switch is reachable by anyone holding the internal API token, which is too broad. | n/a | n/a | n/a |
| **A-20** | WF-18's "call manager" step can wait for Phase F | `VoicePort.createOutboundCall` is Phase F ([provider-adapters](../reference/provider-adapters.md)) | Until then WF-18 ends at a repeat SMS plus a staff notification | Escalation ceiling, documented. |
| **A-21** | The draft/publish split limits dashboard-edit blast radius | `activeVersion` appears in workflow payloads, but `/publish` is **404 on our instance** | ADR-0013's argument #4 weakens; detection becomes the only control | Security posture wording, not mechanism. |

### 2.2 Assumptions introduced by the Python ADRs (2026-08-04)

ADR-0015 to ADR-0018 were taken so the blocked documents could be rewritten in Python without
holes. Three are library choices; **the fourth is a safety guarantee that was being lost
silently.** Each carries a residual assumption, and the first of them is load-bearing.

| ID | Assumption | Basis | If wrong | Blast radius |
|---|---|---|---|---|
| **A-22** | arq's `job_id` dedupe covers the outbox retry schedule (ADR-0015) | Chosen by analogy with the queue it replaces, whose dedupe the outbox design leans on explicitly | arq deduplicates within a *keep-alive window*, not for the job's lifetime. A retried dispatch after the window could send a caller a **second confirmation text** | **Bounded, and already mitigated by design.** At-least-once delivery requires a consumer-side `UNIQUE` constraint regardless, which closes it. **Re-derive in C-04; do not assume.** |
| **A-23** | Alembic can autogenerate and round-trip `EXCLUDE … USING gist` plus the `btree_gist` extension (ADR-0016) | Verified against documentation, not against a running migration | Those migrations become hand-written | Half a day, and only if discovered late. C-02 answers it. |
| **A-24** | FastAPI middleware plus `Depends` reproduces the exact ordering [core-api](../reference/core-api.md) §3 requires (ADR-0017) | The replaced framework enforced order through plugin encapsulation; FastAPI has no equivalent construct | Signature verification could run after body parsing, or the deadline could start after handler work begins — both silent correctness failures | [core-api](../reference/core-api.md) §3 and §6 are rewritten, not renamed. Verify with an ordering test in C-05. |
| **A-25** | `import-linter` can express every boundary the replaced linter enforced (ADR-0018) | Its `forbidden` contract type maps directly onto the old rules | ruff cannot express per-package boundaries at all, so there is no fallback — the I1 guarantee would stay unenforced | **Directly threatens I1.** Prove each contract fails on a deliberate violation (AC-02.3). |

> **A-22 and A-25 deserve the most attention.** A-22 protects a caller from a duplicate message;
> A-25 protects a caller from dead air. Both are guarantees the architecture claims and neither is
> currently proven under the new stack.

---

## 3. Divergences from the design brief

Recorded explicitly so reviewers can challenge them.

| # | Design brief says | This plan says | Rationale | Reversibility |
|---|---|---|---|---|
| **D-1** | n8n serves the 13 Vapi tools (WF-01…WF-04) | Core API serves them; n8n keeps ops workflows | ADR-0002: latency tail, transactions, testable money logic, DB-level concurrency | High — handlers are thin; n8n could call the same domain logic via one endpoint per tool. ~1 day. |
| **D-2** | `slot_holds` and `appointments_mirror` as separate concerns | One `calendar_occupancy` table with an `EXCLUDE` constraint | ADR-0004: a single constraint cannot be bypassed by any code path | Low, and deliberately so — this is the double-booking guarantee. |
| **D-3** | Side effects called from workflow branches | Transactional outbox for every side effect | ADR-0005: a crash between commit and enqueue silently loses a deposit link or a confirmation | Low. |
| **D-4** | Single-tenant design | Multi-tenant schema, single-tenant deployment | ADR-0008: retrofitting tenancy is a rewrite; adding it now is a column | Inert if unused. |
| **D-5** | Hold sweeper on a 1-minute cron | 30-second sweeper | Halves worst-case wasted hold time at no cost | Trivial. |
| **D-6** | Track B introduced alongside Track A | Track C ships **first**, then A, then B | Track C is zero-risk, always available, and is the Phase 1 revenue path. It is also the fallback for everything else, so it must exist before anything depends on it. | Ordering only. |
| **D-7** | 13 workflows in n8n | **11 workflows in n8n, 10 moved into code** *(corrected again 2026-08-04: WF-14 is withdrawn with the chat platform, and WF-20/21/22 are added. The earlier counts of "7 in n8n, 6 moved" and "9 in n8n" were both wrong — see [04-n8n-layer](04-n8n-layer.md) §3)* | Consequence of D-1 | Follows D-1. |
| **D-8** | Two n8n instances, dev and prod, with CI as the only writer to prod | **One n8n Cloud instance**, dev/prod separated by tag + name prefix + webhook path prefix + per-env credentials | We have a single pay-as-you-go Cloud subscription; environments and source control are higher-tier features | **Low** — ADR-0013 records the relaxation of I9 and its exit criteria. Moving to two instances is a config change, not a redesign. |

**None of these change the product, the caller experience, the commercial model, or any compliance
position.** They are all internal engineering choices, and D-1 — the only significant one — has a
documented one-day path back.

---

## 4. Deferred decisions

Not blocking; decide when the trigger arrives.

| Decision | Decide when | Default until then |
|---|---|---|
| Managed vs self-hosted Postgres in production | Phase D | Managed |
| **Which hosted Postgres for n8n reporting** — Neon or Supabase | **Now.** Unblocked, small, and the durable reporting record does not exist until it is done | n8n Data Tables, which are capped and not SQL-queryable ([04-n8n-layer](04-n8n-layer.md) §9) |
| Log aggregation vendor | Phase C | Whatever the cloud provider offers |
| Docker Compose → ECS | Second tenant, or deploy pain exceeds 1h/week | Compose |
| Staff admin console | Phase F, or sooner — it is what restores a one-click kill switch (Q-04.2) | Runbook + SMS |
| Spanish assistant | Phase F | English only |
| Outbound reminder calls vs SMS-only | Phase F | SMS |
| Recording storage: Vapi-hosted vs our bucket | Phase D, when retention policy lands | Vapi-hosted with a purge job |
| Second PMS adapter | First non-Vagaro tenant | Vagaro only |

---

## 5. Risk register (engineering view)

Complements the design brief §17 commercial register.

| Risk | L | I | Mitigation | Owner |
|---|---|---|---|---|
| GATE-07 fails — synced calendar events do not block Vagaro slots | Med | **High** | Test on day one; Track C + D are fully sufficient for Phase 1 without it | us |
| Vapi signature scheme differs from A-02 | Med | Low | Verify empirically before staging | us |
| Vagaro rate limits are tighter than assumed | Med | Med | Conservative token bucket; mirror means in-call reads never hit them | us |
| Track B breaks on a UI change | **High** | Med | Canary, screenshots, selector registry, staff fallback, budgeted hours | us |
| Massagebook/Vagaro dual-running causes collisions | Med | **High** | Collision detection → P1 task + immediate call ([runbooks](../reference/runbooks.md) §8); push for GATE-12 | client |
| Client sign-off (GATE-02/04/05) drags past launch | **High** | Med | `approved_at` gating means the system degrades gracefully instead of quoting wrong policy — the risk becomes a containment-rate problem, not a liability | client |
| 10DLC delays SMS | Med | Med | Email fallback; adapter refuses to send unregistered traffic | us |
| Latency makes Grace feel robotic | Med | Med | Local mirror, async tools, filler phrases, measured SLOs | us |
| Illinois compliance miss | Low | **Severe** | [05-security-and-compliance](05-security-and-compliance.md) controls, CI invariants, legal review gate | us + counsel |
| Over-engineering for one client | Med | Low | Phases A–B are ~3 weeks; every "extra" (multi-tenancy, ports, outbox) has a named payoff and near-zero cost | us |

---

## 6. Decision log

Append-only. Every resolved gate and every significant choice lands here with a date and a rationale.

| Date | Decision | By | Rationale |
|---|---|---|---|
| 2026-07-30 | Vagaro has no appointment-write API; design the write path around it | design brief §1 | Verified against Vagaro's own documentation |
| 2026-07-31 | Telephony: Twilio Elastic SIP Trunking, not RingCentral SIP credentials | design brief §3.2 | RC credentials are registrar, not trunk; stated repeatedly by RC |
| 2026-07-31 | Code-first: Vapi and n8n both driven from a git repo via CI | design brief §20 | Both platforms are fully API-driven |
| 2026-08-01 | Core API owns synchronous tools; n8n owns async ops (ADR-0002) | this plan | Latency tail, transactions, testability of money logic |
| 2026-08-01 | Double-booking prevented by a Postgres `EXCLUDE` constraint (ADR-0004) | this plan | No code path can bypass a database constraint |
| 2026-08-01 | Transactional outbox for all side effects (ADR-0005) | this plan | Durability across the commit/enqueue boundary |
| 2026-08-01 | Multi-tenant schema from commit one (ADR-0008) | this plan | Retrofit cost is a rewrite; build cost is a column |
| 2026-08-01 | Approval gating (`approved_at`) on services, policies, knowledge, templates | this plan | Converts the client sign-off risk into graceful degradation with an audit trail |
| 2026-08-03 | One n8n Cloud instance; I9 relaxed to "CI is the only publisher" (ADR-0013) | this plan | A second instance is disproportionate overhead for a single-tenant pilot; detection replaces prevention, stated honestly |
| 2026-08-03 | **Python, not TypeScript** (ADR-0014, supersedes ADR-0001) | this plan | What the team can maintain and debug at 2am. Pydantic reproduces the generate-everything-from-one-schema pipeline exactly, so the strongest argument for the old stack was parity, not advantage. 3,232 lines ported; the same switch after Core API would be 15,000+ |
| 2026-08-03 | **A third-party chat platform is out of scope** | this plan | Staff notification routes through Core API's `/internal/notify/*` instead, so 10DLC, consent and opt-out enforcement live in one place and cannot be bypassed by adding a node to a canvas. Retires A-19 and withdraws WF-14 |
| 2026-08-04 | Job queue: **arq** (ADR-0015) | this plan | Keeps Redis, already in the topology; async-native; closest analogue to the outbox design. Celery is heavier and sync-first, Dramatiq lacks scheduling. **Dedupe guarantee to be re-derived (A-22)** |
| 2026-08-04 | Database toolkit: **SQLAlchemy 2.0 + Alembic** (ADR-0016, supersedes ADR-0009) | this plan | Expresses the `EXCLUDE` constraint via `postgresql.ExcludeConstraint`. Named rather than assumed, because the whole booking guarantee rests on it |
| 2026-08-04 | Web framework: **FastAPI** (ADR-0017) | this plan | Not a rename — the replaced framework's ordered plugin encapsulation has no analogue, so the request-lifecycle spec is rewritten rather than renamed |
| 2026-08-04 | Import boundaries: **import-linter** (ADR-0018) | this plan | **ruff cannot express per-package boundaries.** Without this the I1 protection disappears with no error and no warning. Restores AC-02.3 and AC-04.10 |
| 2026-08-04 | Reporting persistence: **n8n Data Tables now, Postgres skeleton switched off** | this plan | n8n Cloud cannot reach a laptop database. Shipping the path disabled means turning it on is five steps and no redesign |
| 2026-08-04 | Documentation split into `plans/` (buildable now) and `reference/` (frozen) | this plan | ~3,200 lines described blocked work in the same reading path as active work. Per-tool and per-workflow reference is now generated from code and CI-checked, so it cannot drift |

---

## 7. Weekly review checklist

Run this every Monday alongside the QA ritual ([observability](../reference/observability.md) §8):

- [ ] Any gate answered? Update §1, move the task in [08-roadmap](08-roadmap.md), log it in §6.
- [ ] Any assumption invalidated? Update §2 and the affected document.
- [ ] Any new assumption made this week? Add it with its blast radius.
- [ ] Roadmap progress tracker updated.
- [ ] Risk likelihoods still accurate?
- [ ] Anything in §4 whose trigger has arrived?
- [ ] Client-side items still outstanding — chase, with a named person and a date.
- [ ] `make docs-lint` still green, and any new document carries its header block.

---

## 8. Acceptance criteria

✅ **AC-17.1** Every ⛔ task in [08-roadmap](08-roadmap.md) names a gate that exists in §1.
✅ **AC-17.2** Every assumption in §2 names its basis, its consequence if wrong, and its blast
radius. An assumption without a blast radius is a guess wearing a table row.
✅ **AC-17.3** Every ADR accepted in [01-architecture](01-architecture.md) §4 has a corresponding
dated entry in the §6 decision log.
✅ **AC-17.4** Retired assumptions are struck through with the reason and the date, never deleted —
so a reader can tell the difference between "resolved" and "never considered".
✅ **AC-17.5** The weekly review in §7 has actually been run, and §6 shows it.

## 9. Open questions

This whole document is open questions. What follows is only the meta-question: whether the register
itself is being maintained.

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-09.5** | Has Illinois enacted a chatbot/AI-disclosure law yet? | Grace's greeting deliberately omits an AI label, which is lawful today (SB 3368 and SB 317 are pending, not enacted). Enactment flips it back to required — a one-line change, but only if somebody is watching. See [05-security-and-compliance](05-security-and-compliance.md) §12.4. | Engineering, quarterly |
| **Q-09.1** | Is the weekly review in §7 actually happening? | The register is only useful if it is current, and nothing enforces the ritual. The decision log has no entry recording a review — which either means it has not run, or that running it is not being logged. Both are problems. | Engineering, weekly |
| **Q-09.2** | Who owns chasing the client-side gates? | GATE-02, GATE-04, GATE-05 and GATE-12 are all "PalmLeaf" and all unanswered. §5 already rates client sign-off dragging past launch as **high likelihood**. An unowned chase is not a chase. | Commercial |
| **Q-09.3** | Should A-09 (~45 calls/day) be validated before Phase D? | It drives the cost model and the concurrency target. Validating it needs only the 90-day RingCentral call logs, which nobody has pulled. Cheap, and it de-risks a commercial conversation rather than a technical one. | Commercial |
