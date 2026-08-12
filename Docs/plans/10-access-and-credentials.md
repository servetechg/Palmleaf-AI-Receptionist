# 10 — Access & Credentials We Still Need

**Status:** Active — this is the shopping list
**Read before:** asking the client for anything, or wondering why a workflow says "waiting on configuration".
**Implements:** ADR-0010, ADR-0013
**Enforces:** I9
**Last verified:** 2026-08-05 against the live n8n instance, the live Vapi org, and every `__CRED__:`/`__URL__:`/`__EMAIL__:` placeholder in the repository.

> **In one paragraph:** every remaining piece of work on this system is blocked on access
> somebody has to grant us, not on code somebody has to write. This document lists each one in
> plain terms — what it is, who can give it to us, what it unlocks, and what form the credential
> takes when it arrives. The other planning documents explain *how* each integration works; this
> one answers "what do we need, and from whom".

---

## 1. How to read this

Three kinds of thing appear below, and they behave differently:

| Kind | What it means | Who can supply it |
|---|---|---|
| **Access** | An account, a contract, or a decision from the client or a vendor | PalmLeaf, or a vendor's sales/support |
| **Credential** | A username/password/key pair we create once, by hand, inside a dashboard | Us, once the access exists |
| **Setting** | A value we put in the deploy environment — a URL, a phone number, an email address | Us, once the access exists |

**Nothing here needs new development.** Every integration point is already built and shipped
switched off, which is the deliberate strategy of this phase
([04-n8n-layer](04-n8n-layer.md) §7). When access arrives, the remaining work is creating a
credential and re-running a deploy.

> **Why a workflow says "waiting on configuration".** `deploy.py` refuses to publish a workflow
> whose credential does not exist yet, and names what it is waiting for. That is deliberate: n8n
> would otherwise accept the workflow, activate it, and throw on its first real execution — which
> is the worst possible moment to discover a missing key ([04-n8n-layer](04-n8n-layer.md) §7.2).

---

## 2. The headline — what we are waiting for, by owner

| We need | From | Unlocks | Status |
|---|---|---|---|
| **An email account to send reports from** | PalmLeaf | Every report arriving by email instead of only in a table | ⛔ Waiting |
| **RingCentral forwarding behaviour** | A live test call, not a support ticket | Real calls reaching Grace from the real number | ⚠️ GATE-11 partially cleared — API access granted 6 Aug 2026; forwarding behaviour still unconfirmed |
| **A2P 10DLC brand + campaign** | Twilio | Staff SMS that carriers do not silently filter | ⛔ GATE-09 |
| **Vagaro API access** | Vagaro | Real availability and real bookings | ⛔ GATE-01 |
| **Full service catalogue and prices** | PalmLeaf | Grace quoting any price at all | ⛔ GATE-04 |
| **Approved greeting and provider roster** | PalmLeaf | Production launch | ⛔ GATE-05 |
| **Cancellation policy wording** | PalmLeaf | Grace quoting a cancellation fee | ⛔ GATE-02 |
| **Recording retention period** | PalmLeaf + counsel | Nothing — but the purge job and the privacy notice must agree | ⛔ GATE-06 |
| **A hosted database** | Us — a free tier is enough | Reports surviving longer than n8n's table limits | ⚠️ Unblocked, nobody has done it |

The full gate register, with what each one blocks and what proceeds regardless, is
[09-open-decisions](09-open-decisions.md) §1.

---

## 3. Email — the current focus

**What we are asking for:** an email account Grace can send from, and an address to send to.

Every scheduled report already produces its figures. What is missing is delivery: today a report
lands in a table inside n8n that somebody has to open the dashboard to read. WF-26 sends it by
email instead, and it is built and waiting ([04-n8n-layer](04-n8n-layer.md) §10.5).

### 3.1 What the credential is

n8n needs a standard mail-sending credential — the same five fields any mail program asks for:

| Field | What it is |
|---|---|
| Host | The mail server address, e.g. `smtp.gmail.com` |
| Port | `587` normally, `465` for the older encrypted style |
| User | Usually the full sending address |
| Password | See the warning below — often **not** the account's own password |
| Encryption | On, matching the port |

Created once, by hand, in n8n → **Credentials**, named exactly **`PalmLeaf Email (dev)`**. That
name is not cosmetic: the deploy script looks the credential up by name, so a different name means
the workflow stays blocked ([04-n8n-layer](04-n8n-layer.md) §8).

### 3.2 The warning worth reading before choosing a provider

⚠️ **A normal email password will usually not work.** Mail providers have spent several years
closing off password-based sending by automated systems, and the two most likely accounts both
have a catch:

- **Gmail or Google Workspace** — needs 2-Step Verification switched on and a generated
  **App Password** (a 16-character code). The account's own password is rejected outright.
- **Microsoft 365** — sending by this method is switched **off by default** on newer accounts and
  has to be re-enabled by an administrator, per mailbox. Microsoft has been tightening this
  steadily, so it is not a safe long-term choice for an automated sender.

**Recommendation:** for automated reports specifically, use a service built for it — SendGrid,
Postmark, or Amazon SES all have free or near-free tiers at this volume. They give a stable
credential with no administrator friction, and they handle the sender-reputation records that
decide whether a report lands in the inbox or the spam folder.

⚠️ **Whichever is chosen, the sending domain needs its sender-authentication records published**
(SPF and DKIM, ideally DMARC). Without them a nightly automated report is a textbook spam
signature. This is a DNS change on `palmleafmassage.com`, not a code change, and it needs whoever
administers that domain.

### 3.3 Where the reports go

One setting, `GRACE_REPORTS_EMAIL_TO`, holds the recipient. It is resolved at deploy time, and
**an unset value blocks the deploy rather than defaulting to anything**. That asymmetry is
deliberate: a wrong URL fails loudly and harmlessly, but a wrong email address either reaches a
stranger or is silently accepted and delivered to nobody, which looks identical to success
([04-n8n-layer](04-n8n-layer.md) §10.5).

Which reports email, and which deliberately do not:

| Report | Emails? | Why |
|---|---|---|
| Nightly reconciliation (WF-07) | yes | Once a day |
| Daily call digest (WF-20) | yes | Once a day |
| Weekly QA sample (WF-21) | yes | Once a week |
| Call quality alert (WF-22) | yes — **only when a call is flagged** | A clean hour sends nothing |
| Hourly call digest (WF-11) | **no** | Hourly email is noise; it stays in the table |

---

## 4. Telephony — the phone number

**What we are asking for:** confirmation of how a forward from PalmLeaf's existing number behaves
in practice.

This was the single largest blocker in the system. It is now a smaller one. **RingCentral
developer-platform access was granted on 6 August 2026** — a Private JWT app whose credentials
are in `.env`, reading the live account successfully (`make rc-snapshot`; findings in
`platform/ringcentral/README.md`). The design that follows from it is
[telephony](../reference/telephony.md) §1.1: RingCentral forwards to a Vapi-provisioned 847
number, so no trunk and no porting decision are needed to run the pilot.

What remains open is behavioural, and no support ticket answers it — only a live test call:
what caller ID Grace receives on a forwarded call, how much ring delay the hop adds, and whether
RingCentral voicemail can pick up before the forward completes. The snapshot showed why the
last one cannot be read from configuration: the account's rules declare no ring counts.

| We need | From | Form it takes |
|---|---|---|
| ~~Answer on porting vs forwarding~~ | ~~RingCentral support~~ | Superseded — API access granted; the forward is ours to configure |
| Forwarding behaviour: caller ID, ring delay, voicemail race | A supervised test call | An observation recorded in telephony §1.1 |
| A voice trunk we control | Twilio | An account, then a trunk we configure — **deferred to SMS/porting**, not a pilot prerequisite |
| Brand and campaign registration for staff SMS | Twilio | An application — **1 to 3 weeks of external clock**, so start it early |

⚠️ **Start the SMS registration before it is needed.** Unregistered automated SMS is filtered by
the carriers rather than rejected, so it fails *silently* — and the first place that would bite is
an escalation message to a manager, which is exactly where silence is most expensive. Email is the
fallback until it clears.

Two settings follow once a number exists: `GRACE_TRANSFER_NUMBER` (where Grace transfers a caller
who asks for a person) and `GRACE_MAIN_LINE_NUMBER` (the number she answers on). Until the first
is set, the transfer tool deploys with **no destination at all** rather than a placeholder — an
invalid number would make Grace attempt a real transfer to nowhere in the middle of a call.

---

## 5. The booking system

**What we are asking for:** programmatic access to Vagaro, and the service catalogue.

| We need | From | Why it matters |
|---|---|---|
| Whether the API offers booking and availability, and on what contract | Vagaro Enterprise Sales | Decides an entire implementation path (GATE-01) |
| Rate limits, error codes, token lifetimes, a test account | Vagaro | Tuning; conservative defaults are already in place (GATE-03) |
| Every service, duration, member and non-member price, deposit | PalmLeaf | **Grace cannot quote any price until this exists** (GATE-04) |
| The cutover date from the old booking system | PalmLeaf | The likeliest cause of a customer-visible failure that looks like an AI fault but is an operations one (GATE-12) |

Until the catalogue is approved, prices in the system are placeholders explicitly marked
unapproved, and Grace degrades to transferring rather than quoting a number nobody signed off.

---

## 6. What we already have

Recorded so nobody re-requests it:

| Credential | Where | Covers |
|---|---|---|
| `PalmLeaf Vapi (dev)` | n8n | Every workflow that reads call records |
| `PalmLeaf n8n Inbound (dev)` | n8n | Authenticating the two inbound webhooks — created 5 August 2026 |
| `PalmLeaf Core API (dev)` | n8n | Reserved; holds a placeholder until that service exists |
| Vapi API key | Deploy environment | Deploying the assistant and her tools |
| n8n API key | Deploy environment | Deploying workflows |
| RingCentral Private JWT app | Deploy environment | Reading the live phone account (`make rc-snapshot`) — granted 6 August 2026 |

The RingCentral JWT does not expire in any practical horizon, so there is no refresh mechanism
to maintain; the client secret and JWT live in `.env` only. Rotation is a manual action in the
RingCentral developer console, and re-running `make rc-snapshot` is the test that it worked.

---

## 7. Settings, and when each is needed

**The working copy is `.env.example` in the repository root** — copy it to `.env` and fill in what
you have. Every variable is listed there with what it unlocks and what happens when it is unset. The
Makefile loads `.env` automatically, and `.env` is ignored by git and must never be committed.

Two properties of that file are deliberate and easy to trip over:

- **A value in `.env` overrides the same variable exported in your shell**, including an empty one.
  That is why unset variables are left commented out in the template rather than assigned blank —
  `FOO=` would silently blank a `FOO` you had exported.
- **`make check` runs with no `.env` at all**, which is what CI does. Nothing in the build gate
  needs a secret; only the deploy commands do.

Every value is read at deploy time, never at run time — n8n's hosted service blocks workflows from
reading the environment directly, which is why deploy-time resolution exists at all
([04-n8n-layer](04-n8n-layer.md) §10.5). Changing a value means redeploying for it to take effect.

| Setting | Needed when | If unset |
|---|---|---|
| `GRACE_REPORTS_EMAIL_TO` | Email access arrives | Report email stays undeployed |
| `GRACE_TRANSFER_NUMBER` | A number exists | Transfer tool ships with no destination |
| `GRACE_MAIN_LINE_NUMBER` | A SIP trunk exists | `main.json` skips; the Vapi-native number deploys regardless |
| `GRACE_FRONT_DESK_NUMBER` | A pilot number exists | Grace's number deploys with no fallback destination — a Vapi failure has no human to fall back to |
| `GRACE_RINGCENTRAL_CLIENT_ID` / `_SECRET` / `_JWT` | Reading or changing the phone account | `make rc-snapshot` exits with what is missing |
| `GRACE_PILOT_CALLERS` | Stage A of the pilot | The whitelist rule has no callers to match, so it is not written |
| `GRACE_CORE_API_URL` | That service is built | Workflows record "not yet built" and carry on |
| `GRACE_CRM_WEBHOOK_URL` | The client names a system | The delivery step stays switched off |
| `GRACE_MARKETING_WEBHOOK_URL` | The client names a system | The delivery step stays switched off |

---

## 8. The one thing not blocked on anybody

A hosted database for reports. n8n's own tables work today but are capped and cannot be queried
properly. A free tier from any hosted provider is sufficient, the schema is written, and the
workflow steps are built and switched off. Turning it on is five steps and no redesign
([04-n8n-layer](04-n8n-layer.md) §9).

Nobody has done it because nothing yet breaks without it — worth doing before there is data worth
keeping, not after.

---

## 9. Acceptance criteria

✅ **AC-10.1** Every `__CRED__:` alias in a committed workflow appears in
`platform/n8n/credentials.example.json` with its setup steps.
✅ **AC-10.2** A deploy with a missing credential names what it is waiting for and deploys
everything else, rather than failing wholesale.
✅ **AC-10.3** An unset recipient address blocks the report email from deploying, rather than
resolving to a default.
✅ **AC-10.4** No credential value appears anywhere in the repository — the secret scanner in the
workflow linter is the enforcement.
☐ **AC-10.5** Every row in §2 is either resolved or has a named owner and a date requested.

---

## 10. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-10.1** | Which email service will actually be used? | §3.2 rules out the two most obvious accounts unless someone does administrative work first. A purpose-built sender avoids that entirely, but it is another account for the client to own. | PalmLeaf, with our recommendation |
| **Q-10.2** | Who administers DNS for the sending domain? | Sender-authentication records are a prerequisite for reports reaching an inbox, and they are not something we can add ourselves. | PalmLeaf |
| **Q-10.3** | Who is chasing the client-side gates? | GATE-02, GATE-04, GATE-05 and GATE-12 are all owned by PalmLeaf and all unanswered. [09-open-decisions](09-open-decisions.md) already rates client sign-off dragging past launch as high likelihood. An unowned chase is not a chase. | Commercial |
| **Q-10.4** | Where will the reporting database live? | §8 is unblocked and small, and stays undone because nothing breaks without it yet. | Engineering |
