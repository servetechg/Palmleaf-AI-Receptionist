# telephony — Telephony & Messaging

**Status:** Frozen except §1.1 (amendment of 5 August 2026) — unblocks when **GATE-09** (A2P 10DLC) clears; **GATE-11** is now partially cleared.
**Read before:** Phase E telephony work.
**Implements:** ADR-0007
**Enforces:** I5, I7
**Last verified:** 2026-08-04 — rewritten for Python; carrier and regulatory content is unchanged and was never language-specific.

> **In one paragraph:** this document settles how a phone call physically reaches Grace and how
> messages leave her — the SIP trunk, number porting and forwarding, A2P 10DLC registration, and
> the SMS templates with their consent and opt-out enforcement. It deliberately does **not** cover
> the conversation itself, which is [03-vapi-layer](../plans/03-vapi-layer.md).

---

## 1. The settled position

The design brief §3.2 establishes, with sources, that RingCentral's third-party SIP credentials are
**device registration credentials, not a trunk termination URI**. Nothing in this plan attempts to use
them as a trunk. The carrier is Twilio.

```
Caller
  │
  ▼
847.961.4800  (PalmLeaf's existing RingCentral DID)
  │  Phase D-1: unconditional/after-hours forward   ← reversible in 30 seconds
  │  Phase F  : optional port to Twilio             ← only after the pilot proves out
  ▼
Twilio DID  →  Twilio Elastic SIP Trunk (dedicated termination URI, TLS 5061, SRTP)
  │
  ▼
sip:{number}@{credentialId}.sip.vapi.ai
  │
  ▼
Vapi assistant "Grace"
```

**Forward first, port later.** Forwarding costs one extra hop (~50–150ms) and buys an instant, no-support-ticket
rollback: disable the forward and calls go back to staff. Porting removes the hop but makes rollback a
multi-day carrier operation. During a pilot on a client's only business line, reversibility is worth
150ms. Revisit after 60 days of clean operation.

### 1.1 Amendment — 5 August 2026: Vapi-native pilot

Nothing above is withdrawn. What changes is the *order*: the Twilio leg is no longer a pilot
prerequisite, and the pilot's Grace-side number is provisioned by Vapi instead.

**GATE-11 is partially cleared.** RingCentral developer-platform API access is granted — a
Private JWT app, credentials in `.env`, reads confirmed working against the production platform
on 6 August 2026 (`make rc-snapshot`, `platform/ringcentral/README.md`). What is *not* yet
confirmed is the behaviour of a forward: caller ID presentation, added ring delay, and whether
voicemail can race the forward are empirical questions that only a live test call answers.
Two findings from the snapshot bear on the design directly: the account's routing lives in
**company-level** answering rules (the per-extension API is closed by the
`NewCallHandlingAndForwarding` feature), and no rule declares ring counts, so the timing that
decides the voicemail race sits in the IVR menus each rule hands off to.

**The pilot path.** RingCentral forwards to a **Vapi-native number** (`provider: "vapi"`,
`numberDesiredAreaCode: "847"`, free, provisioned through `platform/vapi/phone-numbers/`).
To RingCentral that is an ordinary forwarding target; no trunk is involved. Twilio moves from
"pilot prerequisite" to "**Phase F / SMS prerequisite**" — it becomes necessary for SMS
(GATE-09) or a decision to port the number to a production carrier. §2 of this document
remains the build sheet for that day, unchanged and still valid.

**Staged rollout, each stage a strictly larger blast radius and individually reversible.**

| Stage | RingCentral change | Who can reach Grace |
|---|---|---|
| A | one custom rule `grace-pilot-whitelist`, condition = our own caller IDs | only us |
| B | `grace-pilot-after-hours`, schedule outside business hours | evening callers |
| C | daytime overflow — staff ring N seconds, no answer → Grace | overflow callers |
| D | unconditional | everyone |

The account's own `business-hours-rule` and `after-hours-rule` are **never edited** in Stages
A–B; only rules named `grace-*` are ever created, enabled or disabled, and write code hard-exits
rather than touch anything else. Stage C is gated on a hosted tool endpoint replacing the local
tunnel, because unattended customer traffic must not depend on a laptop process. Stage D is a
business decision recorded in [09-open-decisions](../plans/09-open-decisions.md), not an
engineering default.

**The kill switch design in §3.1 is unchanged** — two independent layers, one of which
(the manager's manual RingCentral-admin procedure) does not depend on our stack at all. The API
half gains a command, `make rc-kill`, which disables every `grace-*` rule in one call.

---

## 2. Twilio Elastic SIP Trunk setup

Order of operations — each step is verifiable before the next.

| # | Step | Verify |
|---|---|---|
| 1 | Buy a Twilio DID in the 847 area code (local presence) | number visible in console |
| 2 | Create an Elastic SIP Trunk | trunk SID recorded in `infra/terraform/` state |
| 3 | Termination: set a unique `<something>.pstn.twilio.com` URI; enable **credential list** auth (not IP-only) | SIP OPTIONS ping succeeds |
| 4 | Termination: enable **Secure Trunking** (TLS + SRTP) | handshake succeeds on 5061 |
| 5 | Origination: add origination URI → `sip:{number}@{credentialId}.sip.vapi.ai;transport=tls` | Vapi receives INVITE |
| 6 | Assign the DID to the trunk | inbound test call reaches Vapi |
| 7 | Vapi: create BYO-SIP credential (`POST /credential`) with Twilio's gateway IPs, `inboundEnabled: true` | credential id returned |
| 8 | Vapi: bind the number (`POST /phone-number`, `provider: byo-phone-number`) | number listed |
| 9 | Test call from a mobile → Grace answers | full-duplex audio, no one-way audio |
| 10 | Test transfer → RingCentral extension | audio path holds; note what caller ID staff see |

```bash
#: TARGET — design brief §3.3, kept verbatim as the reference shape
POST https://api.vapi.ai/credential
{
  "provider": "byo-sip-trunk",
  "name": "PalmLeaf Trunk",
  "gateways": [{ "ip": "<Twilio termination gateway>", "inboundEnabled": true }],
  "outboundLeadingPlusEnabled": true,
  "outboundAuthenticationPlan": { "authUsername": "USER", "authPassword": "PASS" }
}

POST https://api.vapi.ai/phone-number
{ "provider": "byo-phone-number", "number": "+1847XXXXXXX", "credentialId": "<id>" }
```

**Vapi requires a dedicated termination URI** — IP auth on a shared URI is documented as unreliable
(design brief §3.3). Twilio's Elastic SIP Trunking provides exactly that, which is why it is the carrier
of record here.

### 2.1 Known gotchas to test explicitly

| Gotcha | Test | Mitigation if it bites |
|---|---|---|
| One-way audio (NAT/SRTP mismatch) | 3-minute call, both directions | force SRTP both legs; check media region |
| Caller ID replaced on transfer back into RC | transfer test, ask staff what they see | speak the number in the whisper ([03-vapi-layer](../plans/03-vapi-layer.md) §7) |
| DTMF not passing | press digits during a call | RFC 2833 vs. inband — set explicitly |
| Codec mismatch / transcoding artifacts | listen for robotic audio | pin to PCMU/PCMA |
| Call drops at N minutes | 15-minute test call | session timers / re-INVITE handling |
| International/toll-fraud exposure | — | disable international termination on the trunk |

Record the results of every one of these in `docs/runbooks/telephony-acceptance.md`. They are the
evidence that the line is safe to point a client's business at.

---

## 3. RingCentral configuration

Two modes, selected by rollout phase:

| Mode | Config | Used in |
|---|---|---|
| **After-hours only** | RC business-hours rule: outside 08:00–20:30 → forward to Twilio DID | Phase D-1 (design brief Phase 1) |
| **Overflow** | Ring staff N seconds → no answer → forward to Twilio DID | Phase D-2 |
| **Primary** | Unconditional forward; staff line becomes the escalation target | Phase D-3 / E |

### 3.1 The kill switch (design brief §12.1)

**Requirement:** one action, performed by PalmLeaf's manager, with no developer involvement, that sends
all calls back to staff.

Implementation — two independent layers, because a single kill switch that depends on our system is not
a kill switch:

1. **Carrier layer (primary).** A documented, screenshotted, 4-step procedure in the RingCentral admin to
   disable the forwarding rule. Laminated card at the front desk. **Tested during Phase D acceptance with
   the manager physically performing it.**
2. **Application layer (secondary).** `tenants.settings.killSwitch = true` → Core API returns a
   `transferToHuman` destination on the very first tool call, and `/readyz` reports the flag. Toggled by
   a staff-accessible endpoint. *(A chat-platform command was planned as WF-14 and withdrawn.)*

Layer 1 works even if our entire infrastructure is down. That is the point.

⛔ **GATE-11:** confirm with RingCentral (Outreach Q5) whether forwarding has per-account concurrency or
volume limits. At 45 calls/day this is almost certainly a non-issue, but "almost certainly" is not an
answer to give a client about their only phone line.

---

## 4. SMS — Twilio Programmable Messaging

Booking confirmations, deposit links, intake links and reminders go over Twilio, not RingCentral
(design brief §3.5).

### 4.1 A2P 10DLC — start on day one

⛔ **GATE-09.** Brand + campaign registration takes 1–3 weeks and must complete before production volume.
Unregistered traffic is filtered by carriers, silently.

| Step | Owner | Lead time |
|---|---|---|
| Collect PalmLeaf's legal entity details, EIN, website, address | client | days |
| Register Brand (Standard) | us | 1–3 days |
| Register Campaign — use case **Customer Care / Account Notification**, **not** Marketing | us | 3–10 days |
| Provide sample messages (must match what we actually send) | us | — |
| Attach the Messaging Service and number | us | minutes |
| Verify throughput tier assigned | us | — |

**Sample messages submitted must be the real templates**, including the opt-out language. A campaign
registered with mismatched samples gets flagged later.

Until `GRACE_SMS_10DLC_READY=true`, the messaging adapter routes to email fallback and logs ([provider-adapters](provider-adapters.md) §6).

### 4.2 Message templates

All templates live in `message_templates` ([data-model](data-model.md) §11), are versioned, and require `approved_at`.

| Key | Category | Body (draft — client approval required) |
|---|---|---|
| `booking_confirmation` | TRANSACTIONAL | `PalmLeaf Massage & Wellness: You're booked for {{service}} with {{provider}} on {{date}} at {{time}}. Reply STOP to opt out, HELP for help.` |
| `deposit_link` | TRANSACTIONAL | `PalmLeaf: To hold your {{date}} {{time}} appointment, please complete the room reservation deposit: {{link}} (expires in 24h). Reply STOP to opt out.` |
| `intake_form` | TRANSACTIONAL | `PalmLeaf: Please complete your intake form before your visit: {{link}}. Reply STOP to opt out.` |
| `deposit_reminder` | TRANSACTIONAL | `PalmLeaf: Your {{date}} {{time}} slot is held for a little longer — deposit here: {{link}}` |
| `slot_released` | TRANSACTIONAL | `PalmLeaf: We weren't able to hold {{date}} {{time}} without the deposit. Call us at {{phone}} and we'll find you another time.` |
| `cancellation_confirmed` | TRANSACTIONAL | `PalmLeaf: Your {{date}} {{time}} appointment is cancelled. {{policyNote}}` |
| `reschedule_confirmed` | TRANSACTIONAL | `PalmLeaf: Moved to {{date}} at {{time}} with {{provider}}.` |
| `self_serve_link` | TRANSACTIONAL | `PalmLeaf: Here's your booking link for {{service}}: {{link}}. The time isn't held until you finish — see you soon!` |
| `staff_message_ack` | TRANSACTIONAL | `PalmLeaf: Thanks — we have your message and someone will call you back by {{callbackBy}}.` |

**TCPA rules baked into the adapter ([provider-adapters](provider-adapters.md) §6):**
- Business name in every message ✅ (all templates above)
- STOP/HELP language on the first message to any recipient ✅
- Transactional only. **No marketing** without separate express written consent (design brief §11.4).
- Opt-out is immediate and permanent until re-consent, recorded in `consent_log`.
- Quiet hours: no non-urgent SMS 21:00–08:00 local. Deposit links sent during a call are exempt
  (the caller just asked for them); reminders are not.

### 4.3 Inbound SMS handling

`POST /webhooks/twilio/inbound` handles:
- `STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT` → set `sms_opt_out_at`, log consent revocation
- `START`, `UNSTOP`, `YES` → clear opt-out, log consent
- `HELP`, `INFO` → auto-reply with business name, contact, and opt-out instructions
- Anything else → create a P3 `staff_tasks` row. **A human replies.** Grace does not run an SMS
  conversation in Phase A–E; that is a separate product decision with its own consent implications.

---

## 5. Number strategy summary

| Number | Role | Owner |
|---|---|---|
| 847.961.4800 | Public business number, on marketing, Google, the door | RingCentral (PalmLeaf) |
| Twilio DID (847) | Grace's inbound endpoint; never published | us |
| Twilio Messaging Service number | SMS sender; should be a number PalmLeaf recognises | us |
| Manager mobile | P1 escalation target | PalmLeaf |
| Front-desk extension | Warm-transfer target | RingCentral |

⚠️ SMS goes out from a Twilio number, but the caller's mental model is "PalmLeaf texted me." Every
template therefore leads with the business name, and the front desk must be briefed that clients may
reference a text from an unfamiliar number. Consider printing the SMS number on the confirmation.

---

## 6. Acceptance criteria

✅ **AC-10.1** Inbound call to the Twilio DID reaches Grace with clean two-way audio for 5 minutes.
✅ **AC-10.2** Inbound call to 847.961.4800 outside business hours reaches Grace; inside hours reaches staff.
✅ **AC-10.3** Warm transfer to the front-desk extension connects, with the whisper message audible to
staff only.
✅ **AC-10.4** The caller ID staff see on a transfer is documented (whatever it turns out to be).
✅ **AC-10.5** The manager performs the carrier kill switch unassisted, timed, and calls route to staff
within 60 seconds.
✅ **AC-10.6** A2P 10DLC campaign status is `VERIFIED` before any production SMS.
✅ **AC-10.7** `STOP` from a test handset suppresses all further SMS to that number, verified by a
follow-up send attempt that is refused by the adapter.
✅ **AC-10.8** Every template renders with all variables populated and no `{{...}}` leakage, verified by
a snapshot test.
✅ **AC-10.9** Toll-fraud protections confirmed: international termination disabled on the trunk.

## 7. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **GATE-11** | Can 847.961.4800 be ported or forwarded? What are the forwarding concurrency limits? Is caller ID preserved on transfer back? | Decides the final telephony topology. The Twilio trunk build proceeds regardless, so this blocks the cutover rather than the work. | RingCentral |
| **GATE-09** | A2P 10DLC brand and campaign verification | **1–3 weeks of external clock**, and unregistered traffic is carrier-filtered — which fails silently, exactly where an escalation SMS matters most. Start it early; email is the fallback in the meantime. | Twilio |
| **GATE-12** | The Massagebook → Vagaro cutover date | The most likely cause of a customer-visible failure that looks like an AI bug but is an operations problem. Push for a hard date before any daytime rollout. | PalmLeaf |
| **A-14** | Does `transferCall` work on web calls, or only PSTN? | Web calls are the only test channel until a number exists, so if transfer is PSTN-only the entire escalation path stays unverified until Phase E. | Engineering, early |
| **A-15** | What ring timeout does the warm-transfer mode use, and is it configurable? | A caller waiting on a silent line when nobody picks up is precisely the failure escalation exists to prevent. | Engineering, once a number exists |
