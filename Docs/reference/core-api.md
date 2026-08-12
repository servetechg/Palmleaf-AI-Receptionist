# core-api — Core API Service

**Status:** Frozen — unblocks at [08-roadmap](../plans/08-roadmap.md) task **C-05**, which additionally requires assumption **A-13** (the Vapi HMAC payload format) to be answered first.
**Read before:** implementing any endpoint.
**Implements:** ADR-0002, ADR-0012, ADR-0017
**Enforces:** I1, I3, I10
**Last verified:** 2026-08-04 — rewritten for FastAPI (ADR-0017). §3 and §6 are rewritten rather than renamed, because the middleware/`Depends` split is a genuinely different shape.

> **In one paragraph:** this document settles the request lifecycle for the hot path — the exact
> order in which a tool call is authenticated, resolved to a tenant, deadline-bounded, checked for
> idempotency and dispatched — plus the route table, the error taxonomy, and the natural-language
> formatting of results. It deliberately does **not** contain business logic; handlers are thin
> and the rules live in `grace_domain`.

---

## 1. Responsibility

`apps/core-api` is the only process a caller ever waits on. Its job is narrow and it should stay narrow:

**It does:** verify the caller is Vapi, resolve the tenant, enforce idempotency and deadlines, validate
input, call pure domain logic against local data, write the transaction (including outbox rows), and
format a natural-language sentence.

**It does not:** talk to Vagaro, Stripe, Twilio, Google or n8n; run Playwright; process
transcripts; send SMS; retry anything. All of that is the cold path ([booking-write-path](booking-write-path.md)).

---

## 2. Process topology

```
                     ┌──────────────────────────────┐
   Vapi ────HTTPS───►│  core-api (2+ instances)     │
   Stripe ──────────►│  FastAPI · uvicorn · Py 3.12 │
   Twilio ──────────►│  stateless · behind LB       │
   Vagaro ──────────►│  graceful shutdown 25s       │
   n8n (internal) ──►└───────┬──────────────┬───────┘
                             │              │
                       Postgres pool     Redis
                       (max 10/inst)   (cache+queue)
```

Stateless by construction: no in-memory session, no sticky routing. Two instances behind a load balancer
from day one — not for capacity, but so a deploy never drops a call.

---

## 3. Composition root

```python
#: TARGET — src/grace_api/app.py
@dataclass(frozen=True)
class Deps:
    db: Database
    redis: Redis
    clock: Clock          #: injectable — a handler never reads the clock directly
    config: Settings
    metrics: MetricsRegistry


def build_app(deps: Deps) -> FastAPI:
    app = FastAPI(default_response_class=ORJSONResponse)
    app.state.deps = deps

    #: MIDDLEWARE — outermost runs first. Only these two may precede body parsing.
    app.add_middleware(ObservabilityMiddleware, deps=deps)
    app.add_middleware(RequestContextMiddleware)   #: contextvars: request id, tenant, deadline
    app.add_middleware(RawBodyMiddleware)          #: capture raw bytes BEFORE anything parses them

    #: ROUTERS — health first and unauthenticated, so probes never depend on auth.
    app.include_router(health_router)
    app.include_router(
        vapi_tool_router,
        prefix="/vapi",
        dependencies=[
            Depends(verify_vapi_hmac),   #: 1. needs the raw body from the middleware above
            Depends(resolve_tenant),     #: 2. pins tenant into contextvars, sets the RLS GUC
            Depends(open_deadline),      #: 3. starts the clock before any handler work
            Depends(check_idempotency),  #: 4. replays a stored response if this is a retry
        ],
    )
    app.include_router(webhook_router, prefix="/webhooks")
    app.include_router(internal_router, prefix="/internal")
    app.add_exception_handler(GraceError, error_handler(deps))
    return app
```

**The ordering is the specification, and FastAPI expresses it in two different mechanisms.** Raw-body
capture and request context must be **middleware**, because they have to run before FastAPI parses
the body at all. Everything after is a **dependency**, because it is per-route and may raise a typed
error. Getting this wrong does not crash — it silently verifies a signature against a re-serialised
body, or starts the deadline after the work it was meant to bound. That is why ADR-0017 treats the
framework swap as a rewrite of this section rather than a rename.

`build_app` never calls `uvicorn.run`. `server.py` does that, which is what makes the whole app
testable in-process with `httpx.ASGITransport` and no network.

**Clock injection.** `deps.clock.now()` everywhere. Handlers pass `now` down into domain functions
(ADR-0011). Tests supply a frozen clock; the 48-hour boundary tests are then exact and non-flaky.

---

## 4. Route surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/vapi/tools` | HMAC | **The single tool endpoint.** Every function tool dispatches from here. Set as each *tool's* `server.url` — see [03-vapi-layer](../plans/03-vapi-layer.md) §3.2. |
| `POST` | `/webhooks/vapi/events` | HMAC | `end-of-call-report`, `status-update`, `hang`, `transfer-destination-request`. Set as the *assistant's* `server.url`. |
| `POST` | `/webhooks/vagaro` | shared token + IP allowlist | PMS change notifications — **ACK immediately** |
| `POST` | `/webhooks/stripe` | Stripe signature | payment_intent / checkout.session events |
| `POST` | `/webhooks/twilio/status` | Twilio signature | delivery receipts |
| `POST` | `/webhooks/twilio/inbound` | Twilio signature | STOP / HELP / replies |
| `GET` | `/healthz` | none | liveness — process is up |
| `GET` | `/readyz` | none | readiness — DB + Redis reachable, migrations current |
| `GET` | `/metrics` | network-restricted | Prometheus |

### 4.0 The `/internal/*` surface

Every `/internal/*` route is bearer-authenticated with `GRACE_INTERNAL_API_TOKEN` and is **not**
tenant-resolved at the edge — the tenant is named explicitly by the caller. All of them are cold-path:
none has a latency budget.

| Method | Path | Consumer | Purpose |
|---|---|---|---|
| `POST` | `/internal/tasks` | workers | Create a staff task (was `/internal/tasks/:type`; type moves into the body — see below) |
| `GET` | `/internal/tasks/:id` | n8n WF-12 | Poll acknowledgement state for the 15-minute escalation |
| `POST` | `/internal/tasks/:id/ack` | n8n WF-14 | Sets `status='ACKNOWLEDGED'` **and `acknowledged_at`** ([data-model](data-model.md)) |
| `POST` | `/internal/tasks/:id/resolve` | any staff surface | Marks a task resolved. WF-14 is withdrawn; this endpoint outlived it |
| `GET` | `/internal/reports/reconciliation` | n8n WF-07 | Nightly drift report |
| `GET` | `/internal/reports/calls?window=1h` | n8n WF-11 | Hourly call digest |
| `GET` | `/internal/reports/daily` | n8n WF-15 | Yesterday's calls, bookings, containment, open tasks, deposits |
| `GET` | `/internal/reports/qa-sample?n=20` | n8n WF-16 | Weekly QA sampler |
| `POST` | `/internal/digest/append` | n8n WF-12 (P3 branch) | Appends to the daily digest — replaces the undefined "digest store" |
| `POST` | `/internal/notify/sms` | n8n WF-12, WF-18 | Staff SMS **through the messaging adapter**, so 10DLC/opt-out cannot be bypassed ([04-n8n-layer](../plans/04-n8n-layer.md) §3.4) |
| `GET` | `/internal/tenants/:slug/settings` | n8n (all) | Escalation channel, manager mobile — unblocks multi-tenant workflows ([04-n8n-layer](../plans/04-n8n-layer.md) §11) |
| `POST` | `/internal/tenants/:slug/kill-switch` | runbook, WF-14 | [runbooks](runbooks.md) §28 |
| `POST` | `/internal/sync/reconcile` | runbook | [runbooks](runbooks.md) |

> ⛔ **Route collision, corrected 2026-08-03.** The old table declared `POST /internal/tasks/:type`
> while [04-n8n-layer](../plans/04-n8n-layer.md) used `GET /internal/tasks/:id` and `POST /internal/tasks/:id/resolve`. `:type` and `:id`
> occupy the same path segment, so `/internal/tasks/MESSAGE` and `/internal/tasks/<uuid>` are
> indistinguishable to the router. Task type moves into the request body.

⚠️ [02-python-and-repo](../plans/02-python-and-repo.md) §50 describes this directory as "mTLS/token-gated". **mTLS appears nowhere else in the plan set**
and is not implemented — it is bearer only. Either delete the mention or write the ADR.

⚠️ [05-security-and-compliance](../plans/05-security-and-compliance.md) says the token is "distinct per environment" and workers get "a separate token", but [02-python-and-repo](../plans/02-python-and-repo.md)
defines exactly one `GRACE_INTERNAL_API_TOKEN` shared by core-api, n8n and workers. Split into
`GRACE_INTERNAL_API_TOKEN_N8N` and `_WORKER` if the separation is meant; otherwise correct [05-security-and-compliance](../plans/05-security-and-compliance.md).

⚠️ The composition root in §3 registers `internalRoutes` **outside** the scoped block containing the auth
plugins, and no `internalAuthPlugin` is registered anywhere. As written these routes are unauthenticated.

### 4.1 Why one tool endpoint and not thirteen

Vapi sends `{ message: { toolCalls: [...] } }` and may send **more than one tool call in a single
request**. One endpoint with an internal dispatcher handles batches correctly, guarantees a
`toolCallId`-matched response for every call in the batch, and keeps the middleware chain in one place.
Thirteen routes would each need the same six middlewares and would silently break on batching.

---

## 5. Request lifecycle for a tool call

```
POST /vapi/tools
 │
 1. rawBody captured                                                  ~0ms
 2. HMAC verify x-vapi-signature (timing-safe, replay window 5 min)   ~1ms
 3. Parse envelope (Pydantic) → toolCalls[]                                ~0ms
 4. Resolve tenant from assistantId/phoneNumberId (Redis cache, 60s)  ~0-2ms
 5. Open AsyncLocalStorage context: requestId, tenantId, vapiCallId,
    deadline = now + min(header, GRACE_TOOL_DEADLINE_MS)
 6. FOR EACH toolCall (in parallel, bounded to 4):
      a. look up handler; unknown name → structured "unavailable" result
      b. idempotency: write-tools take key = `${vapiCallId}:${toolCallId}`
      c. validate arguments (extra="forbid")
      d. Promise.race([handler(ctx, args), deadlineTimer])
      e. handler runs inside withTenant() transaction
      f. domain computes; repository persists; outbox rows written
      g. formatter turns the domain result into a spoken sentence
 7. Assemble { results: [{ toolCallId, result }] }
 8. Record tool_invocations rows (fire-and-forget, after response flush)
 9. Respond 200
```

### 5.1 The response contract

Vapi requires the `toolCallId` to match. A missing or mismatched id makes the assistant go silent —
the single most common failure in this integration.

```jsonc
// TARGET — always this shape, even on error
{
  "results": [
    { "toolCallId": "call_a1b2c3", "result": "I have three openings Tuesday evening: five fifteen with Maria, six thirty with James, or seven with Maria. Which works?" }
  ]
}
```

**Rules:**
1. `result` is a **spoken English sentence**, never JSON. The LLM reads it aloud or paraphrases it.
   Returning JSON produces stilted phrasing and burns tokens.
2. Numbers are spoken form: `"five fifteen"` not `"17:15"`, `"one thirty-five"` not `"$135.00"`.
3. Never more than three options in one sentence (design brief §4.3).
4. Errors return a *sentence*, HTTP 200. A 500 gives the LLM nothing to say.
5. Machine data the assistant needs later goes in a second field the formatter also emits into the
   sentence — the LLM has no structured memory, so if it must remember `slotId`, the sentence must
   include a token it can echo back (we use short human-safe ids: `"hold-7K2"`).

### 5.2 Formatters are separate, tested units

```ts
// TARGET — src/grace_api/formatters/availability.py
export function formatSlots(slots: Slot[], tz: string, now: Date): string {
  if (slots.length === 0) return 'I don\'t have anything open then. Would another day work?';
  const parts = slots.slice(0, 3).map(s =>
    `${speakTime(s.startsAt, tz)} with ${s.providerName}`);
  const when = speakRelativeDay(slots[0]!.startsAt, tz, now);   // "Tuesday", "tomorrow"
  return `I have ${listWithOr(parts)} ${when}. Which works better?`;
}
```

Formatters are pure and unit-tested against a table of expected sentences. This is where "Grace sounds
natural" actually lives — it is worth real test coverage. Snapshot tests catch accidental phrasing
regressions on prompt-adjacent text.

---

## 6. Middleware specifications

### 6.1 HMAC verification

```ts
// TARGET — src/grace_api/plugins/hmac_vapi.py
const signature = req.headers['x-vapi-signature'];
const timestamp = req.headers['x-vapi-timestamp'];
if (!signature || !timestamp) throw new UnauthorizedError('missing_signature');
if (Math.abs(clock.now() - Number(timestamp) * 1000) > 5 * 60_000)
  throw new UnauthorizedError('stale_signature');       // replay defence
const expected = createHmac('sha256', config.vapiWebhookSecret)
  .update(`${timestamp}.${req.rawBody}`).digest('hex');
if (!timingSafeEqual(Buffer.from(expected), Buffer.from(signature)))
  throw new UnauthorizedError('bad_signature');
```

**Why this code is now correct by construction, not by assumption.** ✅ Verified 2026-08-03 against
`api.vapi.ai/api-json`: the `Server` schema has **no `secret` field** — it is
`{ url, headers, credentialId, timeoutSeconds, backoffPlan, staticIpAddressesEnabled, encryptedPaths }`.
Webhook auth is a dashboard-created **Custom Credential** referenced by `credentialId`. Its HMAC type lets
us *choose* the algorithm, signature header, and timestamp header — so we configure exactly
`SHA256` / `x-vapi-signature` / `x-vapi-timestamp` and the verifier above matches by definition. See
[03-vapi-layer](../plans/03-vapi-layer.md) §3.3 and the credential-creation steps in [06-platform-setup](../plans/06-platform-setup.md) §1.2. **A-02 is largely discharged.**

⚠️ One residual unknown: the credential's **Payload Format** option set is undocumented, so it is not yet
confirmed that one produces exactly `{timestamp}.{rawBody}`. Record the chosen format when creating the
credential and match this verifier to whatever it actually emits. Logged as **A-13** in [09-open-decisions](../plans/09-open-decisions.md).

⚠️ `config.vapiWebhookSecret` is the secret entered into the *credential*, not a field on the assistant.
Do not add `secret` to `grace.json` — it is silently ignored.

### 6.2 Tenant resolution

```ts
// TARGET
const key = envelope.call?.assistantId ?? envelope.call?.phoneNumberId;
const tenant = await tenantCache.get(key);   // Redis, 60s TTL, negative-cached 10s
if (!tenant) throw new UnauthorizedError('unknown_channel');
if (tenant.status !== 'ACTIVE') throw new ServiceUnavailableError('tenant_paused');
ctx.tenantId = tenant.id;
```

Never hardcode PalmLeaf's id. Never accept a tenant id from the request body.

### 6.3 Idempotency

Applies to `createBooking`, `rescheduleAppointment`, `cancelAppointment`, `takeMessage`,
`flagMedicalHold`, and all three `send*` tools.

```
key = `${vapiCallId}:${toolCallId}`
INSERT INTO idempotency_keys (..., status='IN_FLIGHT') ON CONFLICT DO NOTHING
  ├─ inserted    → run handler → UPDATE status='COMPLETED', response=<result>
  ├─ conflict, existing COMPLETED  → return the stored response verbatim
  └─ conflict, existing IN_FLIGHT  → wait up to 800ms polling; then return
                                     "I'm just finishing that up — one moment."
```

The `request_hash` column detects a key reused with different arguments — that is a bug in the caller
and must log at `error` and return a domain error rather than silently returning the old response.

### 6.4 Deadline (ADR-0012)

> ⛔ **Corrected 2026-08-03.** This raced the handler against `TOOL_BUDGETS[toolName]` — the per-tool
> numbers from [03-vapi-layer](../plans/03-vapi-layer.md) §4. Those are **p95 latency targets**, so by definition ~5% of calls exceed them:
> racing against them fires the graceful-fallback sentence on **one call in twenty, by construction**,
> on a perfectly healthy system. Budgets drive *alerting*; the deadline drives *degradation*. They are
> different numbers with different jobs.

```ts
// TARGET
// The DEADLINE is a single wall-clock ceiling, propagated from the request context.
// It is NOT the per-tool p95 target.
const deadlineMs = ctx.remainingMs();                   // GRACE_TOOL_DEADLINE_MS (2500) minus elapsed
const budget     = TOOL_BUDGETS[toolName] ?? 1500;      // p95 TARGET, from [03-vapi-layer](../plans/03-vapi-layer.md) §4 — for metrics only

const started = clock.now();
const result  = await Promise.race([
  handler(ctx, args),
  sleep(deadlineMs).then(() => DEADLINE_SENTINEL),
]);
const elapsed = clock.now() - started;

// Exceeding the p95 target is a SIGNAL, not a failure. The caller still gets the real answer.
if (elapsed > budget) {
  metrics.toolBudgetExceeded.inc({ tool: toolName });
  logger.warn({ tool: toolName, budget, elapsed }, 'tool exceeded p95 target');
}

// Exceeding the deadline is a failure. Only here do we degrade.
if (result === DEADLINE_SENTINEL) {
  metrics.toolDeadline.inc({ tool: toolName });
  logger.error({ tool: toolName, deadlineMs }, 'tool deadline exceeded');
  return gracefulFallback(toolName);   // a sentence, always
}
```

Two metrics, two alert thresholds: `grace_tool_budget_exceeded_total` tracks whether we are meeting the
[01-architecture](../plans/01-architecture.md) §5 quality targets, and `grace_tool_deadline_total` tracks callers who actually heard a degraded
answer. The second should be near zero; the first is expected to sit around 5% and is a tuning signal.

`gracefulFallback` per tool, from a table — e.g. `checkAvailability` → *"Let me check on that — can you
hold for just a second while I pull up the schedule?"* followed by an async retry is **not** implemented;
the honest fallback is *"I'm having trouble reaching the schedule. Let me get someone who can help."*
plus a transfer hint. Never invent availability.

**Important:** losing the race does not cancel the underlying work. If the handler's transaction later
commits a hold, a stale hold exists. Handlers therefore check `ctx.deadlineExceeded` before their final
commit and roll back if it is set. This is specified per-handler in [availability-engine](availability-engine.md) §7.

### 6.5 Concurrency and back-pressure

- Postgres pool: `max = 10` per instance. At 25 concurrent calls × ~1 query each this is ample; a larger
  pool makes contention worse, not better.
- Keep-alive on, with no per-socket request cap — Vapi reuses connections. *(The equivalent knob in the replaced framework was `maxRequestsPerSocket`.)*
- A semaphore caps in-flight tool handlers at 32 per instance. Beyond that, return the graceful fallback
  immediately rather than queueing — a queued voice request is a dead-air request.

---

## 7. Error taxonomy

```ts
// TARGET — src/grace_contracts/errors.py
export abstract class GraceError extends Error {
  abstract readonly code: string;
  abstract readonly httpStatus: number;
  abstract readonly retryable: boolean;
  /** Sentence Grace can say. null ⇒ use the generic fallback. */
  abstract readonly spoken: string | null;
  constructor(message: string, readonly context: Record<string, unknown> = {}) { super(message); }
}
```

| Class | code | HTTP | Spoken to caller | Alert? |
|---|---|---|---|---|
| `ValidationError` | `invalid_arguments` | 200 | "Sorry, could you say that once more?" | on rate spike |
| `UnauthorizedError` | `unauthorized` | 401 | — (never reaches a caller) | ✅ immediate |
| `TenantNotFoundError` | `unknown_channel` | 401 | — | ✅ immediate |
| `SlotNoLongerAvailableError` | `slot_taken` | 200 | "That one just went. I also have …" | no |
| `NoAvailabilityError` | `no_availability` | 200 | "I don't have anything then. Another day?" | no |
| `ServiceNotApprovedError` | `service_unapproved` | 200 | "Let me get someone who can confirm that." | ✅ daily digest |
| `PolicyNotApprovedError` | `policy_unapproved` | 200 | same | ✅ daily digest |
| `MedicalHoldError` | `medical_hold` | 200 | "I'd like a team member to go over that with you." | ✅ per event |
| `CustomerNotFoundError` | `customer_unknown` | 200 | "I don't see you in our system — can I get your name?" | no |
| `DeadlineExceededError` | `deadline` | 200 | per-tool fallback | ✅ p95 breach |
| `KillSwitchError` | `kill_switch` | 503 | — (calls are already re-routed) | ✅ immediate |
| `InternalError` | `internal` | 200 | "I'm having trouble with that — let me get someone." | ✅ immediate |

**Rule:** any error surfacing to a *caller* returns HTTP 200 with a spoken `result`. HTTP error codes are
reserved for callers that are *machines we control* (webhooks, internal). This is the difference between
a graceful conversation and dead air.

---

## 8. Handler anatomy (the template every tool follows)

```ts
// TARGET — src/grace_api/routes/vapi/handlers/check_availability.py
import { CheckAvailabilityInput } from 'grace_contracts/tools';
import { rankSlots, applyBuffers } from 'grace_domain/availability';
import { occupancyRepo, serviceRepo, providerRepo } from 'grace_db/repositories';
import { formatSlots } from '../../../formatters/availability.js';

export const checkAvailability: ToolHandler<'checkAvailability'> = async (ctx, args) => {
  const service = await serviceRepo.findApprovedByCode(ctx.tx, args.serviceCode);
  if (!service) throw new ServiceNotApprovedError('unknown or unapproved service', { code: args.serviceCode });

  const window = resolveWindow(args.preferredDate, args.timePreference, ctx.tenant.timezone, ctx.now);
  if (window.startsAt < addMinutes(ctx.now, service.minLeadTimeMin))
    return { spoken: 'The soonest I can book is a couple of hours out. Would later today work?' };

  // ONE query: candidate slots anti-joined against active occupancy. See [availability-engine](availability-engine.md) §3.
  const candidates = await occupancyRepo.findFreeSlots(ctx.tx, {
    serviceId: service.id, window, providerId: args.providerPreference
      ? await providerRepo.resolveByName(ctx.tx, args.providerPreference) : null,
  });

  const ranked = rankSlots(candidates, {           // PURE
    preference: args.timePreference,
    preferredProviderId: ctx.customer?.preferredProviderId ?? null,
    now: ctx.now,
    max: ctx.tenant.settings.maxSlotsOffered,
  });
  if (ranked.length === 0) throw new NoAvailabilityError('no slots', { window });

  if (ctx.deadlineExceeded) return { spoken: gracefulFallback('checkAvailability') }; // §6.4

  const held = await occupancyRepo.placeHolds(ctx.tx, {   // may raise SlotNoLongerAvailable
    slots: ranked, callId: ctx.callId, ttlSeconds: ctx.tenant.settings.holdTtlSeconds,
  });

  return { spoken: formatSlots(held, ctx.tenant.timezone, ctx.now), data: { slotIds: held.map(h => h.publicId) } };
};
```

Every handler:
1. loads **approved** reference data (never unapproved),
2. computes with a **pure** domain function,
3. persists inside `ctx.tx`,
4. writes outbox rows for anything external,
5. returns `{ spoken, data? }` — the router turns that into the Vapi response.

---

## 9. Webhook handlers

### 9.1 Vagaro receiver — the 20-second rule

Vagaro retries up to 5 times over 15 minutes if it does not get a 2xx within 20 seconds
(design brief §5.1). Therefore:

```ts
// TARGET — src/grace_api/routes/webhooks/vagaro.py
app.post('/vagaro', async (req, reply) => {
  verifyVagaroToken(req);                                   // fast
  const raw = req.body as unknown;
  await db.insert(inboundWebhooks).values({                 // single INSERT, nothing else
    tenantId, source: 'vagaro', payload: raw, dedupeKey: hashPayload(raw),
  }).onConflictDoNothing();
  reply.code(200).send({ ok: true });                       // ACK in <50ms
  // processing happens in sync-worker, triggered by the outbox/queue
});
```

**Never** parse deeply, look up records, or call another service before the ACK. An `inbound_webhooks`
staging table (add in migration 0015) gives replay capability and idempotent processing.

### 9.2 Stripe

Verify with `stripe.webhooks.constructEvent` against the raw body. Handle
`checkout.session.completed`, `payment_intent.payment_failed`, `charge.refunded`. Each maps to a
booking state transition ([booking-write-path](booking-write-path.md) §4). Idempotent on Stripe's `event.id`.

### 9.3 Vapi end-of-call-report

Ack fast, enqueue. The worker does transcript redaction ([05-security-and-compliance](../plans/05-security-and-compliance.md) §4), summary storage, QA scoring, call
outcome classification, and the customer `visit_count` update. **Redaction happens before the first
write, not after.**

---

## 10. Health and readiness

```ts
// TARGET
GET /healthz → 200 {"status":"ok"}                     // process alive; no dependency checks
GET /readyz  → 200 | 503 {
  db: 'ok', redis: 'ok', migrations: 'current',
  killSwitch: false, version: '<git sha>'
}
```

`/readyz` returning 503 removes the instance from the load balancer. It must check migrations: an
instance running old code against a migrated database, or vice versa, should not take traffic.

---

## 11. Graceful shutdown

On `SIGTERM`: stop accepting new connections → fail `/readyz` → drain in-flight requests up to 25s →
close the pool → exit. Deploys must therefore keep the old instance alive for at least 30s. A call
in progress must never see a connection reset.

---

## 12. Acceptance criteria

✅ **AC-04.1** `app.inject()` can exercise all 13 tools with a fake clock and no network.
✅ **AC-04.2** A request with a bad HMAC returns 401 and never reaches a handler (proven by spy).
✅ **AC-04.3** A request with a 6-minute-old timestamp is rejected as stale.
✅ **AC-04.4** Two identical `createBooking` calls with the same `toolCallId` produce one booking row and
two identical responses.
✅ **AC-04.5** A handler artificially delayed past its budget returns a spoken fallback in <budget+50ms
and commits nothing.
✅ **AC-04.6** A batch request with three `toolCalls` returns three results with matching ids.
✅ **AC-04.7** Every error class in §7 has a test asserting its HTTP status and spoken string.
✅ **AC-04.8** `/webhooks/vagaro` responds in <100ms p99 under a 50-req burst.
✅ **AC-04.9** SIGTERM during an in-flight request drains without dropping it.
✅ **AC-04.10** No file under `routes/vapi/handlers/**` imports `grace_adapters` (lint, invariant I1).

## 13. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **A-13** | What exactly does Vapi HMAC over — the raw body, or a timestamped canonical string? | **This blocks C-05 outright.** Signature verification fails closed, so until the format is known, every tool call is rejected. Closing it needs one captured signed request. | Engineering, before C-05 |
| **A-24** | Does FastAPI middleware plus `Depends` actually reproduce the ordering §3 requires? | The replaced framework enforced order through plugin encapsulation; FastAPI has no equivalent. Signature verification needs the **raw** body before parsing, and the deadline must start before any handler work. Getting it wrong is a silent correctness failure, not a crash. | Engineering, at C-05 |
| **A-16** | Does a `backoffPlan` retry reuse the same `toolCallId`? | Idempotency is keyed on it. If a retry generates a new id, deduplication silently stops working and a retried `createBooking` could double-book. **Directly threatens I3.** | Engineering, before enabling any retry |
| **Q-CA.1** | Where does the `/internal/*` authorization boundary actually sit? | Today it is one bearer token shared by n8n and the workers, which means any holder can invoke the kill switch (Q-05.1). Per-endpoint authorization is the obvious fix and is not designed. | Engineering, at C-05 |
