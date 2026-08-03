# PalmLeaf Massage & Wellness — "Grace" AI Receptionist
## Complete Architecture & End-to-End Implementation Pipeline

**Client:** PalmLeaf Massage & Wellness, 400 W. Dundee Rd Unit 8, Buffalo Grove, IL 60089
**Stack:** Vapi (voice) → n8n (orchestration) → Vagaro (booking system of record)
**Document date:** July 30, 2026
**Status:** Design for build. Contains one blocking dependency — see Section 1.

---

## 0. Executive Summary

Grace is a voice AI receptionist that answers PalmLeaf's main line 24/7, answers business questions, books/reschedules/cancels appointments against the Vagaro calendar, collects deposits, sends confirmation SMS, and escalates to a human when needed.

The architecture is four layers:

| Layer | Technology | Responsibility |
|---|---|---|
| **Telephony** | RingCentral → Twilio → Vapi | Carry the call, present it to the AI |
| **Conversation** | Vapi (STT + LLM + TTS + turn-taking) | Talk to the caller, decide when to call a tool |
| **Orchestration** | n8n | Execute tools, enforce business rules, call external systems |
| **Systems of record** | Vagaro, Postgres, Stripe, Twilio SMS | Store and act on the outcome |

**The single most important design constraint is in Section 1: Vagaro does not publish an API that creates appointments.** The entire booking design in this document is built around that fact. Do not begin development before reading it.

**Recommended delivery:** 4 phases over ~8–10 weeks, with a revenue-generating Phase 1 (answering + qualification + SMS deflection) live in ~2 weeks while the harder booking write-path is validated.

---

## 1. ⚠️ Critical Finding: The Vagaro Write-Path Problem

### 1.1 What we verified

Vagaro's developer surface ("Enterprise Business API V2", `https://api.vagaro.com`) is gated behind Settings → Developers → APIs & Webhooks, requires a paid non-trial plan with Vagaro Credit Card Processing active, costs $10/month including 5,000 calls ($0.002/call overage), and takes roughly 5–7 business days for manual approval.

The published operation set is:

| Operation | Method | Type |
|---|---|---|
| `/merchants/generate-access-token` | POST | auth |
| `/appointments` | GET | **read** |
| `/appointments/{appointmentId}` | GET | **read** |
| `/customers` | GET | **read** |
| `/customers/{customerId}` | GET | **read** |
| `/employees` | GET | **read** |
| `/employees/{employeeId}` | GET | **read** |
| `/employees/{employeeId}/locations/{businessId}/assignment` | PUT / DELETE | write (staff only) |
| `/locations`, `/locations/{businessId}` | GET | **read** |

**There is no `POST /appointments`. There is no availability-search endpoint. There is no customer-create endpoint.** The only write operations are staff-to-location assignment.

**Re-verified 31 July 2026 against Vagaro's own documentation.** Vagaro's official API introduction page (`docs.vagaro.com/public/reference/api-introduction`) lists what their APIs let you do. The verbs are unambiguous:

| Capability area | Vagaro's own description | Verb |
|---|---|---|
| Employee Management | Assign/unassign employees across locations, provision or deprovision calendars | **write** |
| Appointments | <q>Retrieve details about a Vagaro appointment</q> — status, start time, provider | **read** |
| Customers | Retrieve contact information and profile tags | **read** |
| Employees | Retrieve service-provider contact details and reporting lines | **read** |

Every appointment and customer capability Vagaro documents is a *retrieve*. The only documented write capability is employee/location administration. This is Vagaro describing their own product, not a third party inferring it.

Vagaro support has separately told merchants asking this exact question that they cannot find appointment create/update functionality because it does not exist, and referred the request to their development team as a feature suggestion.

Vagaro's webhooks are **outbound only** — they notify you when something changes (Appointments, Customers, Employees, Transactions, Form Responses, Business Locations, plus booking-widget interaction events). They are a read channel, not a write channel.

### 1.2 What this means

> The literal requirement — "AI books a slot and adds it on their Vagaro" — **cannot be satisfied by Vagaro's official API.** Any vendor claiming otherwise is either using browser automation, using a human-in-the-loop queue, or has a private Enterprise agreement.

This is not a reason to stop. It is a reason to design the write path deliberately, with a primary route and real fallbacks, and to price the maintenance burden honestly.

### 1.3 The four write paths, ranked

**Track A — Google Calendar bridge (recommended primary, low risk)**
Vagaro supports two-way Google Calendar sync, including *Sync Google Calendar to Vagaro*. n8n writes a structured event to the assigned provider's synced Google Calendar; Vagaro pulls it in and the time is blocked on the real business calendar in near real time.

- ✅ Officially supported, no ToS risk, no scraping, fast, resilient
- ✅ Guarantees the slot is held — which is the commercially critical part
- ⚠️ Arrives as a calendar event/personal task, **not** a first-class Vagaro appointment with a linked customer record, service code, and deposit
- ⚠️ Must be validated in PalmLeaf's actual account during Phase 0 — sync behavior varies by plan and per-employee configuration

**Track B — Headless booking-widget automation (creates a true appointment)**
A hardened Playwright worker drives PalmLeaf's own public Vagaro booking widget exactly as a customer would: select service → provider → slot → customer details → deposit → confirm.

- ✅ Produces a genuine Vagaro appointment: real customer record, correct service, deposit captured, Vagaro's own confirmation email/SMS fires
- ⚠️ Fragile — breaks whenever Vagaro ships UI changes; budget ongoing maintenance
- ⚠️ Review Vagaro's Terms of Service before shipping; get PalmLeaf's written authorization since it is their own account and their own booking page
- ⚠️ Too slow to run inside the call (10–40s). Runs **asynchronously after the slot is held**, never blocking the conversation

**Track C — SMS deep-link deflection (zero risk, always available)**
Grace confirms service, provider preference, and time, then texts a pre-filled Vagaro booking link. Caller taps and completes checkout themselves.

- ✅ Zero integration risk, zero PCI exposure, works from day one
- ⚠️ Conversion loss — some callers never complete it
- **This is the Phase 1 shipping path and the permanent fallback for every other track**

**Track D — Human-in-the-loop queue**
Anything the automation cannot complete lands in a staff task queue (Slack/email/dashboard) with a full structured summary and the call recording.

### 1.4 Recommended composite

```
Slot held instantly via Track A (Google Calendar → Vagaro)
        ↓
Deposit link sent via SMS (Stripe) — appointment confirmed on payment
        ↓
Track B worker upgrades the hold into a true Vagaro appointment (async, retried)
        ↓
On Track B failure after N retries → Track D staff task + caller keeps their held slot
        ↓
Track C used for any caller who prefers to self-serve, or any edge case
```

The caller's experience is identical in all cases: "You're booked for Tuesday at 2 with Maria, I've texted you the confirmation and deposit link."

**Action item, do this first:** submit the Vagaro API request form now (5–7 business day approval), and simultaneously ask Vagaro Enterprise Sales directly whether appointment-write endpoints are available under an enterprise agreement. If they are, Track B becomes unnecessary and the project gets dramatically simpler and cheaper.

---

## 2. Target Architecture

### 2.1 System diagram

```
                        ┌──────────────────────────┐
   Caller               │  RingCentral 847.961.4800│
   ──────────────────▶  │  (unconditional forward) │
                        └────────────┬─────────────┘
                                     ▼
                        ┌──────────────────────────┐
                        │  Twilio DID (SIP → Vapi) │
                        └────────────┬─────────────┘
                                     ▼
        ┌────────────────────────────────────────────────────┐
        │                    VAPI                            │
        │  Deepgram STT ─ LLM ─ ElevenLabs TTS ─ endpointing │
        │  Assistant "Grace" + tool definitions              │
        └───────┬──────────────────────────────┬─────────────┘
                │ tool calls (sync, <1.5s)     │ end-of-call report
                ▼                              ▼
        ┌────────────────────────────────────────────────────┐
        │                     n8n                            │
        │  Tool Router → 12 workflows → business rules       │
        └───┬────────┬────────┬────────┬────────┬────────────┘
            │        │        │        │        │
            ▼        ▼        ▼        ▼        ▼
      ┌─────────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐
      │Postgres │ │Google│ │Stripe│ │Twilio│ │Playwright│
      │Availab. │ │ Cal  │ │      │ │ SMS  │ │  Worker  │
      │ Mirror  │ └───┬──┘ └──────┘ └──────┘ └────┬─────┘
      └────▲────┘     │                            │
           │          ▼                            ▼
           │     ┌─────────────────────────────────────┐
           └─────┤            VAGARO                   │
    webhooks +   │  calendar · customers · payments    │
    GET polling  └─────────────────────────────────────┘
```

### 2.2 The core latency principle

**Vagaro is never called synchronously during a conversation.** Its API is rate-limited, metered per call, and adds unpredictable round-trip time. A caller will not tolerate four seconds of silence while we query a third-party scheduler.

Instead, we maintain a **local Availability Mirror** in Postgres (Section 5). Every in-call question — "do you have anything Thursday evening?" — is answered from a local index in under 50ms. Vagaro is reconciled in the background via webhooks and periodic polling.

This one decision is what makes the difference between an AI that feels like a receptionist and one that feels like an IVR.

### 2.3 Latency budget (target: <900ms perceived response)

| Stage | Budget |
|---|---|
| STT endpointing / turn detection | 150–250ms |
| LLM first token | 250–400ms |
| n8n tool round-trip (local DB read) | 80–200ms |
| TTS first audio | 120–200ms |
| **Total perceived** | **~700–1000ms** |

Ramon's requirement — *"concise and short answers, no pause in between Q/A"* — is a latency spec, not a style note. It is met by: local availability reads, aggressive endpointing settings, short system-prompt responses, streaming TTS, and filler phrases on any tool call expected to exceed 800ms.

---

## 3. Telephony Layer

### 3.1 Current state
PalmLeaf uses RingCentral (VOIP) on **847.961.4800**.

**DECISION (31 Jul 2026): Option B — Vapi BYO-SIP trunk is the selected path.**

### 3.2 ⚠️ Correction: RingCentral SIP credentials are NOT a trunk

RingCentral does issue SIP credentials for third-party devices:

```
SIP Domain:       sip.ringcentral.com:5060
Outbound Proxy:   sip10.ringcentral.com:5090
User Name/SIP ID: 1832XXXXXXX
Password:         ********
Authorization ID: 8888XXXXXXXX
```

**These are device-registration credentials, not a SIP trunk termination URI.** They let a desk phone or softphone register *into* RingCentral. They do not let an external platform such as Vapi originate or terminate trunked calls. The two are different SIP roles and the credentials are not interchangeable. `sip.ringcentral.com` is a registrar, not a termination endpoint.

RingCentral has stated this directly and repeatedly:

| Source | Statement |
|---|---|
| RC developer community — Retell integration | User asked to set up a termination URI with credential auth; RC replied they have **no open/public SIP trunking API** and referred to partner sales |
| RC developer community — LiveKit integration | *"We don't open SIP trunk to 3rd party developers"*; earlier in the same thread, SIP device credentials *"may not work as a SIP trunk"* |
| RingCentral Ideas (open feature request) | RC SIP endpoints are *"designed for device registration only, not for SIP trunking"* — filed after a customer hit TLS handshake failures (legacy CN field, SAN mismatch) integrating ElevenLabs |
| RC `createSIPRegistration` API | Third-party apps reportedly limited to **WSS transport only** — not TCP/TLS/UDP |

Additionally, where RingCentral does discuss trunking commercially, it is reported to carry a **~20-user minimum** — a threshold a single-location salon does not meet.

### 3.3 How Option B is actually implemented

Option B stands. The trunk simply comes from a carrier that offers a real **dedicated termination URI**, not from RingCentral registration credentials.

```
847.961.4800 (ported or forwarded)
   └─ SIP carrier with dedicated termination URI (Twilio Elastic SIP Trunking)
        └─ sip:847XXXXXXX@{credentialId}.sip.vapi.ai   [TLS :5061 ;transport=tls]
             └─ Vapi assistant "Grace"
```

**Carrier options, in preference order:**

1. **Twilio Elastic SIP Trunking → Vapi BYO-SIP (recommended).** Genuine dedicated termination URI and origination config, documented on both sides, TLS/SRTP clean, self-service — no partner negotiation.
2. **Alternative SIP carrier** (Telnyx, Bandwidth, Vonage). Same pattern; select on price, latency, and region.
3. **RingCentral partner-tier trunking.** RC indicated trunking *may* exist for partners via sales. If PalmLeaf's account or our agency qualifies, this removes the extra carrier — but it is a commercial conversation, not self-service configuration. Treat as a later optimization, not the day-one path.

**Vapi BYO-SIP setup (identical regardless of carrier):**

```bash
# 1. Create the trunk credential
POST https://api.vapi.ai/credential
{
  "provider": "byo-sip-trunk",
  "name": "PalmLeaf Trunk",
  "gateways": [{ "ip": "<carrier SIP gateway>", "inboundEnabled": true }],
  "outboundLeadingPlusEnabled": true,
  "outboundAuthenticationPlan": { "authUsername": "USER", "authPassword": "PASS" }
}

# 2. Bind the number
POST https://api.vapi.ai/phone-number
{ "provider": "byo-phone-number", "number": "+18479614800", "credentialId": "<id>" }
```

Inbound URI: `sip:847XXXXXXX@{credentialId}.sip.vapi.ai` (EU: `.sip.eu.vapi.ai`). Vapi's docs warn that IP-auth on a *shared* URI is unreliable — the dedicated termination URI is mandatory, which is exactly why RingCentral's registration credentials cannot be substituted here.

**Action item:** confirm with RingCentral whether PalmLeaf can port or forward 847.961.4800, and whether partner-tier trunking is available on their account. Until that is confirmed in writing, build against Twilio Elastic SIP Trunking.

### 3.3a Fallback if trunking stalls
Keep 847.961.4800 on RingCentral and forward it to a Twilio DID that bridges into Vapi. One extra hop (~50-150ms), no trunking negotiation, number untouched, instant rollback by disabling forwarding. Useful for the after-hours-first gradual rollout regardless of the final trunk decision.

> Known gotcha either way: RingCentral can overwrite caller ID with the intermediary number on transfers back into RC. Preserve the original `From` / P-Asserted-Identity when transferring to a human.

### 3.4 Human transfer path
Per Ramon's requirement: frustrated caller → apologize → warm transfer to a customer rep; if nobody answers, take a message and page the manager.

```
transferToHuman tool
   → Vapi transferCall to RingCentral front-desk extension
   → ring 25s
   → no answer? → Vapi resumes, apologizes, takes structured message
   → n8n: SMS to manager's mobile + customer service line + Slack alert
   → callback SLA logged
```

Configure as a **warm transfer with a whisper message** ("Transferring an upset caller, booking issue") so staff have context before they pick up.

### 3.5 SMS — plan for A2P 10DLC now

Booking confirmations go out over **Twilio Programmable SMS**, not RingCentral.

> ⚠️ **Schedule risk:** US A2P 10DLC brand + campaign registration takes **1–3 weeks** and must complete before production SMS volume. Unregistered traffic is filtered by carriers. **Start this on day one of the project** — it is the second-longest lead-time item after Vagaro API approval.

Message templates must include business name and STOP/HELP language for TCPA compliance.

---

## 4. Conversation Layer — Vapi Assistant "Grace"

### 4.1 Model configuration

| Component | Recommendation | Rationale |
|---|---|---|
| Transcriber | Deepgram Nova-3, `endpointing: 180ms`, numerals enabled | Fast, strong on names/times/phone numbers |
| LLM | A fast frontier model, `temperature: 0.3` | Low temp — this is a policy-bound role, not a creative one |
| Voice | ElevenLabs Turbo/Flash, warm female preset | Matches "friendly, smiling" brief |
| `silenceTimeoutSeconds` | 20 | |
| `maxDurationSeconds` | 900 | Hard cap on runaway calls |
| `backgroundDenoisingEnabled` | true | Spa lobby has music and water features |
| Interruption handling | enabled, `numWords: 2` | Callers correct times and spellings constantly |

### 4.2 Greeting

Ramon's draft is too long for a first turn — it front-loads a capability list before the caller has said anything. Recommended, preserving his required elements:

> "Hi, this is Grace, PalmLeaf's virtual assistant. This call may be recorded for quality. How can I help you today?"

Recording disclosure stays in the **first turn**, before any substantive exchange — this is a legal requirement, not a preference (Section 11.1). The capability list ("booking, hours, directions") moves to the fallback prompt used when a caller hesitates or says "um, I'm not sure."

### 4.3 System prompt structure

```
[IDENTITY]        Grace, PalmLeaf Massage & Wellness, Buffalo Grove IL
[STYLE]           Warm, concise. 1–2 sentences per turn. Never list more than
                  3 options aloud. Speak times as "two fifteen", not "14:15".
[KNOWLEDGE]       Hours, address, landmarks, parking, memberships, policies
[TOOLS]           When to call each tool; never guess availability or price
[GUARDRAILS]      Never diagnose. Never quote a price not returned by a tool.
                  Never take a card number by voice. Never promise a provider
                  by name unless the tool confirmed it.
[ESCALATION]      Triggers for transferToHuman
[UNKNOWN]         "Let me get someone who can answer that properly."
```

### 4.4 Knowledge base (from the questionnaire)

| Topic | Content |
|---|---|
| Address | 400 W. Dundee Rd, Unit 8, Buffalo Grove, IL 60089 |
| Landmarks | Across from Old National Bank, Kingswood United Methodist Church, Fifth Third Bank |
| Parking | Free parking |
| Hours | Monday–Sunday, 8:00 AM – 8:30 PM |
| Holidays | Open (incl. July 4th); closures posted to website + phone greeting |
| Memberships | 60-min $90 · 90-min $135 · one-time $49 enrollment. Member rates extend to acupuncture, chiropractic, cryo body sculpting, skin health |
| Cancellation | 48-hour policy. Room Reservation Deposit required; non-refundable if cancelled/rescheduled inside 48h or no-show |
| Intake | Required before appointment; link sent by SMS |
| Medical | Recent surgery or cancer → **do not book, route to staff**; may require physician clearance |
| Providers | All seasoned, individual styles, trained for chronic issues and stress relief |
| Upsell | Membership upgrade |

> **Note the questionnaire's internal contradiction on cancellations.** One answer says "100% charge for the service"; Ramon's says "Room Reservation Deposit is non-refundable." Grace must state exactly one policy. **This must be resolved by PalmLeaf in writing before launch** — an AI quoting the wrong cancellation fee creates real chargeback and dispute exposure. Listed in Section 15.

### 4.5 The "Ola/Aliya/Ramon/Soneth" problem

The questionnaire captures four different staff members answering the same questions differently, and two (Aliya, Soneth) left every field blank. **Grace can only have one voice and one policy set.** Section 15 contains the sign-off checklist required to collapse these into a single approved source of truth. Do not build the knowledge base from the questionnaire as-is.

---

## 5. The Availability Mirror (core subsystem)

This is the component that makes in-call booking feel instant. It is a local, always-warm projection of the Vagaro calendar.

### 5.1 How it stays current

| Source | Trigger | Purpose |
|---|---|---|
| Vagaro webhooks | Appointment created/updated/cancelled | Real-time invalidation (primary) |
| Vagaro webhooks | Customer created/updated | Keep client records fresh |
| `GET /appointments` | Every 10 min, rolling 60-day window | Drift correction / safety net |
| Google Calendar watch | Push notification | Catch staff-side manual blocks |
| Full reconciliation | Nightly 3:00 AM | Authoritative resync |

> Vagaro webhooks require a 2xx response within **20 seconds** or they retry up to 5 times over 15 minutes with exponential backoff. The n8n receiver must therefore **acknowledge immediately and process asynchronously** — never do the work inline in the webhook handler.

### 5.2 Slot computation
```
free_slots = business_hours
           − provider_working_hours_exceptions
           − booked_appointments (from mirror)
           − google_calendar_blocks
           − active_slot_holds (TTL)
           − buffer_time (room turnover, per service)
```

### 5.3 Preventing double-booking (mandatory)

Two callers can be on two lines at the same second. Without locking, both get told "2:00 PM is available."

```
1. checkAvailability returns slots AND places a 4-minute soft hold
   on the top 3 offered slots, keyed to the Vapi call ID
2. Caller accepts → hold is promoted to a confirmed reservation (15 min TTL)
3. Deposit paid OR staff confirms → reservation becomes permanent
4. Call ends without acceptance → holds expire automatically
5. Every write carries an idempotency key: {callId}:{slotId}
```

The idempotency key is essential. Vapi will retry a tool call on timeout, and without it a network blip becomes a duplicate appointment.

---

## 6. Tool Catalog (Vapi → n8n)

Each tool is a Vapi custom tool pointing at an n8n production webhook URL. All are `POST`, all return within their stated budget, all are idempotent.

| # | Tool | Sync? | Budget | Purpose |
|---|---|---|---|---|
| 1 | `getBusinessInfo` | sync | 100ms | Hours, address, parking, directions, holidays |
| 2 | `lookupCustomer` | sync | 250ms | Match caller ID against mirror; returns name, membership, visit history |
| 3 | `getServicesAndPricing` | sync | 150ms | Service catalog + member vs non-member pricing |
| 4 | `checkAvailability` | sync | 300ms | Free slots + places soft holds |
| 5 | `createBooking` | sync | 800ms | Confirm reservation, write Google Calendar event, enqueue Track B |
| 6 | `rescheduleAppointment` | sync | 800ms | Move existing appointment, apply 48h rule |
| 7 | `cancelAppointment` | sync | 600ms | Cancel, apply deposit policy, notify staff |
| 8 | `sendIntakeForm` | **async** | — | SMS intake link |
| 9 | `sendDepositLink` | **async** | — | SMS Stripe payment link |
| 10 | `sendBookingConfirmation` | **async** | — | SMS confirmation |
| 11 | `transferToHuman` | sync | — | Warm transfer with whisper |
| 12 | `takeMessage` | sync | 300ms | Structured message → staff queue |
| 13 | `flagMedicalHold` | sync | 300ms | Surgery/cancer disclosure → block booking, route to staff |

Tools 8–10 use Vapi's `async: true` flag — Grace acknowledges immediately ("I'm texting that to you now") while the work completes in the background. This removes 400–900ms of dead air from the three most common actions.

### 6.1 Example tool contract — `checkAvailability`

**Request from Vapi:**
```json
{
  "message": {
    "toolCalls": [{
      "id": "call_a1b2c3",
      "function": {
        "name": "checkAvailability",
        "arguments": {
          "serviceType": "60_minute_massage",
          "preferredDate": "2026-08-04",
          "timePreference": "evening",
          "providerPreference": null,
          "isMember": true
        }
      }
    }]
  },
  "call": { "id": "vapi_call_xyz", "customer": { "number": "+18475551234" } }
}
```

**Response to Vapi (must match `toolCallId`):**
```json
{
  "results": [{
    "toolCallId": "call_a1b2c3",
    "result": "Three openings Tuesday evening: 5:15 PM with Maria, 6:30 PM with James, 7:00 PM with Maria. Holds placed for 4 minutes."
  }]
}
```

> Return **natural language** in `result`, not raw JSON. The LLM speaks this back. Returning a JSON blob produces stilted, robotic phrasing and wastes tokens.

### 6.2 n8n webhook node requirements (common failure source)

Every tool workflow must have:
- Webhook node set to **POST**, using the **production** URL (not test)
- **Raw Body** enabled
- Response Mode = **"Using Respond to Webhook Node"**
- A **Respond to Webhook** node on every branch, including error branches
- Workflow **Active**
- HMAC verification of Vapi's `x-vapi-signature` header

A missing Respond-to-Webhook node on an error branch is the single most common cause of "the agent just goes silent mid-call."

---

## 7. End-to-End Booking Flow

The critical path, turn by turn.

```
[1]  Caller dials 847.961.4800
     RingCentral forwards → Twilio → Vapi

[2]  Vapi fires assistant-request (if dynamic routing used)
     ⚠️ n8n MUST respond in <7.5s — this limit is fixed and not configurable.
        Return a minimal assistant immediately; enrich via Live Call Control.

[3]  Grace: "Hi, this is Grace, PalmLeaf's virtual assistant. This call may be
     recorded for quality. How can I help you today?"

[4]  In parallel (non-blocking): lookupCustomer(callerId)
     → known member? Grace can greet by name and quote member rates

[5]  Caller: "I'd like a 90-minute massage sometime Tuesday evening."

[6]  → getServicesAndPricing   (member: $135)
     → checkAvailability(90_minute, 2026-08-04, evening)
     → 3 slots + 4-minute soft holds

[7]  Grace: "I have 5:15 with Maria or 6:30 with James on Tuesday.
     As a member that's one thirty-five. Which works?"

[8]  Caller: "6:30 with James."

[9]  MEDICAL SCREEN (mandatory gate):
     Grace: "Any recent surgery or ongoing medical treatment I should note?"
       → "yes" → flagMedicalHold → DO NOT BOOK → transfer to staff
       → "no"  → proceed

[10] → createBooking()
       a. Promote hold → reservation (15-min TTL), idempotency key {callId}:{slotId}
       b. Write Google Calendar event → syncs into Vagaro (Track A) — SLOT IS HELD
       c. Enqueue Track B job (Playwright → real Vagaro appointment)
       d. Return in <800ms

[11] Grace: "You're booked, Tuesday the fourth at six thirty with James."

[12] → sendDepositLink (async)   Stripe payment link by SMS
     → sendIntakeForm  (async)   Intake form link by SMS
     → sendBookingConfirmation (async)

[13] Grace states the policy verbatim:
     "There's a room reservation deposit to hold the room — I've texted the
      link. Just so you know, changes inside 48 hours mean the deposit
      isn't refundable. Anything else I can help with?"

[14] Call ends. Vapi end-of-call-report → n8n:
       - transcript + recording URL → Postgres
       - structured summary → staff dashboard
       - QA scoring
       - Track B job executes async

[15] Track B outcome:
       ✅ Success → mirror updated with real Vagaro appointment ID;
                    Track A placeholder event reconciled
       ❌ Failure after 3 retries → Track D staff task, Slack alert,
                    caller's slot REMAINS HELD (never silently dropped)

[16] Deposit paid (Stripe webhook) → status: CONFIRMED → confirmation SMS
     Not paid in 60 min → reminder SMS
     Not paid in 24 hr  → release slot + notify caller + notify staff
```

### 7.1 Reschedule and cancel

Both follow the same shape, with the 48-hour rule enforced **in n8n, not in the prompt**:

```
hours_until_appointment >= 48  → free change, deposit rolls forward
hours_until_appointment <  48  → Grace states deposit is forfeited,
                                 gets explicit verbal confirmation,
                                 logs the confirmation for dispute defense
```

Never let the LLM compute the 48-hour boundary. It is a date-math operation with money attached — it belongs in deterministic code. The prompt says "call the tool"; the tool decides.

---

## 8. Data Model (Postgres)

```sql
-- Availability mirror
providers            (id, vagaro_employee_id, name, google_calendar_id,
                      services[], active)
services             (id, vagaro_service_id, name, duration_min, buffer_min,
                      price_member, price_nonmember, deposit_amount)
business_hours       (day_of_week, open_time, close_time)
schedule_exceptions  (date, provider_id, type, note)   -- holidays, time off
appointments_mirror  (id, vagaro_appointment_id, provider_id, service_id,
                      customer_id, start_ts, end_ts, status, source,
                      last_synced_at)

-- Booking state machine
slot_holds           (id, call_id, provider_id, start_ts, expires_at, state)
                     -- state: SOFT_HOLD → RESERVED → CONFIRMED → RELEASED
bookings             (id, call_id, hold_id, idempotency_key UNIQUE,
                      track_a_event_id, track_b_status, vagaro_appointment_id,
                      deposit_status, stripe_session_id, created_at)

-- Customers
customers            (id, vagaro_customer_id, phone UNIQUE, name, email,
                      membership_tier, intake_completed_at)
                     -- NO medical detail stored here. See §11.3

-- Operations
calls                (id, vapi_call_id, phone, started_at, duration_s,
                      outcome, transcript_url, recording_url, cost)
staff_tasks          (id, type, priority, payload, call_id, status,
                      assigned_to, resolved_at)
tool_invocations     (id, call_id, tool_name, latency_ms, status, error)
```

`bookings.idempotency_key UNIQUE` is the database-level guarantee against duplicate appointments from Vapi tool retries. Do not rely on application logic alone.

---

## 9. n8n Workflow Inventory

| Workflow | Trigger | Notes |
|---|---|---|
| `WF-01 Tool Router` | Vapi webhook | HMAC verify → dispatch by tool name → Respond to Webhook |
| `WF-02 Availability Query` | Sub-workflow | Local Postgres only. Never touches Vagaro. |
| `WF-03 Create Booking` | Sub-workflow | Hold promotion + Google Calendar write + Track B enqueue |
| `WF-04 Reschedule/Cancel` | Sub-workflow | 48-hour rule engine |
| `WF-05 Vagaro Webhook Receiver` | Vagaro webhook | **Ack immediately**, queue async. 20s limit. |
| `WF-06 Vagaro Poller` | Cron 10 min | `GET /appointments`, 60-day window, drift correction |
| `WF-07 Nightly Reconciliation` | Cron 3:00 AM | Full resync + integrity report |
| `WF-08 Track B Worker` | Queue consumer | Playwright job, 3 retries w/ backoff |
| `WF-09 SMS Dispatcher` | Async | Twilio, templated, opt-out honored |
| `WF-10 Payment Handler` | Stripe webhook | Deposit paid/failed/expired state transitions |
| `WF-11 End-of-Call Processor` | Vapi webhook | Transcript, summary, QA scoring, CRM write |
| `WF-12 Escalation & Alerting` | Internal | Staff tasks, Slack, manager SMS |
| `WF-13 Hold Expiry Sweeper` | Cron 1 min | Release expired holds |

**Deployment note:** self-host n8n (Docker) in **us-west-2** to sit close to Vapi's infrastructure and minimize tool round-trip latency. Use queue mode with Redis for concurrency. n8n Cloud is acceptable for Phase 1 but adds latency you will want back later.

---

## 10. Payments & PCI

PalmLeaf currently takes full pre-payment by phone for non-members and stores cards for members.

### 10.1 Hard rule

> **Grace must never ask for, hear, or store a credit card number.** Voice AI card capture pulls the entire stack — Vapi, n8n, transcripts, call recordings, logs — into PCI-DSS scope. That is a compliance and insurance problem far larger than this project's budget.

### 10.2 Approved payment patterns

| Pattern | Use | PCI scope |
|---|---|---|
| **Stripe payment link by SMS** | Deposits, pre-payment (default) | ✅ None — Stripe-hosted |
| **Vagaro booking widget checkout** | Track B bookings | ✅ None — Vagaro-hosted |
| **Existing member card on file** | Members only | ✅ None — Grace triggers a charge by token ID, never sees the card |
| **Transfer to staff** | Gift certificates, disputes, unusual cases | ✅ Out of scope |
| ~~Voice card capture~~ | ❌ **Never** | 🚫 Full PCI scope |

Note that Vagaro API access itself requires Vagaro Credit Card Processing to be active — so PalmLeaf will be running Vagaro payments and Stripe deposits in parallel. Confirm with PalmLeaf's bookkeeper how these reconcile before launch, or use Track B checkout exclusively to keep everything inside Vagaro.

---

## 11. Compliance

This section is not optional. Illinois is one of the strictest states in the country for exactly the things this system does.

### 11.1 Call recording — Illinois is all-party consent
Illinois requires consent from **all parties** to record a private conversation (720 ILCS 5/14-2). Ramon's draft greeting already includes the disclosure — keep it, and enforce these rules:

- Disclosure occurs in Grace's **first utterance**, before any substantive exchange
- If a caller objects → either continue with recording disabled, or transfer to a human
- Recording retention policy documented; recommend 90 days then purge
- Never begin recording before the disclosure has played

### 11.2 BIPA — no voiceprints
The Illinois Biometric Information Privacy Act carries a private right of action and statutory damages per violation. **Do not enable voice identification, voice biometrics, or speaker recognition** in the Vapi configuration. Identify callers by caller ID only. This is a one-line configuration decision that avoids a category of litigation risk that has cost Illinois businesses very large sums.

### 11.3 Health information
Massage therapy sits close to healthcare. The questionnaire requires screening for recent surgery and cancer.

- Grace **asks the screening question** but **never records the answer's detail**
- A "yes" sets a boolean flag (`medical_hold: true`) and routes to staff — nothing more
- Never store diagnoses, conditions, treatments, or medications in Postgres or in call summaries
- Redact health disclosures from stored transcripts via a post-processing pass in WF-11
- Grace never gives medical advice, never assesses whether a condition is safe, never interprets a physician's clearance

### 11.4 TCPA / SMS
- Transactional booking confirmations to a caller who provided their number are permitted; **marketing messages are not** without separate express written consent
- STOP/HELP handling and opt-out suppression list mandatory
- A2P 10DLC registration required (Section 3.5)

### 11.5 AI disclosure
Several jurisdictions now require disclosing that a caller is speaking with an AI. "This is Grace, PalmLeaf's virtual assistant" satisfies this — **do not soften it** to imply Grace is human, and instruct the model to answer honestly if asked directly.

---

## 12. Failure Modes & Fallbacks

Design principle: **every failure degrades to a slower human path, never to a dropped caller.**

| Failure | Detection | Response |
|---|---|---|
| Vagaro API down | Health check | Serve from mirror; queue writes; alert |
| Vagaro API not yet approved | Known | Track A + Track C only; mirror seeded from Google Calendar |
| Track B (Playwright) breaks | Job failure | 3 retries → staff task; **slot stays held**; nightly UI-change canary test |
| n8n unreachable | Tool timeout | Grace: "Let me get someone" → transfer/message |
| Vapi outage | Uptime monitor | RingCentral forwarding auto-reverts to staff line / voicemail |
| LLM hallucinates a price | QA sampling | Prices only ever from `getServicesAndPricing`; prompt forbids improvising; weekly transcript audit |
| Double booking | DB constraint | Unique idempotency key + slot holds; nightly reconciliation report |
| Caller can't be understood | 2 failed retries | Immediate transfer, no third attempt |
| Angry caller | Sentiment + keywords | Apologize → warm transfer → if unavailable, message + manager SMS (per Ramon) |
| Deposit unpaid 24h | Cron | Release slot, notify caller and staff |
| SMS filtered by carrier | Twilio error code | Fallback to email; alert if 10DLC registration lapsed |

### 12.1 The kill switch
A single toggle that reverts RingCentral forwarding, sending all calls to staff. Documented, tested, and accessible to PalmLeaf's manager without developer involvement. Test it during Phase 1 acceptance.

---

## 13. Observability & QA

**Dashboards:** call volume, containment rate, booking conversion, average handle time, tool latency p50/p95/p99, transfer rate, deposit conversion, Track B success rate, cost per call.

**Alerting:** tool error rate >2%, p95 latency >1.5s, Track B failure rate >10%, Vagaro sync drift >5 records, any medical-hold flag, any transfer failure.

**Weekly QA ritual:** sample 20 calls. Score on: correct policy stated, correct price quoted, correct booking written, appropriate escalation, tone. Feed corrections into the prompt and the knowledge base. This is the loop that takes containment from ~60% to ~85% over the first two months — budget the time for it explicitly.

**Vapi test suites:** maintain automated voice tests for the 15 highest-frequency intents. Run before every prompt or tool change. Prompt edits are deploys and deserve regression tests.

---

## 14. Phased Rollout

### Phase 0 — Discovery & unblocking (Week 1) 🔴 START IMMEDIATELY
- [ ] Submit Vagaro API access request (5–7 business day approval)
- [ ] Ask Vagaro Enterprise Sales directly about appointment-write endpoints
- [ ] Start Twilio A2P 10DLC registration (1–3 weeks)
- [ ] **Validate Track A in PalmLeaf's live account** — does a Google Calendar event actually appear on the Vagaro calendar, and in what form?
- [ ] Confirm Vagaro plan tier + Vagaro CC Processing active (API prerequisite)
- [ ] Get PalmLeaf's written sign-off on the Section 15 checklist
- [ ] Review Vagaro ToS re: automated booking-widget interaction
- [ ] Export service catalog, provider list, provider schedules

**Phase 0 is the whole project's critical path.** Two external approvals with multi-week clocks and one unvalidated technical assumption sit here. Everything else is parallelizable; this is not.

### Phase 1 — Answer & deflect (Weeks 2–3) — *ships value early*
Grace answers hours, location, parking, directions, pricing, policies. Books nothing — uses Track C (SMS booking link) and takes messages. Runs **after-hours only** at first.
> Even at this stage PalmLeaf stops losing after-hours callers, which is where most missed revenue lives.

### Phase 2 — Booking (Weeks 4–6)
Availability mirror live. Track A holds slots. Stripe deposits. Confirmation SMS. Reschedule and cancel with the 48-hour engine. Still after-hours + overflow only.

### Phase 3 — Full Vagaro write (Weeks 6–8)
Track B Playwright worker in production behind retries and staff-task fallback. Reconciliation and drift monitoring. Expand to daytime overflow, then primary answer with staff overflow.

### Phase 4 — Optimization (Weeks 9–10+)
Outbound reminders and no-show recovery. Waitlist backfill for cancellations. Membership upsell flow. Bilingual (Spanish) assistant. Trunk consolidation if RingCentral partner-tier SIP becomes available. Weekly QA loop becomes routine operations.

---

## 15. Open Items Requiring PalmLeaf Sign-Off

The questionnaire has four respondents, two of whom left every field blank, and contains at least one direct policy contradiction. Grace can only speak with one voice. **These must be resolved in writing before Phase 1 launch.**

| # | Item | Issue | Owner |
|---|---|---|---|
| 1 | **Cancellation policy** | Contradiction: "100% charge for the service" vs. "Room Reservation Deposit is non-refundable." Which does Grace say? | PalmLeaf |
| 2 | Deposit amount | Never specified. Flat fee or % of service? Per service type? | PalmLeaf |
| 3 | "No valid reason" | One answer allows exceptions for valid reasons. Grace cannot adjudicate this — must route to a human. Confirm. | PalmLeaf |
| 4 | Non-member pre-payment | Full pre-payment vs. deposit-only — these conflict across answers | PalmLeaf |
| 5 | Greeting wording | Four variants submitted. Approve one. | PalmLeaf |
| 6 | Service catalog | Full list with durations, prices, buffer times, deposit amounts — not in questionnaire | PalmLeaf |
| 7 | Provider roster | Names, specialties, services offered, working hours | PalmLeaf |
| 8 | Transfer targets | Which extension for escalation? Manager's mobile for after-hours pages? | PalmLeaf |
| 9 | Massagebook → Vagaro | Transition is "slow." Is Vagaro the sole source of truth on day one? If both are live, which wins? | PalmLeaf |
| 10 | Vagaro plan + CC processing | API access requires a paid non-trial plan **with Vagaro Credit Card Processing active** — confirm both | PalmLeaf |
| 11 | Recording retention | How long are recordings and transcripts kept? | PalmLeaf + counsel |
| 12 | Track B authorization | Written authorization to automate their own booking widget | PalmLeaf |
| 13 | Membership add-on rates | "Access to membership rates for acupuncture, chiropractic, cryo, skin health" — actual numbers needed | PalmLeaf |

> **Item 9 deserves emphasis.** Building a booking integration against a system the client is "slowly transitioning into" is a moving target. If a caller books through Grace into Vagaro while the front desk is still booking into Massagebook, you get double-bookings that look like an AI failure but are an operations failure. Push for a hard cutover date before Phase 2.

---

## 16. Cost Model (estimated)

Assumes ~45 calls/day, ~3 min average — validate against PalmLeaf's actual RingCentral call logs before quoting.

**Per-minute (variable)**
| Item | Rate | Monthly (~4,050 min) |
|---|---|---|
| Vapi platform + STT + LLM + TTS | ~$0.13–0.18/min | $525–730 |
| Twilio inbound voice | ~$0.014/min | ~$57 |
| RingCentral forwarding leg | plan-dependent | verify |

**Fixed**
| Item | Monthly |
|---|---|
| Vagaro API (incl. 5,000 calls) | $10 |
| Twilio number + SMS (~600 msgs) | ~$10 |
| n8n self-hosted (VPS) | $20–40 |
| Postgres (managed) | $25 |
| Playwright worker VPS | $20–40 |
| Monitoring | $0–25 |
| **Fixed subtotal** | **~$85–150** |

**Estimated total: ~$700–950/month at this volume.**

Compare against a part-time receptionist at roughly $2,400–3,600/month for equivalent coverage — and note Grace covers all 87.5 open hours per week plus overnight, which no single hire does.

⚠️ **Not included:** build cost, and ongoing Track B maintenance. Budget 4–8 developer-hours per month for Playwright upkeep, because Vagaro will change their booking UI without notice. If Vagaro grants appointment-write API access, this line disappears entirely.

---

## 17. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Vagaro never offers appointment-write API** | High | High | Track A + B + C composite; already the plan |
| **Track B breaks on Vagaro UI change** | High | Medium | Canary tests, retries, staff-task fallback, maintenance budget |
| Vagaro API request rejected (plan/CC prerequisites) | Medium | High | Verify prerequisites in Phase 0 before building anything on it |
| A2P 10DLC delays SMS launch | Medium | Medium | Start day one; email fallback |
| Google Calendar → Vagaro sync doesn't behave as documented | Medium | **High** | **Validate in Phase 0** — this invalidates Track A if wrong |
| Massagebook/Vagaro dual-running causes double-books | Medium | High | Force a cutover date; single source of truth |
| Callers reject talking to AI | Medium | Medium | Fast, obvious path to a human; after-hours-first rollout |
| Illinois recording/BIPA non-compliance | Low | **Severe** | Section 11 controls; legal review before launch |
| Latency makes Grace feel robotic | Medium | Medium | Local availability mirror; async tools; latency SLOs |
| Wrong cancellation fee quoted | Medium | High | Resolve Item 1; policy in code, not prompt; QA sampling |

---

## 18. Immediate Next Actions

**This week, in this order:**

1. **Submit the Vagaro API access request.** 5–7 business day clock. Nothing downstream moves without it. Use wording along the lines of: *"Connecting an AI voice receptionist that answers inbound calls, books and manages appointments, and syncs customer records in real time. Requires Appointments and Customers webhooks plus API access to read and write appointments and customer information."* Select both **Appointments** and **Customers** webhook types.
2. **Email Vagaro Enterprise Sales** and ask explicitly: *do you offer appointment-create endpoints under an enterprise agreement?* A "yes" removes the riskiest component of this build.
3. **Start Twilio A2P 10DLC registration.** 1–3 week clock, runs in parallel.
4. **Run the Track A validation test** in PalmLeaf's live Vagaro account. Create a Google Calendar event on a synced provider calendar; confirm whether and how it appears in Vagaro. This single 30-minute test determines the entire booking architecture.
5. **Send PalmLeaf the Section 15 checklist** and get written sign-off, especially Item 1 (cancellation policy) and Item 9 (Massagebook cutover date).
6. **Pull PalmLeaf's RingCentral call logs** for the last 90 days — real call volume, time-of-day distribution, and after-hours miss rate. This validates both the cost model and the phasing.

---

## 19. Project Log

### 30 July 2026 — Discovery & Architecture

**Completed**
- Reviewed PalmLeaf's completed onboarding questionnaire
- Researched how Vagaro permits external software to connect
- **Confirmed blocker:** Vagaro does not allow appointments to be created from outside their system
- Identified and ranked four alternative routes for getting bookings onto their calendar
- Assessed how RingCentral connects to the AI phone layer
- Reviewed Illinois legal requirements — call recording consent, biometric data, health information
- Determined a safe method for taking deposits by phone without handling card numbers
- Produced this full architecture and build plan
- Estimated running cost at roughly $700–950/month
- Compiled 13 items requiring client sign-off (Section 15)

**Issues raised**
- Cancellation policy contradicts itself in the questionnaire — two different fees stated
- Four staff answered the form differently; two left it entirely blank
- Client is mid-migration from Massagebook to Vagaro with no cutover date — double-booking risk
- Deposit amount never specified
- Service list, prices, and staff schedules missing

**Open tasks**
- [ ] Apply for Vagaro access — up to 7 working days
- [ ] Ask Vagaro sales directly whether booking access is available
- [ ] Begin Twilio SMS registration — 1 to 3 weeks
- [ ] Run the 30-minute calendar test in the client's live account
- [ ] Send the client the Section 15 sign-off checklist
- [ ] Obtain 90 days of call records to confirm real phone volume
- [ ] Confirm the client's Vagaro plan tier and that card processing is active

**Waiting on client**
- Approved cancellation policy and deposit amount
- Approved greeting wording
- Service list, prices, and staff schedules
- Written authorization and a Massagebook switch-off date

---

## Appendix A — Vapi Assistant Skeleton

```jsonc
{
  "name": "Grace — PalmLeaf",
  "firstMessage": "Hi, this is Grace, PalmLeaf's virtual assistant. This call may be recorded for quality. How can I help you today?",
  "firstMessageMode": "assistant-speaks-first",
  "model": {
    "provider": "...",
    "model": "...",
    "temperature": 0.3,
    "messages": [{ "role": "system", "content": "<see §4.3>" }],
    "toolIds": ["<13 tools — see §6>"]
  },
  "voice": { "provider": "11labs", "model": "eleven_turbo_v2_5", "stability": 0.5 },
  "transcriber": { "provider": "deepgram", "model": "nova-3", "endpointing": 180 },
  "serverUrl": "https://n8n.palmleaf.internal/webhook/vapi-router",
  "serverUrlSecret": "<HMAC secret>",
  "silenceTimeoutSeconds": 20,
  "maxDurationSeconds": 900,
  "backgroundDenoisingEnabled": true,
  "recordingEnabled": true,          // disclosure is in firstMessage — required
  "endCallFunctionEnabled": true,
  "analysisPlan": {
    "summaryPrompt": "Summarize outcome, booking details, and any follow-up needed. Do NOT include medical details.",
    "structuredDataSchema": { /* intent, booked, providerRequested, escalated, medicalHold */ }
  }
}
```

## Appendix B — Escalation Triggers

Transfer to a human immediately on any of:
- Caller asks for a person, a manager, or "a real human"
- Frustration detected (sentiment, raised voice, profanity, repeated corrections)
- Medical disclosure: recent surgery, cancer, pregnancy complications, injury
- Any complaint, refund request, or dispute
- Gift certificate redemption
- Third failed comprehension attempt on the same question
- Any request to change a policy or waive a fee
- Anything Grace does not have a tool for

Grace never argues, never re-explains a policy a second time to an upset caller, and never says "I understand how you feel."

---

*Prepared for PalmLeaf Massage & Wellness. Section 1 and Section 15 require resolution before development begins.*

---

## 20. Code-First Build Pipeline (added 31 July 2026)

**Answer to the core question: yes — neither platform requires drag-and-drop.** Both Vapi and n8n are fully controllable from code, both ship official MCP servers, and both are explicitly designed to be driven by Claude Code. The entire system can live in one git repository and deploy via CI.

### 20.1 Vapi — code-first confirmed

Vapi has four independent code paths, all official:

| Path | What it is | Use |
|---|---|---|
| **REST API** | `api.vapi.ai` — assistants, tools, phone numbers, calls, squads | Source of truth; CI deploys against it |
| **CLI** | `vapi` — `vapi init`, `vapi assistant list/create`, `vapi listen` | Local dev + scripted deploys |
| **SDKs** | TypeScript, Python | Typed assistant/tool definitions |
| **MCP server** | `@vapi-ai/mcp-server` (npx) or hosted `https://mcp.vapi.ai/mcp` (streamable HTTP) | Claude Code drives Vapi directly |

Two details that matter for us:

- **`vapi listen` replaces ngrok.** It tunnels Vapi webhook events straight to localhost, so tool development against a live call is possible without exposing n8n publicly during the build.
- **Vapi publishes an official Agent Skills repo** (`VapiAI/skills`) following the Agent Skills spec, with skills like `create-assistant` and `create-tool`, plus a documentation MCP server that gives the agent RAG access to Vapi's full knowledge base. Install with `npx skills add VapiAI/skills`. This is Vapi explicitly supporting the Claude Code workflow you want.

MCP server capabilities: list/create/update/retrieve assistants (LLM, voice, transcriber, first message), list/create/retrieve calls including scheduled outbound, list/retrieve phone numbers, list/retrieve tools.

> ⚠️ **Design rule:** the MCP server is for authoring and iteration, not for production deployment. Production changes go through version-controlled JSON → CI → REST API. An LLM silently mutating a live assistant that is answering a client's phone is not an acceptable deployment model.

### 20.2 n8n — code-first confirmed

This changed recently and in our favour. n8n now ships an **official MCP server that can build workflows**, not just execute them. It is in Public Preview, and n8n's own guidance is that **coding agents such as Claude Code outperform chat clients** for this — their internal testing found Claude Code gets better results with the same prompt and same model. Requires n8n **2.18.4 or higher**.

Three routes, use all three at different stages:

| Route | Mechanism | Use |
|---|---|---|
| **Official n8n MCP server** | Enable in n8n settings → connect Claude Code via HTTP transport + Bearer token | Authoring and editing workflows conversationally |
| **`czlonkowski/n8n-mcp`** | Community MCP, `n8n_create_workflow`, `n8n_update_partial_workflow`, `validate_node`, `validate_workflow`, ~2,350 templates | Richer validation + template search; more mature than the official preview |
| **n8n Public REST API** | `POST /api/v1/workflows` with workflow JSON | **CI/CD — the production path** |

The key fact: **n8n workflows are just JSON objects.** Nodes, connections, parameters, credentials references — all serializable. That means workflows are code, they live in git, they diff in pull requests, and they deploy through a pipeline. The canvas is a viewer, not the source of truth.

### 20.3 Recommended build workflow

```
┌─────────────────────────────────────────────────────────┐
│  git repo: palmleaf-grace                               │
│                                                          │
│  /vapi/                                                  │
│    assistant.grace.json      ← assistant definition      │
│    tools/*.json              ← 13 tool definitions       │
│    prompts/system.md         ← versioned prompt          │
│  /n8n/                                                   │
│    workflows/WF-01..WF-13.json                           │
│  /services/                                              │
│    availability-mirror/      ← Postgres + sync service    │
│    track-b-worker/           ← Playwright                 │
│  /db/migrations/                                         │
│  /tests/                                                 │
│    vapi-suites/              ← voice regression tests     │
│  /.mcp.json                  ← Vapi + n8n MCP config      │
│  /.claude/skills/            ← VapiAI/skills installed    │
└──────────────────────┬──────────────────────────────────┘
                       │  CI (GitHub Actions)
          ┌────────────┴────────────┐
          ▼                         ▼
   Vapi REST API            n8n REST API
   (assistants, tools)      (POST /workflows, activate)
```

**Environments:** run **two n8n instances** — dev (port 5679) and production. Claude Code authors against dev via MCP. Workflows are validated, exported to JSON, committed, reviewed, then deployed to production by CI. Never let an agent write directly to the instance answering PalmLeaf's phone.

### 20.4 Step-by-step build sequence

```
STEP 1  Repo + MCP setup
        vapi init && vapi mcp setup
        npx skills add VapiAI/skills --skill create-assistant
        npx skills add VapiAI/skills --skill create-tool
        Enable n8n MCP (Settings → API → key; Settings → MCP → enable)
        Add both to .mcp.json; verify with /mcp in Claude Code

STEP 2  Infrastructure as code
        Postgres schema + migrations (§8)
        Docker compose: n8n (queue mode + Redis), Postgres, worker
        Deploy to us-west-2

STEP 3  Availability Mirror service
        Vagaro OAuth client (POST /merchants/generate-access-token)
        GET /appointments, /customers, /employees, /locations pollers
        Webhook receiver (ack <20s, process async)
        Slot computation + hold/reservation state machine
        ← This is pure application code. Build it NOW, during the
          5-day Vagaro approval wait. It needs no Vagaro access to
          write, only to test.

STEP 4  n8n workflows via MCP
        Claude Code authors WF-01..WF-13 against dev instance
        validate_node → validate_workflow → export JSON → commit

STEP 5  Vapi assistant + tools as JSON
        13 tool definitions + Grace assistant config
        Deploy via CLI/REST, not the dashboard

STEP 6  Integration testing
        vapi listen for local webhook debugging
        Vapi test suites for the 15 top intents
        Load test: 5 concurrent calls hitting checkAvailability

STEP 7  Telephony
        Twilio DID → Vapi SIP; RingCentral forwarding (after-hours first)

STEP 8  Write-path decision gate
        Vagaro approval lands → confirm the endpoint list
        → write endpoints exist?  Track B is deleted, wire the API
        → they don't?             Track A + B ship as designed
```

**Steps 1–3 and 5 require no Vagaro access at all.** The five-day approval wait costs us nothing if sequenced this way.

### 20.5 What still isn't code

Honest scope note — a few things remain manual, one-time, GUI or paperwork steps. No MCP fixes these:

- Vagaro API access request form + approval (5–7 business days)
- Vagaro webhook registration in their settings UI (desktop only — their FAQ confirms the Developers section is not exposed in the mobile app)
- Twilio A2P 10DLC brand and campaign registration
- RingCentral call-forwarding configuration
- OAuth consent grants (Google Calendar, Stripe)
- Vagaro credential retrieval (Client ID, Client Secret, region identifier from the URL bar)

If any of these need automation later, browser-based Claude can drive them — but they are one-time setup, not recurring work, and each should be documented in a runbook rather than automated.

---

## 21. Reference Architecture Analysis

We reviewed the public Vapi + n8n booking implementations. The pattern is consistent and it validates our design.

### 21.1 What the field actually does

| Reference | Booking backend | Notes |
|---|---|---|
| n8n template #8972 — Vapi + Google Calendar | **Google Calendar** | Two tools: `checkAvailability`, `bookAppointment`; Switch node routes on `toolCalls[0].function.name` |
| n8n template #10905 — Vapi + Gemini + Calendar | **Google Calendar** | Availability Checker + Appointment Creator, plus confirmation email |
| n8n template #3427 — Vapi + Calendar + Airtable | **Google Calendar** | Airtable for call logging |
| Vapi + n8n + GoHighLevel | **GoHighLevel CRM** | Uses GHL's write API |
| Clixlogix production receptionist | Vapi + n8n + Groq + Twilio + Google | End-of-call webhook processing |

**Every single public reference implementation books into Google Calendar or a CRM with a documented write API. None of them book into Vagaro, Mindbody, or Booker.** That is not a coincidence — it is the same constraint we hit, and the field has independently converged on the same workaround our Track A uses.

### 21.2 Confirmed conventions we adopt

- Tool names must match the n8n Switch node exactly — a mismatch means nothing runs and the agent goes silent
- Vapi Server Messages should have **only `toolCalls` enabled** for the router workflow; the end-of-call workflow subscribes separately to **only** the end-of-call report
- Production webhook URL, never the test URL
- Sub-800ms is the accepted latency target for voice — matches our §2.3 budget
- Reported containment for this pattern is roughly 65–80% of routine calls, which is the right expectation to set with PalmLeaf (not 100%)

### 21.3 Where we deliberately go further

Public templates are demos. Production for a paying client needs more:

| Template does | We do | Why |
|---|---|---|
| Query Google Calendar live per tool call | Local Postgres availability mirror | Latency + Vagaro rate limits + metered API calls |
| No concurrency control | Slot holds with TTL + unique idempotency key | Two callers, two lines, same second |
| Book directly, hope it works | Hold → async write → retry → staff fallback | Vagaro has no write API; failure must not lose the caller |
| Prompt contains business rules | 48-hour rule and pricing in code | Money decisions don't belong in an LLM |
| Single environment | dev + prod n8n, CI deploy | An agent must not edit the live phone system |
| No compliance layer | IL all-party consent, BIPA, PCI, TCPA | Illinois; healthcare-adjacent; card data |

