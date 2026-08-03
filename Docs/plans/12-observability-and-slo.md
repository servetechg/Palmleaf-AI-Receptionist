# 12 — Observability & SLOs

**Read before:** Phase B. Instrumentation is written with the code, not bolted on before launch.

---

## 1. The question every signal must answer

For a voice product the operative question is not "is the server up?" — it is **"did the last caller have
a good experience, and if not, why?"** Every dashboard and alert below is judged against that.

Three pillars, one correlation id:

| Signal | Tool | Retention |
|---|---|---|
| Structured logs | Pino → JSON → log aggregator (Better Stack / Loki / CloudWatch) | 30 days |
| Metrics | prom-client → Prometheus → Grafana | 13 months (downsampled) |
| Traces | OpenTelemetry → OTLP → Tempo/Jaeger | 7 days (100% sampled — volume is tiny) |
| Errors | Sentry | 90 days |

**`vapiCallId` is the correlation key.** It appears on every log line, every span, every
`tool_invocations` row, every `booking_events` row, and every staff task. Given a complaint —
"a caller says Grace quoted the wrong price this morning" — one search on the call id must return the
transcript, every tool call with its arguments and latency, the booking state history, and the outbound
messages. If that is not true, the observability is not done.

---

## 2. Logging

```ts
// TARGET — packages/observability/src/logger.ts
export const logger = pino({
  level: env.GRACE_LOG_LEVEL,
  redact: { paths: LOG_REDACT_PATHS, censor: '[REDACTED]' },   // §11 §7.3
  formatters: { level: (label) => ({ level: label }) },
  timestamp: pino.stdTimeFunctions.isoTime,
  base: { service: env.SERVICE_NAME, version: env.GIT_SHA, env: env.NODE_ENV },
});
```

Every log line carries, via `AsyncLocalStorage`: `requestId`, `tenantId`, `vapiCallId`, `toolName`,
`traceId`. No exceptions — a log line without a correlation id is noise.

**Levels:**

| Level | Use | Example |
|---|---|---|
| `error` | Someone must look at this | adapter circuit opened, outbox DEAD, exclusion conflict on PMS sync |
| `warn` | Degraded but handled | deadline exceeded, retry attempted, unapproved policy hit |
| `info` | Business events | call started/ended, booking created, tool invoked, state transition |
| `debug` | Diagnostics | redacted request/response bodies, query plans |
| `trace` | Off in prod | — |

**Never logged at any level:** transcripts, summaries, message bodies, full phone numbers, secrets,
health text, card data (§11 §7.3).

---

## 3. Metrics

Naming: `grace_<subsystem>_<metric>_<unit>`. Labels always include `tenant`; never include unbounded
cardinality (no phone numbers, no call ids, no customer ids).

### 3.1 Business metrics — the ones that matter to the client

```
grace_calls_total{tenant,outcome}                       counter
grace_call_duration_seconds{tenant}                     histogram
grace_containment_ratio{tenant}                         gauge   ← resolved without a human
grace_bookings_total{tenant,strategy,result}            counter
grace_booking_conversion_ratio{tenant}                  gauge   ← bookings / booking-intent calls
grace_transfers_total{tenant,reason}                    counter
grace_deposits_total{tenant,state}                      counter
grace_deposit_conversion_ratio{tenant}                  gauge
grace_medical_holds_total{tenant}                       counter
grace_messages_total{tenant,template,status}            counter
grace_after_hours_calls_total{tenant}                   counter  ← the Phase 1 value story
grace_cost_cents_total{tenant,component}                counter
```

### 3.2 Technical metrics

```
grace_tool_duration_seconds{tenant,tool,status}         histogram  buckets .05 .1 .2 .3 .5 .8 1.2 2 5
grace_tool_deadline_total{tenant,tool}                  counter
grace_tool_errors_total{tenant,tool,code}               counter
grace_db_query_duration_seconds{query}                  histogram
grace_db_pool_in_use / _waiting                         gauge
grace_occupancy_conflicts_total{tenant,context}         counter    ← 23P01 occurrences
grace_adapter_duration_seconds{adapter,operation,outcome} histogram
grace_adapter_circuit_state{adapter}                    gauge      0 closed 1 half 2 open
grace_outbox_pending / _lag_seconds / _dead_total       gauge/counter
grace_queue_depth{queue} / _job_duration_seconds{queue} gauge/histogram
grace_mirror_lag_seconds{tenant,source}                 gauge
grace_mirror_drift_records{tenant}                      gauge      ← from nightly reconciliation
grace_trackb_attempts_total{tenant,result}              counter
grace_holds_active{tenant}                              gauge
grace_redaction_hits_total{tenant,class}                counter    ← §11 §4.1
grace_card_number_detected_total{tenant}                counter    ← must stay at 0
```

---

## 4. Tracing

One trace per inbound request. Spans:

```
POST /vapi/tools                                    [root]
├── hmac.verify
├── tenant.resolve                                  (cache hit/miss attribute)
├── idempotency.check
└── tool.checkAvailability
    ├── db.services.findApprovedByCode
    ├── db.occupancy.findFreeSlots                  (attr: candidate_count, window_days)
    ├── domain.rankSlots                            (attr: ranked_count)
    ├── db.occupancy.placeHolds                     (attr: held_count, conflicts)
    └── format.slots
```

Cold-path traces link to the hot-path trace via a trace context stored on the outbox row — so
"the caller was told the deposit link was sent" and "the SMS actually went out 4 seconds later" are one
connected story.

Sample at 100%. At this volume the cost is negligible and the debugging value during a pilot is high.
Revisit at 10× volume.

---

## 5. Dashboards

Four dashboards, in `infra/grafana/`, provisioned as code.

### 5.1 "Is Grace healthy right now?" (the on-call view)

Single screen, red/green: tool p95 by tool · tool error rate · deadline rate · Core API availability ·
DB pool saturation · outbox pending + lag · queue depth · adapter circuit states · active calls ·
kill-switch state.

### 5.2 "How is the phone line performing?" (the daily view)

Calls by hour of day vs. business hours · containment ratio (7-day trend) · booking conversion ·
transfer reasons breakdown · average handle time · after-hours calls captured · top unanswered questions
(from `structuredData.unansweredQuestions`).

> That last panel is the highest-value feedback loop in the product. It tells you exactly which knowledge
> entry to write next to raise containment. Design brief §13 budgets containment growth from ~60% to
> ~85% over two months — this panel is how that happens.

### 5.3 "Is the booking write path keeping its promises?"

Bookings by state (stacked, over time) · time in each state · Track B success rate and attempt
distribution · `NEEDS_STAFF` count and age · deposit funnel (link sent → paid → expired) ·
mirror drift · reconciliation check results.

### 5.4 "What is this costing?"

Per-component cost/day (Vapi, Twilio voice, SMS, PMS API calls, infra) · cost per call · cost per booking
· projection against the design brief §16 estimate of $700–950/month. Validate the estimate against
reality in week two and tell the client either way.

---

## 6. Alerting

Alerts are **actionable or they are deleted.** Each has an owner, a runbook link, and a severity.

| Severity | Meaning | Route |
|---|---|---|
| **P1** | Callers are affected right now | PagerDuty/SMS on-call, immediately, 24/7 |
| **P2** | Degraded; will affect callers if unattended | Slack `#palmleaf-alerts`, business hours |
| **P3** | Needs attention this week | Daily digest |

| Alert | Condition | Sev | Runbook |
|---|---|---|---|
| Core API down | `/healthz` failing 2 consecutive probes | P1 | §16 §2 |
| Tool error rate | >2% over 5 min | P1 | §16 §3 |
| Tool p95 latency | >1.5s over 10 min | P1 | §16 §4 |
| Deadline rate | >5% of calls over 10 min | P1 | §16 §4 |
| Vapi webhook auth failures | >10 in 5 min | P1 | §16 §5 (possible attack or rotated secret) |
| Outbox DEAD | any row | P1 | §16 §6 |
| Outbox lag | >60s for 5 min | P2 | §16 §6 |
| Booking stuck | any booking in `WRITING_TO_PMS` >2h | P2 | §16 §7 |
| `NEEDS_STAFF` unresolved | any >4h during business hours | P2 | §16 §7 |
| PMS/Grace collision | any occupancy conflict on mirror sync | **P1** | §16 §8 |
| Adapter circuit open | any adapter, >2 min | P2 | §16 §9 |
| Mirror lag | >15 min | P2 | §16 §10 |
| Mirror drift | >5 records in nightly report | P2 | §16 §10 |
| Track B failure rate | >10% over 24h | P2 | §16 §11 |
| Track B canary failed | nightly canary red | **P1** | §16 §11 (Vagaro UI changed) |
| Medical hold flagged | any | P2 (notify staff, not on-call) | §16 §12 |
| Card number detected | any | **P1** | §16 §13 |
| SMS delivery failures | >10% over 1h | P2 | §16 §14 |
| 10DLC campaign not verified | daily check | P2 | §10 §4.1 |
| Deposit unpaid backlog | >5 outstanding | P3 | digest |
| Google watch channel renewal failed | any | P2 | §16 §10 |
| Unapproved policy/service hit | >3 in a day | P3 | chase client sign-off |
| Cost anomaly | daily spend >150% of 7-day average | P2 | §16 §15 |
| Containment drop | 7-day containment down >10 points | P3 | QA review |

**Alert hygiene:** any alert that fires more than twice without producing an action is either re-tuned or
deleted within one week. An ignored alert is worse than no alert.

---

## 7. SLOs and error budgets

| SLO | Target | Window | Budget |
|---|---|---|---|
| Core API availability | 99.9% | 30 days | ~43 min |
| Tool latency: p95 < 400ms (read) | 99% of 5-min windows | 30 days | ~7h of windows |
| Call answer success (call reaches Grace and gets a first response) | 99.5% | 30 days | — |
| Booking durability (confirmed bookings that reach a real calendar) | 100% | always | **zero** |
| Double bookings caused by Grace | 0 | always | **zero** |

The last two have no error budget. If either is breached, all feature work stops until the cause is
found and a regression test exists. Say this to the client explicitly — it is a meaningful commitment
and it is one this architecture can actually keep.

**Budget policy:** if the availability or latency budget is >50% consumed at the halfway point of a
window, the next sprint prioritises reliability over features.

---

## 8. The weekly QA ritual (design brief §13)

Automated in WF-16, executed by a human. This is the loop that raises containment.

1. Sample 20 calls (stratified: 10 random, 5 transfers, 5 longest).
2. Score each: correct policy stated · correct price quoted · correct booking written · appropriate
   escalation · tone · any statement not sourced from a tool (**the critical one**).
3. Every "not sourced from a tool" finding becomes either a knowledge entry, a tool change, or a prompt
   change — with a voice-suite test.
4. Every unanswered question becomes a knowledge entry or a documented "transfer, by design".
5. Publish a one-page weekly summary to the client. This is also the commercial artifact that
   demonstrates the service is being actively managed.

Budget the time explicitly: ~2 hours/week for the first eight weeks, then ~1 hour.

---

## 9. Acceptance criteria

✅ **AC-12.1** A single search on a `vapiCallId` returns logs, spans, tool invocations, booking events and
messages for that call.
✅ **AC-12.2** Every tool emits a duration histogram with a status label.
✅ **AC-12.3** No log line in a captured full-call sample contains a transcript, full phone number, or secret.
✅ **AC-12.4** All four dashboards are provisioned from `infra/grafana/` on a clean Grafana.
✅ **AC-12.5** Every alert in §6 has a runbook link that resolves to a real section in §16.
✅ **AC-12.6** Killing the Core API triggers the P1 within 2 minutes end to end (tested).
✅ **AC-12.7** `grace_card_number_detected_total` and the double-booking counter are both wired to alerts
and verified with a synthetic event.
✅ **AC-12.8** Cost dashboard reconciles to within 10% of the actual Vapi + Twilio invoices for a test week.
