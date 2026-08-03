# 17 — Open Decisions, Gates & Assumption Register

**Read:** continuously. **Update:** every time an answer arrives or an assumption is made.

This is the living document. Everything else in the plan set is stable; this file changes weekly.

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
| **A-02** | ~~Vapi signs `timestamp.rawBody` and sends `x-vapi-signature`~~ **LARGELY DISCHARGED 2026-08-03.** Verified against `api.vapi.ai/api-json`: `Server` has **no `secret` field**. Auth is a dashboard-created Custom Credential referenced by `credentialId`; the HMAC type lets us *choose* algorithm, signature header and timestamp header. The scheme is now true **by construction**, not by assumption — see §08 §3.3. Residual uncertainty moved to **A-13**. | Live OpenAPI spec | n/a | n/a |
| **A-03** | Vagaro OAuth token endpoint, region host pattern, and TTL are config-driven | Not documented publicly (Outreach Q19) | Config change only | Adapter config. |
| **A-04** | ~~Caller ID may be replaced on transfer back into RingCentral~~ **DOWNGRADED TO CONFIG 2026-08-03.** `TransferDestinationNumber.callerId` accepts `'{{customer.number}}'`, so preserving caller ID is a setting, not an open question (§08 §7.2). Keep the spoken number in the whisper as belt-and-braces. | Live OpenAPI spec | n/a | Config line item. |
| **A-05** | 15-minute slot grid suits massage booking | Industry norm | Change one constant | One constant + tests. |
| **A-06** | 4-min hold TTL / 15-min reservation TTL are right | Design brief §5.3 | Tenant settings, not code | Config. |
| **A-07** | A fast frontier model at temp 0.3 meets tool-selection accuracy | Design brief §4.1 | Model swap + full voice suite re-run | Config + a regression cycle. |
| **A-08** | us-west-2 minimises Vapi round-trip | Design brief §9 | Redeploy to another region | Infra, ~half a day. |
| **A-09** | ~45 calls/day, ~3 min average | Design brief §16, unvalidated | Cost model shifts; architecture does not | Commercial, not technical. **Validate with the 90-day RingCentral call logs.** |
| **A-10** | Providers each have a Google Calendar that can be shared with a service account | Track A prerequisite | Track A unavailable → Track C/D only | Depends on GATE-07 anyway. |
| **A-11** | Vagaro webhooks require a 2xx within 20s, retry 5× over 15 min | Design brief §5.1 | Receiver already ACKs in <100ms | None — the design is conservative. |
| **A-12** | The 90-day recording retention default is acceptable | Design brief §11.1 recommendation | Config change | Config (GATE-06). |

### 2.1 Assumptions raised by the 2026-08-03 API verification pass

Added while rewriting §08 and §09 against the live Vapi and n8n APIs. Each is a *residual* unknown —
the surrounding design is verified; only these specific points are not.

| ID | Assumption | Basis | If wrong | Blast radius |
|---|---|---|---|---|
| **A-13** | A Vapi HMAC custom credential can be configured to sign exactly `{timestamp}.{rawBody}` | Credential UI exposes a *Payload Format* field; its options are undocumented | Match §04 §6.1's verifier to whatever format it actually emits | One plugin. Discharge in the dashboard during C-11 — §18 §1.2. |
| **A-14** | `transferCall` to a PSTN number **does not work on web calls** | Community-reported; not confirmable in official docs | If it *does* work, we gain transfer testing earlier than expected | None — we already defer live transfer verification. Our only test channel this phase, so verify early. |
| **A-15** | `warm-transfer-experimental` honours `dialTimeout: 25` for ring-then-return | `dialTimeout` is documented against `sipVerb: 'dial'`; the mode is labelled experimental | Fall back to a `wait-for-operator` mode and accept no ring timeout | Transfer UX only. |
| **A-16** | A `backoffPlan` retry reuses the same `toolCallId` | HTTP-level retry of an identical body | Idempotency key would differ per retry → duplicate writes possible | **Directly threatens I3.** Verify in C-11 before enabling any `backoffPlan`. |
| **A-17** | `blocking: true\|false` behaves the same on async tools | Undocumented | Filler phrasing changes | Cosmetic. |
| **A-18** | `compliancePlan.recordingConsentPlan` is unsuitable for mid-call consent | Not investigated | `calls.recording_consent = false` becomes reachable; §08 §6.1 revisited | One config field. |
| **A-19** | `/grace-kill` may be restricted by a Slack user-id allowlist held in n8n | No authorization model specified anywhere | Anyone in the workspace could kill production | **Ship the allowlist before the command.** §09 §3.1. |
| **A-20** | WF-18's "call manager" step can wait for Phase F | `VoicePort.createOutboundCall` is Phase F (§05 §242) | Until then WF-18 ends at repeat-SMS + P1 `@here` | Escalation ceiling, documented. |
| **A-21** | The draft/publish split limits dashboard-edit blast radius | `activeVersion` appears in workflow payloads, but `/publish` is **404 on our instance** | ADR-0013's argument #4 weakens; detection becomes the only control | Security posture wording, not mechanism. |

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
| **D-7** | 13 workflows in n8n | **9 workflows in n8n, 10 moved into code, 5 new ops workflows added** *(corrected 2026-08-03 — the earlier "7 in n8n, 6 moved" miscounted: the strike-through rows in §09 §3 number ten, and the surviving set is nine once WF-00, the global error handler, is counted)* | Consequence of D-1 | Follows D-1. |
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
| Log aggregation vendor | Phase C | Whatever the cloud provider offers |
| Docker Compose → ECS | Second tenant, or deploy pain exceeds 1h/week | Compose |
| Staff admin console | Phase F, or when Slack-based task handling frustrates staff | Slack + SMS |
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
| Massagebook/Vagaro dual-running causes collisions | Med | **High** | Collision detection → P1 task + immediate call (§16 §8); push for GATE-12 | client |
| Client sign-off (GATE-02/04/05) drags past launch | **High** | Med | `approved_at` gating means the system degrades gracefully instead of quoting wrong policy — the risk becomes a containment-rate problem, not a liability | client |
| 10DLC delays SMS | Med | Med | Email fallback; adapter refuses to send unregistered traffic | us |
| Latency makes Grace feel robotic | Med | Med | Local mirror, async tools, filler phrases, measured SLOs | us |
| Illinois compliance miss | Low | **Severe** | §11 controls, CI invariants, legal review gate | us + counsel |
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
| 2026-08-01 | Approval gating (`approved_at`) on services, policies, knowledge, templates | this plan | Converts the §15 sign-off risk into a graceful degradation with an audit trail |
| | | | |

---

## 7. Weekly review checklist

Run this every Monday alongside the QA ritual (§12 §8):

- [ ] Any gate answered? Update §1, move the task in [15](15-implementation-roadmap.md), log it in §6.
- [ ] Any assumption invalidated? Update §2 and the affected document.
- [ ] Any new assumption made this week? Add it with its blast radius.
- [ ] Roadmap progress tracker updated.
- [ ] Risk likelihoods still accurate?
- [ ] Anything in §4 whose trigger has arrived?
- [ ] Client-side items still outstanding — chase, with a named person and a date.
