# Outreach Package — RingCentral & Vagaro
## Ready-to-send questions for PalmLeaf "Grace" AI Receptionist
**Prepared 31 July 2026**

---

# PART 1 — RINGCENTRAL

## 1.1 Where to post

| Channel | URL | Use for |
|---|---|---|
| **Developer Community** (primary) | `https://community.ringcentral.com/` → *Developer Platform, APIs & Integrations* | The technical question below. Free, public, RC developer advocates answer here (PhongVu and colleagues respond to SIP threads). |
| **Ideas portal** (secondary) | `https://ideas.ringcentral.com/` → *Developer Platform, APIs & Integrations* | Upvote the existing SIP-trunking-for-AI-platforms request rather than filing a duplicate. |
| **Partner / Sales** | `https://www.ringcentral.com/` → Contact Sales | Only if the community answer is "partner tier only." Ask for the Channel/Partner team, not general sales. |
| **Support** | 1-888-898-4591 | Account-specific questions (can this number port/forward), not API capability. |

**Posting tips for RC community:**
- Register with the account email tied to PalmLeaf if possible — RC staff sometimes check account tier before answering.
- Post in *Developer Platform, APIs & Integrations*. Posting in general RingEX support gets routed to tier-1 who won't know SIP trunking policy.
- One thread, numbered questions. RC staff answer inline per number. Multiple threads get partial answers.
- Do **not** paste real SIP credentials, passwords, or the full DID.
- Expect 1–3 business days. If no staff reply in 3 days, reply to your own thread with "@PhongVu any guidance here?" — bumping works.

## 1.2 The post — copy from here

**Title:**
`SIP trunking to a third-party voice AI platform (Vapi) — is device registration the only option?`

**Body:**

> **Context**
>
> I'm building an AI voice receptionist for a single-location wellness business that currently runs on RingCentral (RingEX, one main VOIP DID). The AI platform is Vapi, which accepts inbound calls via BYO-SIP: you point a SIP trunk at a dedicated URI in the form `sip:{number}@{credentialId}.sip.vapi.ai`, optionally over TLS on port 5061. Vapi requires a **dedicated termination URI** — their docs state that IP-based auth on a shared URI is unreliable.
>
> I've been provided the standard third-party device SIP credentials from the account (SIP Domain `sip.ringcentral.com:5060`, Outbound Proxy `sip10.ringcentral.com:5090`, SIP ID, password, Authorization ID). My understanding is that these are **registrar** credentials for registering a device *into* RingCentral, not a termination URI for trunking calls *out to* an external platform — different SIP roles.
>
> Before I design around that assumption, I want to confirm it directly, because I've found conflicting information.
>
> **What I've already found in this community**
>
> 1. A thread on connecting Retell's voice agent asked about setting up a termination URI with credential-based auth; the answer was that there's no open/public SIP trunking API, with a referral to partner sales.
> 2. A thread on connecting LiveKit received "we don't open SIP trunk to 3rd party developers," and earlier in the same thread, that SIP device credentials "may not work as a SIP trunk."
> 3. An open Ideas request notes RC SIP endpoints are "designed for device registration only, not for SIP trunking," filed after a customer hit TLS handshake failures (legacy CN field, SAN mismatch) integrating ElevenLabs.
> 4. A thread on `createSIPRegistration` indicated third-party apps are limited to WSS transport, not TCP/TLS/UDP.
>
> **My questions**
>
> 1. Can you confirm that `sip.ringcentral.com` / `sip10.ringcentral.com` third-party device credentials **cannot** be used as a SIP trunk termination point for an external platform like Vapi? I want this stated clearly so I stop trying.
> 2. Is there **any** self-service path on a standard RingEX plan to obtain a dedicated SIP termination URI with credential-based auth, pointed at an external SIP endpoint?
> 3. If SIP trunking is partner-tier only — what exactly is the qualifying tier? Is there a user-count minimum? (I've seen ~20 users mentioned; this business is well under that.) What is the correct team to contact, and what's the typical lead time?
> 4. Is the WSS-only restriction on `createSIPRegistration` still current, or has TLS/TCP registration for third-party apps been added since those threads?
> 5. If the answer to 1–3 is no across the board, is **call forwarding** to an external DID the officially supported pattern for this use case? Any per-account limits on forwarding volume or concurrency I should know about?
> 6. On forwarded calls: is there a supported way to **preserve the original caller's number** when the AI transfers the call back into a RingCentral queue or extension? I've seen reports of the original `From` being replaced by the intermediary number. Is P-Asserted-Identity or Remote-Party-ID honored on inbound?
> 7. Has the SIP-trunking-for-AI-platforms Idea moved on the roadmap? Anything I should design toward for the next 6–12 months?
>
> Happy to move this to a private/account channel if any of it is tier-specific. Thanks.

## 1.3 What each answer changes

| Answer | Impact on the build |
|---|---|
| Q1 confirmed "cannot" | Locks the design — stop pursuing RC credentials, go Twilio Elastic SIP Trunking |
| Q2/Q3 "partner tier, no minimum" | Worth a sales call; could remove the Twilio carrier hop |
| Q3 "20-user minimum" | Ruled out for PalmLeaf — Twilio it is |
| Q5 "forwarding is supported" | Fallback path validated for after-hours-first rollout |
| Q6 "PAI honored" | Human transfer keeps caller ID — meaningful UX gain |
| Q6 "not supported" | Staff will see the Twilio number; pass caller ID in the whisper message instead |

---

# PART 2 — VAGARO

## 2.1 ⚠️ There is no Vagaro developer community

Vagaro has no public developer forum. Your channels are:

| Channel | How | Use for |
|---|---|---|
| **Enterprise Sales** (primary) | `https://www.vagaro.com/pro/contact` · Enterprise line **1-925-515-5055** | The endpoint capability question. Vagaro's own webhooks page directs API/webhook enablement here. |
| **Access request form** | In-app: log in on **desktop** → Settings → Developers → APIs & Webhooks → *Contact Us*. Also linked from the support article. | The formal request. Up to **7 business days**. Desktop only — not in the mobile app. |
| **Support article comments** | `support.vagaro.com` → *Set Up Webhooks From Vagaro* | Public Q&A; this is where the "no create/update appointment API" answer appeared. Slow but on the record. |
| **General support** | `support@vagaro.com` · 1-800-919-0157 | Account/billing prerequisites only. Tier-1 won't know the API roadmap. |

**Approach:** send the email below to Enterprise Sales **first**, then submit the in-app form referencing it. Sales controls provisioning; the form is the paperwork.

**Before you contact them, confirm PalmLeaf meets the prerequisites** — otherwise the request bounces:
- Paid plan, **not** in free trial
- On the computer/tablet/Pay Desk/PayPro version
- **Vagaro Credit Card Processing active** (hard requirement)
- Active billing cycle

## 2.2 The email — copy from here

**To:** Enterprise Sales (via `vagaro.com/pro/contact`, or ask for Enterprise on 1-925-515-5055)
**Subject:** `API endpoint capability confirmation — AI receptionist integration, PalmLeaf Massage & Wellness`

> Hello,
>
> I'm implementing an AI voice receptionist for **PalmLeaf Massage & Wellness** (Buffalo Grove, IL), an existing Vagaro business. The system answers inbound calls and needs to book, reschedule, and cancel appointments directly in Vagaro via your official API. We are not pursuing any workaround — official API only.
>
> Before we build, I need written confirmation of what the API can and cannot do. Your public documentation describes Appointments, Customers, Employees, and Locations as **retrieve** operations, with Employee Management as the only write capability. I could not find endpoints for reading availability or creating appointments, and a support thread indicates appointment create/update is not currently available.
>
> **Please confirm, per line, whether each exists today, can be provisioned for our account, or is not available:**
>
> **A. Availability (highest priority)**
> 1. An endpoint returning **bookable open slots** for a given service and optional provider across a date range — honoring working hours, existing bookings, buffer times, and time off. Without this the project cannot proceed.
>
> **B. Appointment writes**
> 2. **Create** an appointment (service, provider, start time, customer, notes, booking source).
> 3. **Reschedule/update** an existing appointment.
> 4. **Cancel** an appointment with a reason.
> 5. **List** appointments across a date range (not just retrieve by ID).
>
> **C. Customers**
> 6. **Search** a customer by phone number and by email (for caller-ID matching).
> 7. **Create** a customer record.
> 8. **Update** a customer record.
>
> **D. Catalog & scheduling reference data**
> 9. Service catalog with durations, prices, member vs non-member pricing, buffer times, deposit amounts.
> 10. Provider-to-service assignments.
> 11. Provider working schedules, shifts, and time off.
> 12. Business hours and holiday/closure calendar.
>
> **E. Commerce**
> 13. Membership status lookup and member pricing resolution for a customer.
> 14. Deposit/prepayment: charge a card on file, or create a hosted payment link we can send by SMS.
> 15. Apply a payment to an appointment; issue a refund.
> 16. Gift certificate lookup and redemption.
>
> **F. Forms**
> 17. Send an intake form to a customer; check completion status; retrieve responses. (I'm aware of the `formResponse` webhook — I'm asking about the send and status endpoints.)
>
> **G. Technical**
> 18. **Idempotency-Key header support on all write operations.** Critical — without it, a retried request can double-book a client.
> 19. Exact **OAuth2 token endpoint path**, host pattern including the region identifier, token TTL, and refresh flow. Not in the public docs.
> 20. **Numeric rate limits** — requests per second and per minute.
> 21. **Pagination** conventions and **error code** reference.
> 22. Is there a **sandbox or test environment**? If not, what's your recommended approach for testing booking writes without affecting the live calendar?
> 23. Webhook **signature verification** method and verification token handling.
> 24. Does the **$10/month, 5,000 calls, $0.002 overage** pricing cover REST API calls as well as webhook events, or webhooks only?
>
> **Commercial questions**
> 25. If any of the above are not in the standard API, are they available under an **enterprise agreement**? What tier, and at what cost?
> 26. If appointment-write endpoints don't exist today, are they on the roadmap, and on what timeline?
> 27. Is there an official partner or ISV program for AI receptionist integrations?
>
> I'd rather hear a clear "not available" than discover it mid-build. If a call is easier, I'm happy to schedule one.
>
> The business meets the stated prerequisites (paid plan, not in trial, Vagaro Credit Card Processing active). We'll submit the in-app APIs & Webhooks request in parallel.
>
> Thank you,
> [Name] · [Company] · [Phone] · [Email]
> On behalf of PalmLeaf Massage & Wellness

## 2.3 Decision gate

**Question 1 and Questions 2–4 are go/no-go.**

| Vagaro's answer | What happens |
|---|---|
| Availability + create/reschedule/cancel all available | Build proceeds as architected |
| Available under enterprise agreement | Get pricing, present to PalmLeaf as a cost decision |
| Not available, on roadmap | Project pauses or scope drops to answering + qualification + message-taking |
| Not available, not planned | Escalate to PalmLeaf — booking automation on Vagaro is not achievable via official API |

Do not begin work on availability, booking, reschedule, cancel, or deposits until Q1–Q4 are answered **in writing**. Everything else — repo, infra, telephony, assistant, read-only workflows — proceeds in parallel.

---

# PART 3 — TRACKING

| # | Ask | Channel | Sent | Reply | Blocks |
|---|---|---|---|---|---|
| 1 | SIP trunking capability | RC Developer Community | | | Telephony design |
| 2 | Ideas upvote | ideas.ringcentral.com | | | — |
| 3 | Port/forward 847.961.4800 | RC Support 1-888-898-4591 | | | Number strategy |
| 4 | Endpoint capability | Vagaro Enterprise Sales | | | **Entire booking core** |
| 5 | API access request | Vagaro in-app form (desktop) | | | Credentials |
| 6 | Prerequisites check | PalmLeaf / Vagaro Support | | | #5 |
| 7 | A2P 10DLC registration | Twilio | | | SMS |

**Send #4 and #5 today** — the 7-business-day Vagaro clock is the longest pole in the project.
