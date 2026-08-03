# 10 — Telephony & Messaging

**Read before:** Phase D.
**Depends on:** the RingCentral answers in `Docs/PalmLeaf_Outreach_Package.md` Part 1.

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
# TARGET — design brief §3.3, kept verbatim as the reference shape
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
| Caller ID replaced on transfer back into RC | transfer test, ask staff what they see | speak the number in the whisper (§08 §7) |
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
   a staff-accessible endpoint or a Slack command (WF-14).

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

Until `GRACE_SMS_10DLC_READY=true`, the messaging adapter routes to email fallback and logs (§05 §6).

### 4.2 Message templates

All templates live in `message_templates` (§03 §11), are versioned, and require `approved_at`.

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

**TCPA rules baked into the adapter (§05 §6):**
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

## 6. Acceptance criteria (Phase D gate)

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
