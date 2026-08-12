# provider-adapters — Ports & Adapters

**Status:** Frozen — the adapters unblock as GATE-01, GATE-03, GATE-07, GATE-08 and GATE-09 clear. **The fakes and the resilient client (tasks D-01, D-02) are not blocked and can be built now.**
**Read before:** integrating any external system.
**Implements:** ADR-0007
**Enforces:** I1
**Last verified:** 2026-08-04 — ports rewritten as `typing.Protocol` classes; response validation is Pydantic.

> **In one paragraph:** this document settles the boundary between Grace and every system she does
> not own — the port protocols, the retry/circuit-breaker/timeout behaviour every adapter shares,
> the capability flags that let one booking saga serve three different Vagaro futures, and the
> contract tests that keep the fakes honest. It deliberately does **not** decide *which* PMS ships
> first; that is a gate, not a design.

---

## 1. The rule

**All network egress to a third party happens in `packages/adapters` and nowhere else.**

Everything above the adapter layer speaks to a *port* — a `typing.Protocol` class (which replaced the TypeScript interface) in
`src/grace_contracts/ports`. The domain does not know Vagaro exists. The handlers do not know Stripe
exists. This is what makes the Vagaro write-path uncertainty (⛔ GATE-01) survivable: three different
Vagaro futures are three different adapter implementations behind one unchanged interface.

---

## 2. Adapter construction standard

Every adapter, without exception, is built from the same five pieces:

| Piece | Requirement |
|---|---|
| **Typed client** | `httpx` request wrapper. Response parsed with a Pydantic model — never trusted. |
| **Retry** | Exponential backoff + full jitter. Only on 429, 5xx, and network errors. **Never on 4xx.** Max 4 attempts. Respects `Retry-After`. |
| **Circuit breaker** | Opens after 5 consecutive failures or a 50% error rate over 20 requests; half-open probe after 30s. Open circuit → `AdapterUnavailableError` immediately, no hanging. |
| **Timeout** | Per-call, explicit, always set. No adapter call is unbounded. |
| **Instrumentation** | One histogram `grace_adapter_duration_seconds{adapter,operation,outcome}` and one OTel span per call. Request/response bodies logged at `debug` only, always redacted. |

```ts
// TARGET — src/grace_adapters/shared/resilient-client.py
export function createResilientClient(opts: {
  name: string; baseUrl: string; timeoutMs: number;
  retry?: { maxAttempts: number; retryOn: (e: unknown) => boolean };
  breaker?: { failureThreshold: number; resetMs: number };
  auth: () => Promise<Record<string, string>>;   // called per request; handles token refresh
}): ResilientClient;
```

**Rate limiting.** Each adapter declares its budget and self-limits with a token bucket in Redis
(shared across instances). Vagaro's numeric limits are unpublished (⛔ GATE-03) — until confirmed, the
Vagaro adapter is capped at **2 requests/second, 3,000 requests/day** and emits a warning at 80% of the
monthly 5,000-call allowance.

---

## 3. `PmsPort` — the critical abstraction

```ts
// TARGET — src/grace_contracts/ports/pms.py
export interface PmsPort {
  readonly capabilities: PmsCapabilities;

  // ---- READ (always available) ----
  listAppointments(q: { from: Date; to: Date; cursor?: string }): Promise<Page<PmsAppointment>>;
  getAppointment(id: string): Promise<PmsAppointment | null>;
  listCustomers(q: { updatedSince?: Date; cursor?: string }): Promise<Page<PmsCustomer>>;
  findCustomerByPhone(phoneE164: string): Promise<PmsCustomer | null>;
  listEmployees(): Promise<PmsEmployee[]>;
  listLocations(): Promise<PmsLocation[]>;

  // ---- WRITE (capability-gated — may throw NotSupportedByProvider) ----
  createAppointment(req: CreateAppointmentRequest): Promise<PmsAppointment>;
  updateAppointment(id: string, req: UpdateAppointmentRequest): Promise<PmsAppointment>;
  cancelAppointment(id: string, reason: string): Promise<void>;
  createCustomer(req: CreateCustomerRequest): Promise<PmsCustomer>;
  searchAvailability(q: AvailabilityQuery): Promise<PmsSlot[]>;
}

export interface PmsCapabilities {
  readAppointments: boolean;
  readCustomers: boolean;
  writeAppointments: boolean;     // ⛔ GATE-01 — false for Vagaro as of 1 Aug 2026
  updateAppointments: boolean;
  cancelAppointments: boolean;
  writeCustomers: boolean;
  searchAvailability: boolean;
  idempotencyHeader: boolean;
  webhooks: boolean;
}
```

### 3.1 The capability object is the whole point

Code **never** branches on `if (pms instanceof VagaroAdapter)`. It branches on
`if (pms.capabilities.writeAppointments)`. The booking strategy selector ([booking-write-path](booking-write-path.md) §2) reads capabilities and
picks Track A/B/C accordingly.

When Vagaro answers the outreach questions (`Docs/PalmLeaf_Outreach_Package.md` Part 2), the change is:

- **"Write endpoints exist"** → flip `writeAppointments: true`, implement the four methods, delete the
  Track B worker. Estimated diff: one adapter file, one config flag, one deleted app. **No domain change.**
- **"Not available"** → capabilities stay false, Track A+B ship as designed.
- **"Enterprise tier only"** → capabilities become tenant-configurable; both paths coexist.

This is the concrete engineering payoff of ADR-0007 and it is why the adapter layer is built in Phase B,
before the Vagaro answer arrives.

### 3.2 Vagaro adapter specifics

```
src/grace_adapters/vagaro/
├── __init__.py              # VagaroAdapter implements PmsPort
├── auth.py               # OAuth2: POST /merchants/generate-access-token, cached in Redis
├── client.py             # resilient client, region-aware base URL
├── mappers/              # Vagaro DTO ↔ domain model. Bidirectional, tested both ways.
├── schemas.py            # a Pydantic model for every Vagaro response — their docs are incomplete, trust nothing
├── capabilities.py       # the single source of truth for what Vagaro can do
└── unsupported.py        # write methods throw NotSupportedByProvider with a helpful message
```

**Auth.** Token cached in Redis with TTL = `expires_in − 60s`, refreshed by a single-flight lock so 20
concurrent workers cause one refresh, not twenty. Exact token endpoint path, host/region pattern and TTL
are unconfirmed (Outreach Q19) — logged as **A-03** in [09-open-decisions](../plans/09-open-decisions.md); the adapter reads them from config so the
answer is a config change.

**Pagination and rate limits.** Unpublished (Outreach Q20, Q21). The adapter implements cursor *and*
offset pagination behind one `Page<T>` type and detects which the API actually uses at runtime,
logging which path it took.

**Region.** `GRACE_VAGARO_REGION` feeds the base URL template. Do not hardcode `api.vagaro.com`.

**Sandbox.** Vagaro has no confirmed sandbox (Outreach Q22). Therefore:
- Integration tests run against a **recorded-cassette** fake (`packages/testing/src/fakes/vagaro`).
- Any test that would write to Vagaro is gated behind `GRACE_ALLOW_LIVE_PMS_WRITES=true`, which is
  never set in CI and never set in dev.
- A live smoke test exists but is manual, documented in [runbooks](runbooks.md), and uses a designated test customer and a
  designated far-future slot that is cleaned up afterwards.

---

## 4. `CalendarPort` — Track A

```ts
// TARGET
export interface CalendarPort {
  createEvent(req: {
    calendarId: string; summary: string; description: string;
    startsAt: Date; endsAt: Date; timezone: string;
    idempotencyKey: string;                 // → Google's `requestId` / our own event id
    metadata: Record<string, string>;       // extendedProperties.private
  }): Promise<{ eventId: string; htmlLink: string }>;
  updateEvent(calendarId: string, eventId: string, patch: Partial<EventPatch>): Promise<void>;
  deleteEvent(calendarId: string, eventId: string): Promise<void>;
  listEvents(calendarId: string, from: Date, to: Date, syncToken?: string): Promise<Page<CalendarEvent>>;
  watch(calendarId: string, webhookUrl: string): Promise<{ channelId: string; expiration: Date }>;
}
```

Google Calendar adapter notes:

- **Auth:** service account with domain-wide delegation, or per-provider OAuth. Prefer a service account
  with each provider's calendar shared to it — simpler, no refresh-token rot. ⛔ requires PalmLeaf action.
- **Idempotency:** set the event `id` deterministically to a base32 of the booking id. Re-creating the
  same event returns 409, which the adapter treats as success. This makes Track A retry-safe for free.
- **Event body:** `extendedProperties.private` carries `graceBookingId`, `graceOccupancyId`,
  `graceServiceCode`. The reconciler uses these to match Google events back to bookings without
  parsing the summary text.
- **Watch channels** expire (max ~7 days for calendars). A cron renews them at 80% of TTL and alerts if
  renewal fails — a silently dead watch channel means staff-side manual blocks stop syncing.

⛔ **GATE-07 — Track A viability.** The design brief §18 item 4 correctly identifies this as *the*
30-minute test that decides the booking architecture. It must produce a written answer to:
1. Does a Google Calendar event created by us appear on the Vagaro calendar?
2. How long does it take?
3. Does it *block* the slot from being booked by a customer on Vagaro's own widget, or is it only visual?
4. Does it survive a Vagaro-side edit?

Answer 3 is the one that matters. If a synced event is cosmetic and does not block booking, **Track A
does not hold the slot** and the entire composite in the design brief §1.4 must be re-planned. Do not
build Track A logic until this test is done. It requires no code.

---

## 5. `PaymentsPort` — Stripe

```ts
// TARGET
export interface PaymentsPort {
  createDepositLink(req: {
    amountCents: number; currency: 'usd'; bookingId: string; customerRef: string;
    description: string; expiresAt: Date; idempotencyKey: string;
  }): Promise<{ url: string; sessionId: string }>;
  getPaymentStatus(sessionId: string): Promise<PaymentStatus>;
  refund(paymentIntentId: string, amountCents: number, reason: string): Promise<void>;
  verifyWebhook(rawBody: Buffer, signature: string): StripeEvent;
}
```

- **PCI boundary (I5).** We create hosted links. We never touch a PAN, never render a card form, never
  proxy card data. Grace does not read the link aloud — it is sent by SMS.
- `idempotencyKey` maps directly to Stripe's `Idempotency-Key` header. Use the outbox event id.
- Deposit amount comes from `services.deposit_cents` / `deposit_percent_bp` computed by
  `grace_domain/policy` — never from the LLM, never from the request.
- ⛔ **GATE-08:** the design brief §10 flags that PalmLeaf will be running Vagaro CC processing *and*
  Stripe deposits in parallel, and that their bookkeeper must confirm reconciliation. If the answer is
  "keep everything in Vagaro", the deposit link becomes a Vagaro-hosted checkout and `PaymentsPort` gains
  a second adapter. The port does not change.

---

## 6. `MessagingPort` — Twilio

```ts
// TARGET
export interface MessagingPort {
  sendSms(req: {
    to: string; body: string; messagingServiceSid: string;
    idempotencyKey: string; statusCallbackUrl?: string;
  }): Promise<{ messageId: string }>;
  sendEmail(req: EmailRequest): Promise<{ messageId: string }>;   // fallback channel
  verifyWebhook(url: string, params: Record<string, string>, signature: string): boolean;
}
```

Rules enforced **inside the adapter**, so no caller can bypass them:

1. Refuse to send to a number with `sms_opt_out_at` set → throws `RecipientOptedOutError`.
2. Refuse to send a `MARKETING`-category template without a matching `consent_log` grant (TCPA).
3. Append the tenant's STOP/HELP footer to the first message to any new recipient.
4. Truncate/segment awareness: warn if a rendered template exceeds 3 segments.
5. All sends carry `statusCallbackUrl` so delivery failures are observable.

⛔ **GATE-09:** A2P 10DLC registration must be `VERIFIED` before production volume. The adapter checks a
config flag `GRACE_SMS_10DLC_READY`; when false it logs and routes to the email fallback instead of
sending traffic that carriers will filter. Start registration on day one (design brief §3.5).

---

## 7. `VoicePort` — Vapi

Used by `src/grace_platform/vapi/deploy.py` and by outbound-call features in Phase F. Not on the hot path.

```ts
export interface VoicePort {
  listAssistants(): Promise<VapiAssistant[]>;
  upsertAssistant(def: VapiAssistantDefinition): Promise<VapiAssistant>;
  listTools(): Promise<VapiTool[]>;
  upsertTool(def: VapiToolDefinition): Promise<VapiTool>;
  getCall(id: string): Promise<VapiCall>;
  createOutboundCall(req: OutboundCallRequest): Promise<VapiCall>;  // Phase F: reminders
}
```

---

## 8. Fakes — mandatory, first-class, shipped

Every port has an in-memory fake in `packages/testing/src/fakes/`. The fakes are **not** stubs that
return fixed values; they maintain state and enforce the same rules as the real service.

| Fake | Models |
|---|---|
| `FakePms` | An appointment store, configurable capability flags, injectable latency and failure rates, cursor pagination |
| `FakeCalendar` | Event store with 409-on-duplicate-id semantics |
| `FakePayments` | Sessions that can be driven to paid/failed/expired; emits webhook payloads |
| `FakeMessaging` | Records sends; enforces opt-out; simulates carrier filtering |

The entire integration suite runs against fakes. This means the full booking saga — including Track A,
deposits, SMS and PMS write-back — is testable in CI with no credentials and no network. That is what
allows Phases A–C to proceed while ⛔ GATE-01 is still open.

**Fidelity rule:** when a real API surprises us, the fix lands in the fake *and* the adapter in the same
PR, with a regression test. Otherwise the fakes drift and the suite becomes theatre.

---

## 9. Contract tests

For each adapter, a contract test suite asserts the adapter and its fake satisfy the *same* behavioural
specification:

```ts
// TARGET — tests/adapters/contract/test_pms_contract.py
export function pmsContract(name: string, makeSubject: () => Promise<PmsPort>) {
  describe(`PmsPort contract: ${name}`, () => {
    it('listAppointments paginates to completion without duplicates', …);
    it('getAppointment returns null for unknown id, does not throw', …);
    it('findCustomerByPhone normalises to E.164 before querying', …);
    it('write methods throw NotSupportedByProvider when capability is false', …);
    it('surfaces 429 as RateLimitedError with retryAfter', …);
    it('does not retry on 400', …);
  });
}
pmsContract('fake', async () => new FakePms());
pmsContract('vagaro', async () => new VagaroAdapter(cassetteClient()));   // recorded cassettes
```

Cassettes are recorded once against the live API (with secrets scrubbed) and committed. Re-record
deliberately, never automatically.

---

## 10. Acceptance criteria

✅ **AC-05.1** `PmsPort`, `CalendarPort`, `PaymentsPort`, `MessagingPort`, `VoicePort` exist in
`contracts` with no imports from any other `@grace/*` package.
✅ **AC-05.2** Every adapter method has an explicit timeout; a test proves an unbounded call is impossible.
✅ **AC-05.3** Circuit breaker opens after the configured failures and rejects immediately while open.
✅ **AC-05.4** Retry does not fire on a 400; does fire on 429 and honours `Retry-After`.
✅ **AC-05.5** Every port has a fake, and the contract suite passes for both fake and real implementation.
✅ **AC-05.6** `MessagingPort` refuses an opted-out recipient and a non-consented marketing template.
✅ **AC-05.7** Setting `capabilities.writeAppointments = true` on the fake causes the booking saga to take
the native-write path with no other code change (proves ADR-0007 pays off).
✅ **AC-05.8** No adapter logs a secret, token, PAN, or full phone number at any level.

## 11. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **GATE-01** | Does Vagaro offer appointment create/update/cancel, today or under an enterprise agreement? | It decides whether Track B — an entire application — exists at all. The capability flag and the port shape are built so that either answer is a small diff, but the answer itself has a 7-business-day clock and nobody has started it. | Vagaro |
| **GATE-03** | Vagaro's numeric rate limits, pagination, error codes, OAuth token path and TTL | Conservative defaults are in place, so this tunes the token bucket rather than blocking the adapter. | Vagaro |
| **GATE-07** | Does a Google Calendar event synced into Vagaro actually *block* the slot, or is it cosmetic? | **The cheapest and most consequential open question in the project** — 30 minutes, no code — and it decides whether Track A is viable at all. | us, on any day we choose |
| **GATE-08** | Do Vagaro card processing and Stripe deposits reconcile acceptably for the bookkeeper? | Decides which payments adapter ships. `PaymentsPort` is unchanged either way. | PalmLeaf bookkeeper |
| **Q-PA.1** | Should D-01/D-02 (fakes, resilient client) be pulled forward into Phase C? | Neither is blocked, and every later adapter needs both. Building them alongside Phase C means adapters start with a tested foundation instead of acquiring one. | Engineering |
