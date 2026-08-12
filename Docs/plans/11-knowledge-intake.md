# 11 — Knowledge Intake & Decision Pack

**Status:** Active
**Read before:** any conversation with PalmLeaf about content, policy or scope — and before editing `platform/knowledge/palmleaf.yaml` or `grace_db/seeds.py`.
**Implements:** the sign-off half of GATE-02, GATE-04, GATE-05, GATE-06, GATE-08, GATE-12
**Enforces:** I4, I5, I6, I7
**Last verified:** 2026-08-10 against `platform/knowledge/palmleaf.yaml`, `src/grace_contracts/tools/`, `src/grace_api/handlers.py`, `src/grace_db/seeds.py` and [reference/data-model](../reference/data-model.md).

> **In one paragraph:** this document is two things bound together. **Part one (§4–§16)** is the
> complete content-collection instrument for PalmLeaf — every fact Grace needs, in the exact shape
> the system stores it, with the consequence of each blank stated up front. It replaces the generic
> chatbot questionnaire, which was written for a text widget with no calendar, no money and no
> medical exposure. **Part two (§17–§21)** is every question this project still has to ask: of the
> client, of ourselves, and of the architecture — including the decisions we have already taken
> unilaterally and now need confirmed. It deliberately contains **no design**; where an answer
> changes a design, it names the document that owns it.

---

## 1. Why the generic template does not fit

The sample intake we have used on other accounts collects seven things: business info, a product
table, an FAQ list, four policy paragraphs, support contacts, a personality block, and a list of
banned topics. It is a good instrument for a chat widget that answers questions and hands off.

Grace is not that. She answers a phone in Illinois, holds a slot in a shared calendar, quotes money,
takes a medical screening question, and triggers a payment link. Six categories of requirement have
no home in the generic form:

| Generic form assumes | This build actually needs | Where it lands |
|---|---|---|
| Answers are **read**. Prices can be `1,099`, hours `11:30AM-4AM` | Answers are **spoken**. `one thirty-five`, `eight thirty at night`. Digits and symbols make speech engines stumble | `knowledge_entries.answer_spoken`, and the number rules in `prompts/sections/10-style.md` |
| One flat FAQ table | Facts are **typed records** with different lifecycles — a price syncs from a booking system, a policy is signed off once, an answer is edited weekly | `services`, `policies`, `knowledge_entries` — three tables, three approval paths |
| Content is either present or absent | Content is present, absent, **or present-but-unapproved**. Unapproved is treated as absent and Grace offers a person | `approved_at` on services, policies, knowledge, templates |
| Products are a price list | A service is a price **plus** a duration, two buffers, a deposit rule, a lead time, an advance limit, a room requirement and a list of who can perform it | `services` — 21 columns, [reference/data-model](../reference/data-model.md) §4 |
| Support is an email and a phone number | Escalation is a transfer target, a ring timeout, a whisper sentence, a voicemail fallback, a paging mobile and an acknowledgement SLA | `tenants.settings`, `staff_tasks`, WF-12 / WF-18 |
| "Topics to avoid" | A medical screening gate that must fire before every booking, must record a boolean and nothing else, and must never be answered by the model | `flagMedicalHold`, invariant I6 |

And one thing the generic form cannot express at all: **who said so, and when.** The original
PalmLeaf questionnaire was answered by four people, two of whom left every field blank, and it
contradicts itself on the cancellation fee. Grace can hold exactly one policy. Every field in this
document therefore carries an owner and a date, and nothing without both reaches a caller.

---

## 2. How to run the intake

**One respondent with authority.** Not four. Name a single person at PalmLeaf who can commit to a
policy, and a single deputy. Everything else routes through them, however many people contribute the
raw material.

> **The client never sees this document.** What goes to PalmLeaf is
> [`Docs/PalmLeaf_Client_Form.md`](../PalmLeaf_Client_Form.md) — the same ground as §4–§16 and the
> answerable parts of §17 and §19, as **216 written-answer questions in 25 sections**. It carries no
> tick boxes at all, by design: a multiple choice lets the respondent pick the nearest option and
> lets us infer the rest, and inference is what produced the four-respondent contradiction in the
> first place. Every question instead states why it is asked and lists the points a complete answer
> must cover, so the client is prompted through the details that only surface on a real call.
> Section 21 is pure harvesting — twenty-two real caller questions with the answer left blank.
> Every question traces back to a field here; when the form returns, this document is how you turn
> it into rows.

**Three collection modes, in decreasing order of reliability:**

1. **System export.** Service catalogue, provider roster, shifts, and closure calendar should come
   out of Vagaro as a file, not out of a person as a sentence. Ask for the export first, every time.
2. **Structured form.** Sections §4–§14 below, answered field by field.
3. **Recorded conversation.** For §8 (policies) and §17 (scope), where the useful answer is usually
   the second sentence, not the first. Send the questions in advance; record with consent; we write
   the answer down and they approve the wording.

**Source precedence, when two sources disagree** — this rule is already live at the top of
`platform/knowledge/palmleaf.yaml` and should not be relaxed:

> The **website wins** over a verbal answer. It is what the caller has already read, and quoting
> someone something softer than the published policy is how a dispute starts. A **signed-off written
> answer** from the named owner beats the website. A Vagaro export beats both on catalogue data —
> prices, durations and staff — because that is the system that will take the money.

**Sign-off is a data edit, not a deploy.** Approving a knowledge answer is `approved: true` in the
YAML plus `make kb-apply`. Approving a service is one `UPDATE`. Approving a policy is one row.
Nobody needs a release to change what Grace says, which is exactly why the approval flag must be
treated as a signature and not a formality.

**Suggested sessions:**

| Session | Length | Covers | Who from PalmLeaf |
|---|---|---|---|
| 1 — Facts | 60 min | §4 identity, §5 hours, §7 team, §14 systems | Owner + front-desk lead |
| Async | — | §6 catalogue export, §7 roster export, §5 closure calendar | Whoever administers Vagaro |
| 2 — Money & risk | 60 min | §8 policies, §9 medical, §13 compliance | Owner, with the bookkeeper on the phone for §8 |
| 3 — Voice | 45 min | §10 persona, §11 messaging, §12 escalation | Owner + front-desk lead |
| Sign-off | 30 min | §16 checklist, countersigned | Owner |

---

## 3. Where every answer lands

Nothing in this document is collected for its own sake. Each section maps to a storage surface, a
tool that reads it, and a defined behaviour when it is missing. This table is the contract; the
per-section tables below repeat the relevant row so a reader never has to hold two places at once.

| § | Section | Storage | Read by | If missing or unapproved |
|---|---|---|---|---|
| §4 | Identity & reachability | `knowledge_entries` (`location`, `contact`, `parking`), `tenants` | `getBusinessInfo` | Grace: "let me have the front desk confirm" → callback or transfer |
| §5 | Hours & calendar | `business_hours`, `schedule_exceptions`, `knowledge_entries.hours` | `getBusinessInfo`, `checkAvailability` | Hours answer withheld; availability silently wrong if closures are absent — **the dangerous one** |
| §6 | Services & pricing | `services`, `provider_services` | `getServicesAndPricing`, `checkAvailability`, `createBooking` | `approved_at IS NULL` ⇒ no price quoted, no booking taken |
| §7 | Team & rooms | `providers`, `provider_shifts`, `resources` | `checkAvailability` | No named-therapist requests; `speakProviderNames: false` hides names entirely |
| §8 | Policies & money | `policies` (6 keys) | `cancelAppointment`, `rescheduleAppointment`, `getBusinessInfo` | `FeeReason.POLICY_UNAPPROVED` — Grace cannot state a fee, so she cannot complete the change |
| §9 | Medical screening | Prompt + `flagMedicalHold` + `customers.medical_hold` | Every booking | Booking is refused server-side unless `medical_screen_passed` is true |
| §10 | Persona & wording | `prompts/sections/*.md`, `first-message.txt` | The assistant itself | Ships with our recommended wording; the recording disclosure is CI-enforced (I7) |
| §11 | Messaging & consent | `message_templates`, `consent_log` | `sendIntakeForm`, `sendDepositLink`, `sendBookingConfirmation` | Degrades to email, then to `no_contact_method`; never silently drops |
| §12 | Escalation & SLA | `tenants.settings`, `staff_tasks`, WF-12/WF-18 | `flagEscalation`, `transferToHuman`, `takeMessage` | Transfer has no destination — the single worst failure on this list |
| §13 | Compliance & retention | `tenants.settings.recordingRetentionDays`, `calls.recording_expires_at` | Retention job | Defaults to 90 days, unratified |
| §14 | Systems of record | Adapter config, GATE-01/10/12 | Sync, Track A/B | Booking write path stays on Track C |

**Format rules that apply to every field.** These are not stylistic preferences; each one has a
failure attached.

- **Spoken text** is what Grace says. Two short sentences, no digits, no symbols, no URLs, no
  abbreviations. `"eight thirty at night"`, not `"8:30 PM"`.
- **Data values** are machine form: times `HH:MM` 24-hour local, dates `YYYY-MM-DD`, phone numbers
  **E.164** (`+18479614800`), money in **integer cents** (`11500`), durations in whole minutes.
- **Never both in one field.** A price that appears in spoken text will drift out of step with the
  booking system the first time it changes. Prices are quoted from `services` only — this is why
  `knowledge_entries` answers are forbidden from containing them, with the deliberate exception of
  the membership rates, which are a marketing claim rather than a bookable price.
- Every field carries **owner** and **date**. An unattributed answer is not signed off.

---

## 4. Section A — Identity and reachability

| Field | Format | Why it matters | Status today |
|---|---|---|---|
| Legal name | text | Contracts, SMS sender identity (TCPA requires the business name in the message body) | "PalmLeaf Massage & Wellness" |
| Spoken name | spoken | What Grace says in the first three seconds. Confirm the stress: *PALM-leaf*, one word or two | assumed |
| Full address incl. unit | text | Read aloud, and used in confirmation texts | 400 W. Dundee Rd, Unit 8, Buffalo Grove, IL 60089 |
| Address, spoken form | spoken | "four hundred West Dundee Road, Unit eight" | ✅ approved |
| Landmarks, in the order a driver meets them | spoken | The single most common non-booking question after hours | ✅ approved (Old National Bank, Kingswood church) |
| Which door / how to find Unit 8 | spoken | A strip-mall unit number is not enough at night. Is the entrance on Dundee or round the back? | ❌ **missing** |
| Parking specifics | spoken | Free — but is any of it accessible, and is it shared with the bank? | partial |
| Accessibility | spoken | Step-free entry? Table height? A wheelchair user asking this and getting "let me check" is a poor first impression | ❌ **missing** |
| Timezone | IANA | Every timestamp resolves against it | `America/Chicago` |
| Main published number | E.164 | Caller ID, callback promises | +18479614800 |
| Number Grace answers on | E.164 | May differ during the forwarding phase | GATE-11 |
| Website | URL | **Never spoken.** Used in SMS and email only | palmleafmassage.com |
| Second location? | yes/no | Changes the whole tenancy story if yes | assumed no — **confirm** |
| Booking-page URL for Track C | URL | The SMS deflection path depends on a pre-fillable link | ❌ **missing** |

**Edge cases to resolve here, not later:**

- A caller says "is this the place next to the Fifth Third?" — Grace has landmarks in one fixed
  sentence and cannot answer a landmark she was not given. List every landmark worth naming.
- A caller asks for the fax number, the owner's email, or the corporate address. Decide: answer, or
  take a message. Default is take a message.
- A caller asks "do you have another location closer to me?" Confirm the answer is a clean no.

---

## 5. Section B — Hours, calendar and closures

Grace currently believes the business is open **08:00–20:30, seven days a week, holidays included**,
seeded from the client's own hours. Two things about that are unverified and both are load-bearing.

| Field | Format | Why | Status |
|---|---|---|---|
| Opening hours per weekday | `HH:MM`–`HH:MM` × 7 | `business_hours`; the availability grid is generated from it | seeded 08:00–20:30 daily |
| Hours, spoken | spoken | `getBusinessInfo(hours)` | ✅ approved |
| **Last bookable start** per service length | derived or explicit | The engine subtracts the service duration from closing, so a 120-minute massage stops being offered at 18:30. **Does the therapist actually stay until 20:30 for a session that ends then, given a 15-minute turnover buffer runs past close?** | ⚠️ assumed |
| Do the phones ring outside opening hours | yes/no | Grace answers 24/7; the business does not. What she says at 03:00 differs | ❌ **missing** |
| Holiday policy | list of dates | "Open, holidays included" was stated. Christmas Day? Thanksgiving? | ⚠️ claimed, not enumerated |
| Closure calendar, next 12 months | `YYYY-MM-DD` + reason | `schedule_exceptions`. **A missing closure means Grace books a client into a closed salon** | ❌ **missing** |
| Same-day booking allowed? | yes/no + `min_lead_time_min` | Default is 120 minutes' notice | ⚠️ default |
| How far ahead may a caller book | days | `max_advance_days`, default 90 | ⚠️ default |
| Weather / emergency closure procedure | text | Who tells us, how fast, and does Grace stop booking or start apologising | ❌ **missing** |
| Staff lunch / break blocks | per provider | Otherwise offered as availability | ❌ **missing** |

**Edge cases:**

- 20:25 on a Tuesday, caller asks "can I come in now?" Grace has no walk-in concept. Decide the
  answer: refuse politely, offer the first slot tomorrow, or transfer.
- The Sunday of a holiday weekend. Which rule wins — the weekday row or the exception row? (The
  exception row does; confirm the client understands that is how it will behave.)
- Daylight-saving transitions. Handled by storing UTC and rendering local, but a 02:30 appointment
  on the spring-forward date should simply never be offered. Confirm nobody books at 02:30 anyway.
- "Are you open right now?" at 07:55. Grace answers from the hours entry, which is a fixed sentence
  and does not know the current time. If the client wants a live open/closed answer, that is a new
  field on `getBusinessInfo`, not a knowledge edit.

---

## 6. Section C — Service catalogue

This is the largest gap in the project and the one that gates revenue. GATE-04.

**What exists today.** Three rows, seeded from palmleafmassage.com on 8 August 2026: 60-minute
($115 / $90 member), 90-minute ($160 / $135), 120-minute ($230 / $205). Twelve massage modalities —
deep tissue, Swedish, prenatal, postnatal, sports, Thai, myofascial, trigger point, lymphatic, Reiki,
meridian, FOHOW — are carried as **aliases** of the duration rows rather than as separate services,
because they share one price list. That is the right modelling choice and should be confirmed, not
revisited.

**Required per service.** Every column below has a caller-visible consequence; none is optional.

| Column | Format | What breaks without it |
|---|---|---|
| `code` | snake_case | The identifier Grace passes between tools |
| `display_name` / `spoken_name` | text / spoken | Confirmation texts vs what she says aloud |
| `aliases` | list | "deep tissue" fails to match and the caller is told we do not offer it |
| `duration_min` | minutes | The slot grid, and the last-bookable-start calculation |
| `buffer_before_min` / `buffer_after_min` | minutes | Room turnover. Default is 0 / 15. **Confirm 15 is real** — it is the difference between eight and nine sessions in a therapist's day |
| `price_nonmember_cents` / `price_member_cents` | cents | The quote |
| `deposit_cents` or `deposit_percent_bp` | cents / basis points | Never specified by anyone, on any document, at any point |
| `requires_intake` | bool | Whether `sendIntakeForm` fires |
| `bookable_by_ai` | bool | Per-service kill switch — the mechanism for "Grace may quote acupuncture but not book it" |
| `min_lead_time_min` / `max_advance_days` | minutes / days | Same-day and far-future behaviour |
| `requires_resource_kind` | text | Cryo needs the machine; couples needs the double room |
| Provider eligibility | list | Who can actually perform it |

**Services PalmLeaf advertises that Grace cannot currently handle at all:**

| Service | Advertised | In the catalogue | Decision needed |
|---|---|---|---|
| Acupuncture | ✅ (Samantha Brodersen, L.Ac.) | ❌ | Quote-and-transfer, or full booking? Durations and prices? |
| Chiropractic | ✅ (Dr. Eumi A. Chang, D.C.) | ❌ | Same — and note a chiropractic call is far more likely to open with a medical disclosure |
| Cryo body sculpting | ✅ | ❌ | Needs a `resources` row for the machine, not just a provider |
| Skin health | ✅ | ❌ | Is this still offered? |
| Membership add-on rates for the above | ✅ claimed | ❌ | The membership answer promises member rates on four services we cannot price |

That last row is live and speaking to callers today: the approved memberships answer offers member
rates while three of the four services it covers have no price in the system. A caller who accepts
that offer hits a dead end.

**Also missing, and each is a real inbound call:**

- **Couples massage.** Two providers, one double room, same start time. This is a genuinely
  different availability query — `checkAvailability` accepts `party_size` up to 4 but the engine
  computes single-subject slots. Do they offer it? If yes, it is engineering work, not a data entry.
- **Packages and series** — "I bought a five-pack, how many do I have left?" No tool, no table.
- **Gift certificates** — currently a hard escalation, which is correct if they are rare and wrong
  if December is a third of the volume.
- **Add-ons** — hot stone, cupping, CBD oil, aromatherapy, extended-time upgrades. Priced how,
  bookable how, and do they change the duration?
- **First-visit or promotional pricing**, and whether Grace may mention it unprompted.
- **Membership mechanics** — the $49 enrolment, what happens when a member books more than their
  monthly allowance, whether a member can use their rate for a guest, and whether Grace may sell a
  membership on the phone (today she cannot).
- **HSA / FSA payment and superbills.** Common in massage; entirely absent from the design.
- **Tipping.** The single most common "small" question at a massage business, and Grace has no
  answer for it.

⚠️ **Verify before anything else in this section.** `seeds.py` inserts all three services with
`approved_at = now()`, while its own docstring and its completion message both say the rows ship
with `approved_at = NULL` pending GATE-04. The code is what runs: **Grace can quote those
non-member prices to a caller today.** Either they are genuinely approved — in which case the
docstring and the printed message are stale and should be corrected — or they are placeholders
that are live by accident. Resolve this before the first production call, not after.

---

## 7. Section D — Team and rooms

Fourteen licensed massage therapists are seeded by first name from the public staff page, and
`speakProviderNames` is **true**, so Grace will say those names aloud to real callers.

| Field | Format | Why | Status |
|---|---|---|---|
| Display name / spoken name | text / spoken | "Aleksandr" is seeded as "Aleks" aloud — confirm each therapist is happy with the short form | ⚠️ inferred from a web page |
| Pronunciation guidance | text | Kaori, Iryna, Katerina, Aleksandr. Mispronouncing a therapist's name on every call is a small, constant embarrassment | ❌ **missing** |
| Still employed? | bool | A public staff page is not a payroll record. **Confirm all fourteen, by name** | ❌ **unverified** |
| Services each can perform | list | Currently every provider is assigned every service, which is certainly wrong once acupuncture and cryo exist | ⚠️ blanket assumption |
| Working shifts per weekday | `HH:MM`–`HH:MM` | Currently every therapist is seeded as working every day 08:00–20:30 — **fourteen people, ninety hours a week each.** Availability is therefore fiction until real shifts arrive | ❌ **the single biggest data lie in the system** |
| Time off, next 90 days | dates | `schedule_exceptions` | ❌ **missing** |
| `accepts_new_clients` | bool | Some therapists are fully booked with regulars | ❌ **missing** |
| Gender | enum | **Callers request this constantly at a massage business** and there is no field for it, no tool parameter, and no prompt rule. Decide the policy before deciding the schema | ❌ **missing** |
| Languages spoken | list | The roster suggests Russian, Ukrainian, Japanese and Spanish may be available. A caller who can be matched to a therapist in their language is a retained caller | ❌ **missing** |
| Modality specialisms | text | Grace currently says everyone does everything. If that is untrue, "deep tissue with Kaori" is a broken promise | ⚠️ |
| Google Calendar ID | text | Track A prerequisite (GATE-07) | ❌ **missing** |
| May Grace say this person's name? | bool | Per-therapist consent, not a global flag | ❌ **missing** |

**Rooms and resources** — no rows exist at all:

- How many treatment rooms? This is the real capacity ceiling. Fourteen therapists and four rooms
  means the therapist-only occupancy model over-books the building.
- Which services need which room type (couples, cryo machine, wet room)?
- Is a room ever the constraint rather than the therapist? If yes, `resources` rows and
  `requires_resource_kind` must be populated before Phase 2, because the exclusion constraint
  already supports rooms and is simply not being given any.

**Edge cases:** a caller asks for a therapist who has left; asks "who's your best?"; asks for
"someone with strong hands"; asks whether their usual therapist is working Saturday (Grace can only
answer via `checkAvailability`, which reveals availability, not a roster — confirm that is
acceptable, because "is Ramon in today" is a legitimate privacy question about an employee).

---

## 8. Section E — Policies and money

Six policy keys exist in the schema — `CANCELLATION`, `DEPOSIT`, `NO_SHOW`, `LATE_ARRIVAL`,
`INTAKE`, `MEDICAL` — each needing machine-readable `params`, verbatim `spoken_text`, and a named
approver. **None is populated.** Until they are, `cancelAppointment` and `rescheduleAppointment`
return `FeeReason.POLICY_UNAPPROVED` and Grace hands the caller to a person.

### 8.1 The contradiction that must be closed first

Three sources, two answers, one caller waiting:

| Source | Says |
|---|---|
| palmleafmassage.com | A late cancellation is charged **100% of the scheduled service** |
| Ramon (questionnaire) | The **Room Reservation Deposit is forfeited** as the cancellation fee |
| Ola (questionnaire) | **100% charge** for the service |

Two of three say full session fee, and that is what Grace currently quotes. On a 60-minute
non-member massage the difference is **$115 versus a deposit of an amount nobody has ever
specified**. Ask it in exactly these words, and get it back in writing:

> A non-member books a 60-minute massage for Tuesday at 2pm and cancels at 9am Tuesday. What
> **exact dollar amount** do you charge, and does that change if they reschedule instead of
> cancelling outright?

### 8.2 Every policy field

| Policy | Machine params needed | Spoken text needed | Open |
|---|---|---|---|
| `CANCELLATION` | window hours (48), fee type, fee amount or percent, whether it differs for members | one approved sentence | §8.1 |
| `DEPOSIT` | amount, flat or percent, per-service or global, refundable when, expiry, does it apply to members | one sentence | **amount never specified by anyone** |
| `NO_SHOW` | fee, and whether it differs from a late cancellation | one sentence | ❌ |
| `LATE_ARRIVAL` | grace period, whether the session is shortened or the fee stands | ✅ answer drafted; not a policy row | partially |
| `INTAKE` | required before first visit, how far ahead, what happens if incomplete on arrival | ✅ answer drafted | partially |
| `MEDICAL` | what blocks a booking outright, what needs clearance, who calls back | §9 | ❌ |

### 8.3 Money questions with no owner

- **Reschedule versus cancel.** The 48-hour engine treats them the same. Confirm the business does.
- **Waiver authority.** Grace never waives a fee — that is deliberate and prompt-enforced. Confirm
  the front desk can, and that the caller will not be told two different things in one hour.
- **Non-member prepayment.** The approved payments answer says non-members prepay **in full** by
  secure link; the design brief elsewhere describes a deposit only. Which is it?
- **Members' card on file.** Who charges it, when, and does Grace trigger it or does the front desk?
- **Refunds.** Always a transfer? Confirm.
- **Price changes.** How will we be told? A stale price is a chargeback.
- **Vagaro card processing and payment links running in parallel** — how does the bookkeeper
  reconcile two payment rails? (GATE-08.)

---

## 9. Section F — Medical screening and safety

The rules Grace follows are already tight and should not be loosened: she asks one screening
question, she does not ask what the condition is, she does not repeat it back, she does not write it
anywhere, and she never assesses or reassures. A disclosure sets a boolean and routes to a person.
There is deliberately no free-text field on `flagMedicalHold`, because an optional field is one a
model eventually fills.

What the client still owes us is everything on the **other side** of that handoff:

| Question | Why it cannot wait |
|---|---|
| Approve the screening wording verbatim | It is spoken before every booking; it is the most-repeated sentence in the system |
| Which disclosures **block** a booking outright, versus needing a call back? | Recent surgery and cancer were named. Pregnancy? Recent injury? Blood thinners? |
| Who calls back, and within how long? | A blocked booking with no callback SLA is a lost client and a bad experience |
| Physician clearance — who judges it? | Never Grace. Confirm the human process exists |
| Prenatal massage is advertised. Is a pregnancy disclosure a hold, or a routing rule to a trained therapist? | The current design holds **any** disclosure, so every prenatal booking will escalate. That may be correct, but it should be a decision |
| Allergy and scent sensitivity — medical, or a scheduling note? | A caller saying "I'm allergic to lavender" trips the medical rule today and gets escalated instead of booked |
| Do the therapists' own contraindication rules exist in writing? | We need them for the staff-facing callback script, never for Grace |

**One safety topic the current design does not address at all.** Massage businesses receive
inappropriate and solicitation calls. Grace has no rule for them: no refusal script, no
end-the-call trigger, no logging category, and they will pollute the containment metric while
subjecting staff to nothing useful. Decide the handling — a firm single-sentence refusal and an
immediate `endCall`, with a counted outcome — and confirm the client wants it that way.

---

## 10. Section G — Persona, wording and language

| Item | Status | Needed |
|---|---|---|
| Assistant name "Grace" | in use | Client approval. It is on every call |
| Voice — warm, female | in use | Client hears a sample and signs off |
| First message | live: *"Thanks for calling PalmLeaf Massage and Wellness, this is Grace! Quick note — calls are recorded. What can I do for you?"* | Approve verbatim. **The recording clause is CI-enforced (I7) and legally required in Illinois — it may be reworded, never removed** |
| Four competing greeting drafts | unresolved | Collapse to one (GATE-05) |
| AI disclosure | Grace admits it plainly when asked, does not volunteer it | Confirm the client is comfortable. Also a watch item: Illinois disclosure bills are pending, not enacted |
| Sign-off wording | ad hoc | One approved closing line |
| Hold and filler phrases | drafted | Approve — these are heard on every tool call |
| Prohibited topics | ✅ from the questionnaire | Confirm still current |
| Competitor comparisons | ✅ "we compare ourselves with us only" | Good answer; keep it |
| Upsell rule | one light membership sentence, never repeated | Confirm the client wants even that much |
| **Languages** | English only | Spanish was scoped for a later phase. Given the roster, ask which languages callers actually use — this may be worth more than several planned features |

---

## 11. Section H — Messaging, consent and templates

Every text Grace sends must be approved before the 10DLC campaign is submitted, because the campaign
registration includes sample messages.

| Template key | Needed content | Notes |
|---|---|---|
| `booking_confirmation` | date, time, therapist, service, address, cancellation window | Must carry the business name and STOP/HELP |
| `deposit_link` | amount, what it is for, expiry | Never a card request in text either |
| `intake_form` | link, why, deadline | Who is it sent to when the booking is for someone else? |
| `reschedule_confirmation` | old and new time, any fee | |
| `cancellation_confirmation` | what was cancelled, fee charged, how to rebook | Evidence in a dispute |
| `callback_promise` | who will call and roughly when | Sent after `takeMessage` |
| `after_hours_acknowledgement` | optional | Decide if wanted |

**Consent and delivery questions:**

- Who owns the A2P 10DLC brand registration — PalmLeaf's EIN or ours? This determines who can send,
  and it has a 1–3 week clock (GATE-09).
- Quiet hours: the salon closes at 20:30 and Grace answers overnight. Does a 02:00 booking generate
  a 02:00 text?
- Opt-out: a client who texted STOP still needs a booking confirmation. Confirm the business accepts
  that a suppressed number gets email or nothing.
- **Email fallback needs an email address, and no tool collects one.** `lookupCustomer` does not
  report whether we hold one, and `createBooking` has no email field. If a caller rings from a
  landline, the deposit link, the intake form and the confirmation all fail with
  `no_contact_method`. This is a design gap, not a content gap — logged in §18.

---

## 12. Section I — Escalation, staffing and SLAs

The most operationally dangerous blanks in the whole document, because they are the failure path for
everything else.

| Field | Format | Consequence if blank |
|---|---|---|
| Transfer destination | extension or E.164 | **`transferToHuman` has nowhere to go.** Every escalation path terminates in a message |
| Ring timeout before Grace resumes | seconds (25 proposed) | Caller waits in silence or is dumped to voicemail |
| Whisper sentence to staff | text | Whoever answers picks up blind |
| Voicemail fallback | which box | Grace currently promises the desk's voicemail — confirm it exists and is monitored |
| Manager mobile for P1 paging | E.164 | Medical holds and angry callers page nobody |
| P1 acknowledgement SLA | minutes (15 proposed) | WF-18's unacknowledged-escalation chase has no threshold |
| Who reads the daily digest | named person | Reports are written and nobody reads them |
| Weekly QA reviewer | named person | The 20-call sample that takes containment from ~60% to ~85% does not happen |
| Kill-switch operator | named person + method | The manager cannot turn Grace off without calling a developer |
| Out-of-hours expectation | text | Grace should not promise a callback "shortly" at 02:00 |
| Complaint handling boundary | text | Confirm Grace never attempts to resolve a complaint |

`flagEscalation` already carries a fixed reason list — asked for a person, frustrated, complaint,
refund, gift certificate, medical, recording objection, no tool, repeated failure. Walk the client
through it and ask what is missing. Anything they name that is not on that list is either a new
enum value or a gap they have been absorbing manually.

---

## 13. Section J — Compliance and data

Illinois is strict about precisely the things this system does. These are decisions, not preferences.

| Item | Current position | Owner |
|---|---|---|
| Recording retention | 90 days, then purge — our recommendation, unratified (GATE-06) | Client + counsel |
| Transcript retention | Follows recordings | Client + counsel |
| Recording objection path | Grace cannot disable recording mid-call; she escalates. **Confirm a human is reachable, or the objecting caller has nowhere to go** | Client |
| Voiceprints / speaker recognition | **Disabled, permanently.** Illinois BIPA carries a private right of action and per-violation damages | Us — non-negotiable |
| Health information | Boolean only; no diagnosis, condition or medication ever stored; transcripts redacted | Us — invariant I6 |
| Card data | Never spoken, never heard, never stored | Us — invariant I5 |
| Marketing messages | Not sent. Transactional only, without separate written consent | Client must not ask for this casually later |
| Data subject requests | No process exists | Client + us |
| Who at PalmLeaf owns data policy | Unnamed | Client |
| Legal review before launch | Not scheduled | Client + counsel |
| Insurer notified that an AI answers the phone | Not asked | Client |

---

## 14. Section K — Systems of record and operations

| Question | Why it decides architecture |
|---|---|
| Massagebook → Vagaro cutover date (GATE-12) | Two live booking systems means double-bookings that look like AI failures and are operations failures. **Push for a hard date before daytime rollout** |
| Is Vagaro the sole source of truth on day one? | Determines whether the mirror can be trusted |
| Vagaro plan tier + card processing active | Hard prerequisites for API access; the request bounces without them |
| Vagaro API access request submitted? (GATE-01) | 5–7 business day clock, longest pole in the project |
| Per-provider Google Calendars, shareable with a service account | Track A prerequisite (GATE-07 / A-10) |
| Written authorisation to automate their own booking widget (GATE-10) | Track B cannot ship without it |
| 90 days of call logs | Validates volume, after-hours miss rate, and the cost model (A-09). Nobody has pulled them |
| Front-desk conflict protocol | When Grace and a human book the same slot within seconds, who yields? |
| Staff training and announcement | Staff hearing about Grace from a client is a bad start |

---

## 15. Edge-case catalogue

A knowledge base is judged on the calls it was not written for. Each row names the scenario, what
Grace must have been told, and whether she has it today.

**Booking mechanics**

| Scenario | Needs | Today |
|---|---|---|
| "Can I come in now?" | Walk-in policy, min lead time | ❌ |
| Last slot of the day, 120-minute service | Last-bookable rule confirmed against real closing behaviour | ⚠️ |
| Couples massage | Two-provider simultaneous availability | ❌ not modelled |
| Booking for a spouse | ✅ `bookedForName` — but who gets the intake form and the confirmation text? | ⚠️ |
| Booking for a minor | Age policy, consent, whether Grace may book it at all | ❌ |
| "Same therapist as last time" | `preferred_provider_id` + visit history | ❌ not surfaced |
| "A female therapist, please" | Gender field, tool parameter, prompt rule | ❌ |
| Wants a slot beyond the advance limit | `max_advance_days` + a spoken refusal | ⚠️ default |
| Group or party booking | Policy, capacity | ❌ |
| Corporate or on-site chair massage | Policy — likely a transfer | ❌ |
| Waitlist for a full day | Waitlist concept | ❌ Phase F |
| Two callers, same slot, same second | ✅ exclusion constraint | ✅ |
| Wants to cancel one of two bookings | Disambiguation by date | ⚠️ untested |
| Appointment booked by the front desk, not Grace | Mirror coverage; `lookupCustomer` reports only a boolean | ⚠️ |

**Identity and contact**

| Scenario | Needs | Today |
|---|---|---|
| Blocked or withheld caller ID | Identification fallback | ❌ |
| Landline caller — SMS undeliverable | Email capture in-call | ❌ **no tool collects an email** |
| Couple sharing one mobile number | `customers` is unique on phone per tenant — two people, one row | ⚠️ real constraint |
| Caller rings back after being cut off mid-booking | ✅ handled explicitly in the prompt | ✅ |
| Wrong number | ✅ | ✅ |
| Spam or robocall | Detection, an outcome category, and exclusion from containment | ❌ |

**Money**

| Scenario | Needs | Today |
|---|---|---|
| "How much is a massage?" with no duration given | A three-option answer under the never-list-more-than-three rule | ⚠️ |
| Gift certificate purchase or redemption | ✅ escalates — confirm that is right at volume | ✅/⚠️ |
| Package balance enquiry | Package model | ❌ |
| Tipping | An answer | ❌ |
| HSA / FSA card, or a superbill for insurance | A policy | ❌ |
| Disputes the fee Grace just quoted | ✅ transfer | ✅ |
| Wants to buy a membership on the call | Sales path, or a clean transfer | ❌ |
| Deposit link unpaid at 24 hours | ✅ designed: release the slot and notify | ✅ design |

**People and safety**

| Scenario | Needs | Today |
|---|---|---|
| Asks for a therapist who has left | Roster truth | ⚠️ |
| Asks to speak to their therapist directly | Policy | ❌ |
| Complaint about a specific therapist | Escalation with no detail written down | ⚠️ |
| Inappropriate or solicitation call | Refusal script, `endCall`, logging | ❌ **absent** |
| Distressed or vulnerable caller | Escalation, and an explicit rule not to counsel | ⚠️ |
| Medical question ("would massage help my sciatica?") | ✅ never answered, always handed over | ✅ |
| Objects to being recorded | ✅ escalates — depends on §12 having a destination | ⚠️ |

**Operations and calendar**

| Scenario | Needs | Today |
|---|---|---|
| Snow closure at 07:00 | A closure procedure Grace learns about in minutes | ❌ |
| Therapist calls in sick with six bookings | Staff-side rebooking; outbound calling is Phase F | ❌ |
| Public holiday | Enumerated closure calendar | ❌ |
| Power or internet outage at the salon | Kill switch, forwarding revert | ⚠️ documented, untested |
| Vagaro down | ✅ mirror serves reads, writes queue | ✅ design |
| Caller asks for directions from the interstate | Landmark set richer than one sentence | ⚠️ |

---

## 16. Completeness and sign-off

Launch does not require every row above. It requires the right ones, in the right order. Ordered by
the phase each blocks.

| Priority | Item | Section | Blocks | Degradation if still missing |
|---|---|---|---|---|
| **P1** | Cancellation policy, in writing, one answer | §8.1 | Any cancel or reschedule | Grace transfers instead of changing a booking |
| **P1** | Deposit amount and rule | §8.2 | Deposits, prepayment | No money collected on the call |
| **P1** | Transfer destination + manager mobile | §12 | **Every escalation** | Escalations become messages nobody is paged about |
| **P1** | Real provider shifts | §7 | Booking | Availability is fiction; slots offered nobody can work |
| **P1** | Service catalogue confirmed, including the seed-approval question | §6 | Quoting and booking | Wrong prices spoken to real callers |
| **P2** | Closure calendar, 12 months | §5 | Booking | Clients booked into a closed salon |
| **P2** | Room count and constraints | §7 | Booking accuracy | Over-booking the building |
| **P2** | Greeting approved verbatim | §10 | Production launch | Ships with our wording |
| **P2** | SMS templates + 10DLC ownership | §11 | Confirmations, deposit links | Email fallback only |
| **P2** | Medical block list + callback SLA | §9 | Screening quality | Every disclosure escalates, including benign ones |
| **P2** | Massagebook cutover date | §14 | Daytime rollout | After-hours pilot only |
| **P3** | Recording retention ratified | §13 | Nothing technical | 90-day default stands, unsigned |
| **P3** | Acupuncture / chiro / cryo decision | §6 | Coverage | Those callers all escalate |
| **P3** | Gender, language, pronunciation on the roster | §7 | Match quality | Requests we cannot honour |
| **P3** | Tipping, HSA, packages, gift certificates | §6, §15 | Containment rate | Each one is an escalation |

**Sign-off block to be countersigned:** name, role, date, and the statement *"the answers in this
document are the answers PalmLeaf's automated receptionist may give to customers, and supersede any
earlier questionnaire"*. That sentence is what retires the four-respondent problem.

---

## 17. Part two — service and scope questions for the client

Everything from here is the second half of the brief: what we still need to ask about the project
itself. These are not content questions; they change what gets built.

**Coverage and rollout**

1. Should Grace answer **every** call from day one, or after-hours and overflow first? Our
   recommendation is after-hours first — it captures the missed revenue with the least risk, and it
   is where the client's exposure is lowest while the containment rate climbs.
2. What does "success" mean in numbers? Containment percentage, bookings per week, after-hours calls
   answered, or missed-call rate? Pick one headline metric, because it determines what we tune.
3. What is the realistic call volume? The cost model assumes ~45 calls/day at ~3 minutes; nobody has
   pulled the 90-day logs that would confirm it.
4. How many calls arrive at once at peak? Concurrency is a cost and capacity question.
5. What is the current missed-call rate? It is the entire business case, and it is unmeasured.
6. Is there an outbound use case — reminders, no-show recovery, waitlist backfill? Each is a
   different regulatory posture from answering an inbound call.
7. Who at PalmLeaf owns this system day to day once we hand over?

**Boundaries**

8. What must Grace **never** do, even if technically possible? Get this in the client's own words.
9. Is there a call type they would rather she did not take at all?
10. How should she introduce herself to a regular who knows the front desk by name?
11. If a client says "I'd rather talk to a person" every single time — is that a failure, or fine?

**Commercial**

12. Who pays for the per-minute usage, and is there a ceiling that should trigger an alert?
13. What is the trial period, and what ends it — a date, or a metric?
14. Is this exclusive to PalmLeaf, or the first tenant of a product? (We have built multi-tenant
    schema on the assumption it is the latter; it costs a column either way.)

---

## 18. Part two — architecture and logic decisions to confirm

Decisions already taken, mostly by us, that the client or the record should ratify. Each is stated
as position, consequence, and the question that closes it.

| # | Decision taken | Consequence | Question to close it |
|---|---|---|---|
| **D-A** | Vagaro is never called during a call; a local mirror answers | Sub-second availability; the mirror can drift | Confirm the client accepts eventual consistency measured in seconds, not zero |
| **D-B** | Double-booking is prevented by a database constraint, not application logic | No code path can bypass it | None — this is ours, and it is right |
| **D-C** | The 48-hour boundary and every fee are computed in code, never by the model | The model cannot invent or waive a fee | Confirm the front desk's waiver authority does not contradict it (§8.3) |
| **D-D** | Unapproved content is treated as absent | Grace degrades to a human instead of guessing | Confirm the client prefers a handoff to a plausible answer. They always say yes; ask anyway, because it sets the containment expectation |
| **D-E** | Medical disclosures store a boolean and nothing else | No PHI in the system, no notes for staff either | Confirm staff are content to call back with no written context |
| **D-F** | No card details by voice, ever | Keeps the whole stack out of card-data scope | Confirm the client will not ask for it later "just for members" |
| **D-G** | No voiceprints or speaker recognition | Avoids Illinois biometric exposure | Non-negotiable; state it, do not ask |
| **D-H** | Grace admits she is automated when asked, but does not lead with it | Honest without being cold | Client sign-off |
| **D-I** | Booking write path ships as SMS deflection first, then calendar hold, then a real appointment | Revenue in week two instead of week eight | Confirm the client understands the first phase books nothing directly |
| **D-J** | Slot holds expire after 4 minutes; reservations after 15 | A hung-up caller does not freeze the calendar | Confirm these feel right operationally |
| **D-K** | Provider names are spoken aloud | Warmer calls, and a small privacy exposure for staff | Per-therapist consent (§7) |
| **D-L** | Escalation always writes a staff task before transferring | Nobody picks up blind | Confirm staff will actually work the task queue |
| **D-M** | Recording disclosure is in the first utterance and CI-enforced | Illinois all-party consent | Confirm the wording |
| **D-N** | The synchronous tool path is served by our own service, not the workflow tool | Latency, transactions, testable money logic | Internal; recorded in the decision log |

**Open logic questions that are genuinely undecided:**

15. **Whose calendar wins** when Grace's mirror and Vagaro disagree at the moment of booking?
    Currently the mirror, with reconciliation afterwards. That is the fast answer; is it the right
    one on a busy Saturday?
16. **Should Grace ever offer a slot she cannot guarantee?** If the mirror is stale by 30 seconds,
    the honest options are "offer and risk it" or "offer fewer, safer slots".
17. **What happens to a held slot if the caller hangs up mid-booking?** It expires — but should
    Grace call back, or text?
18. **Should a customer record be created for a caller who does not book?** It improves the next
    call and increases the data footprint.
19. **One phone number, two people.** The customer table is unique on phone per tenant. Households
    share numbers. Decide now, because retrofitting identity is painful.
20. **Email capture has no home.** No tool collects an email; the email fallback therefore cannot
    fire for a caller we do not already know. Either add a field to `createBooking`, or accept that
    landline callers get nothing in writing.
21. **`party_size` accepts up to 4 but the engine computes single-subject availability.** Either
    build multi-subject slots for couples, or constrain the parameter to 1 and escalate the rest.
22. **Four approved knowledge answers are unreachable.** `getBusinessInfo` accepts eight topics;
    the knowledge file holds twelve keys. `late_arrival`, `intake`, `services_detail` and `payments`
    are approved, signed off, and can never be retrieved, because no topic maps to them. Either
    extend the topic enum or fold those answers into the reachable keys.
23. **Rooms are modelled and unused.** The occupancy table already supports resources; no rows
    exist. If rooms are the real constraint, availability is wrong in a way no test will catch.
24. **Does Grace know what time it is?** Several natural questions — "are you open now?", "how late
    are you open tonight?" — need current time against the hours table, not a fixed sentence.

---

## 19. Part two — enhancement questions

Each is phrased as a question because each has a cost. Ordered by our estimate of value per unit of
work for this specific business.

| # | Enhancement | Value | Cost | Depends on |
|---|---|---|---|---|
| **E-1** | **No-show and reminder texts** 24h and 2h before | Highest-value item on the list at a massage business. Recovers revenue that is currently walking out | Low — the messaging path already exists | 10DLC |
| **E-2** | **Waitlist backfill.** A cancellation triggers texts to callers who wanted that slot | Turns the most painful event into a filled hour | Medium | Booking live |
| **E-3** | **Therapist matching** — gender, language, modality, pressure preference | Directly requested by callers today and impossible to honour | Medium — schema plus tool parameters | §7 roster data |
| **E-4** | **Returning-client fast path** — recognise the number, offer their usual therapist, service and time in one sentence | Turns a 3-minute call into 40 seconds | Low once history exists | Visit history |
| **E-5** | **Spanish, and possibly Russian** | The roster suggests the staff already work in these languages; the phone line does not | Medium | §10 answer |
| **E-6** | **Membership sales on the call** | The upsell sentence exists but has nowhere to land | Medium | Payment path |
| **E-7** | **Package and gift-certificate balance lookup** | Removes two guaranteed escalations, one of them seasonal | Medium | Vagaro read access |
| **E-8** | **Post-visit follow-up and review request** | Reviews are the growth channel for a local salon | Low | Marketing consent — a different consent basis |
| **E-9** | **Staff console** — see calls, tasks, holds; press the kill switch | Removes us from the client's daily operations | Medium-high | Phase F |
| **E-10** | **Live open/closed and "next available" awareness** | Fixes several natural questions at once | Low | §18 item 24 |
| **E-11** | **Text-message channel using the same brain** | Many callers would rather text; the knowledge and tools are already there | Medium | 10DLC |
| **E-12** | **Weekly client-facing report** — calls answered, booked, escalated, missed | This is what makes the value visible and the invoice easy | Low — the data already lands | Reporting store |
| **E-13** | **Outbound reactivation** — clients who have not visited in 90 days | Real revenue, real regulatory care needed | Medium | Consent review |
| **E-14** | **Call-recording QA loop with the client** — five calls a week, reviewed together | This is what takes containment from ~60% to ~85% | Low, but it needs a named person on both sides | §12 |

---

## 20. Part two — questions we must answer ourselves

Not for the client. These are ours, and they are unanswered.

25. Who chases the client-side gates? GATE-02, GATE-04, GATE-05 and GATE-12 are all unowned, and
    the register already rates "client sign-off drags past launch" as high likelihood. An unowned
    chase is not a chase.
26. Is the weekly review actually happening? The decision log records no review, which means either
    it has not run or running it is not logged. Both are problems.
27. What is our containment target at 30, 60 and 90 days, and what do we do if it stalls?
28. What is the rollback if the client wants Grace off tomorrow? The kill switch is documented and
    has never been tested end to end.
29. What is the support model after launch — hours, response time, who carries the phone?
30. How do we detect that the client changed a price in Vagaro and told nobody?
31. What is the first thing we would do differently for tenant two? Capture it now, while the pain
    is fresh.

---

## 21. Findings from this pass

Discovered while writing this document, against the code as it stands. Each is verifiable in a
minute and none is a matter of opinion.

| # | Finding | Evidence | Severity |
|---|---|---|---|
| **F-1** | Services are seeded **approved** while the same file's docstring and its printed summary both say they ship unapproved pending GATE-04. Grace can quote those prices today | `src/grace_db/seeds.py` — the insert sets `approved_at = now()`; the summary prints "all approved_at NULL" | **High** — either a live wrong-price risk or a misleading comment |
| **F-2** | Four approved knowledge answers are unreachable: `late_arrival`, `intake`, `services_detail`, `payments` | `BusinessTopic` has eight members; `TOPIC_TO_KEY` maps only `team` → `providers_general`; the YAML holds twelve keys | **Medium** — signed-off content that can never be spoken |
| **F-3** | All fourteen therapists are seeded as working 08:00–20:30 every day of the week | `seeds.py` writes one shift per provider per open day | **High** once booking goes live — availability is fiction |
| **F-4** | The approved memberships answer promises member rates on acupuncture, chiropractic, cryo and skin health; none of those services exists in the catalogue | `palmleaf.yaml` memberships entry versus `SERVICES` | **Medium** — a promise with no fulfilment path |
| **F-5** | No tool collects an email address, yet the messaging tools document an email fallback | `messaging_tools.py` `DegradedReason.NO_CONTACT_METHOD`; no email field on any input | **Medium** — landline callers get nothing in writing |
| **F-6** | `checkAvailability` accepts `party_size` up to 4; the availability query computes single-subject slots | contract versus [reference/availability-engine](../reference/availability-engine.md) | **Low now, High if couples massage is offered** |
| **F-7** | `resources` and `requires_resource_kind` exist and are unpopulated | no seed rows | **Medium** if rooms, not therapists, are the real constraint |
| **F-8** | No handling for inappropriate or solicitation calls — no script, no outcome category, no metric exclusion | absent from every prompt section | **Medium** — predictable at this business type |
| **F-9** | Buffers: the last-bookable-start subtracts the service duration but not the 15-minute turnover, so the final session of the day ends at close and the room is cleaned after it | availability query versus `buffer_after_min` default | **Low** — but it is a staffing promise nobody has made |

---

## 22. Acceptance criteria

✅ **AC-11.1** Every field in §4–§14 names its storage location, its consumer, and the behaviour when
it is absent. A field without a stated consequence is a field nobody will chase.
✅ **AC-11.2** Every P1 row in §16 maps to a gate in [09-open-decisions](09-open-decisions.md) §1, or
a new gate is opened for it.
✅ **AC-11.3** No field in this document asks for information the system has nowhere to store; where
that was true, it is recorded as a finding in §21 instead.
✅ **AC-11.4** The sign-off block in §16 is countersigned before the first production call, and the
countersigned date is recorded in the decision log.
✅ **AC-11.5** Every finding in §21 is either fixed or logged as an accepted risk with a named owner
before Phase C completes.
✅ **AC-11.6** `make docs-lint` passes on this document.

## 23. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-11.1** | Should this document become the standard intake for every future tenant? | It is deliberately PalmLeaf-shaped — Illinois, massage, Vagaro. The *structure* generalises; roughly a third of the content does not. Extracting the reusable skeleton is worth doing once there is a second tenant, and premature before | Product |
| **Q-11.2** | Who runs the intake sessions? | The sessions in §2 need someone who can hear "we're flexible on cancellations" and turn it into a policy row with a dollar amount. That is not a note-taking role | Commercial |
| **Q-11.3** | Do we send the client all of §17–§19, or a curated subset? | The full list is honest and long; a client reading twenty-four architecture questions may hear uncertainty rather than rigour. Our inclination is to send §17 and §19 in full, and to bring §18 to a working session instead | Commercial |
| **Q-11.4** | Is F-1 a bug or a decision? | It is one line of code and it determines whether Grace is quoting approved prices or placeholders to real callers. Nobody currently knows which was intended | Engineering, today |
| **Q-11.5** | How often is the knowledge base re-verified after launch? | Prices, staff and hours drift. Nothing in the system notices, and the client will not tell us | Engineering + client |
