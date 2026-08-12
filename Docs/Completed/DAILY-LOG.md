# Daily Log

What was built, newest first. Technical work, written so anyone can follow it.
Format rules: [DAILY-LOG-GUIDELINES.md](DAILY-LOG-GUIDELINES.md). Full detail: numbered files in this folder.
**Engineers: [DAILY-LOG-TECHNICAL.md](DAILY-LOG-TECHNICAL.md)** covers the same days with mechanisms, paths and root causes.

---

## 12 August 2026

- Built the messaging layer end-to-end — a messages table + outbox (migration 0011), a cold-path
  messenger worker (Twilio SMS + SMTP email), and real sendBookingConfirmation / sendIntakeForm /
  sendDepositLink handlers replacing the stubs; a booking now queues real SMS and EMAIL rows, and the
  worker leaves them QUEUED rather than ever marking an unsent message as sent.

- Fixed the invented-callback-number safety bug server-side — takeMessage now reads the number back
  digit by digit and only files after confirmation, enforced in the handler (not just the prompt) like
  the medical-screening gate; also closed the opposite bug where cancel/reschedule filed a blank number
  while promising a callback.

- Captured email + contact preference on createBooking — new contract fields and handler wiring, so
  Grace sends confirmations by the channel the caller actually chose and names only the channels that
  went (never claiming a text when only the email sent).

- Added the missing assistant fallbacks — an idle hook (12 s, max two "are you still there?" prompts),
  a voicemail message, and an end-call message, none of which existed before.

- Added the recovery and edge-flow prompts — transfer-failure recovery (take name/number/reason, read
  back, confirm follow-up), an after-hours branch, a contact-preference step, and escalation that now
  offers a handoff and waits, handing over only on a second failure.

- Fixed the accent drop and redeployed clean — switched the transcriber from `en-US` to `en` (the cause
  of "you cut out a bit"), then shipped with 166 tests passing and no Vapi drift.

⚠️ The messenger has no Twilio/SMTP credentials yet, so every queued message sits unsent until those
and the intake/deposit URLs are set. And transfers still can't complete — no real transfer or
front-desk number exists (the fallback dials a placeholder), so the new recovery flow is the only thing
standing between a caller and a dead handoff.

---

## 11 August 2026

- Restored the live call after the tunnels died — the prior session's background processes (and their
  Cloudflare quick-tunnels) were killed on exit, so every tool call hit a dead address; re-minted both
  tunnels, redeployed to Vapi (no drift), and relaunched everything under `setsid` so it survives the
  session ending.

- Fixed availability silently failing on a stale mirror — the dev mirror fixture had aged past the
  30-minute freshness gate (a day old), so checkAvailability refused every slot; added a permanent
  `make db-devfixture` + `mirror-freshness.sql` and confirmed a named-therapist request ("Julie") now
  returns slots.

- Surfaced a critical safety bug through a live call — on a web call (no caller ID), Grace fabricated a
  plausible +1 847 callback number for takeMessage and filed it as real, because the tool says "default
  to the number they're calling from" and, with none present, she invented one instead of asking.

- Diagnosed the rest of the failed call to real causes — a "membership pricing" query matched no
  service name (the member prices exist in the DB), the knowledge base says "fourteen therapists" but
  holds none of the names (they live in the DB, unreachable by that tool), getBusinessInfo was re-called
  3× with identical args, the transcriber is pinned to `en-US` (dropping the caller's accent), and a
  booking went out dated 2025 instead of 2026.

- Found that email capture is a schema gap, not a config tweak — there is no email field anywhere in
  the system (not in any tool, not in the `customers` table), so confirmations and deposit links by
  email need a migration plus a new/extended tool before they can exist.

- Hunted for a free virtual number and came up empty — Call.com and Vyke are paid-only, TextNow is
  region-blocked (a VPN didn't get past it), and TextFree hung on "searching for a number" across many
  VPN locations and area codes without ever issuing one.

⚠️ The invented-callback-number bug is diagnosed but not yet fixed, so takeMessage can still file a
fabricated number and stays web-harness-only for now. Everything runs on laptop tunnels (setsid-persistent,
but gone on reboot) with Vagaro unconnected and availability on a dev fixture.

---

## 10 August 2026

- Wired the full tool chain live end-to-end — Vapi → Cloudflare tunnel → FastAPI Core API on :8080 →
  PostgreSQL (19 Alembic migrations) — retiring the mock server, and proved answers are read live from
  Postgres by editing a price to $777 in the DB and hearing it spoken back with no redeploy.

- Redeployed the platform clean against the live stack — the Vapi assistant (15 tools + 1 structured
  output) and 9 n8n workflows both applied with zero drift, tools and events pointed at separate
  Cloudflare tunnels.

- Fixed a grounding bug where "what services do you offer?" returned nothing — the query word
  "services" matched no service name and fell through to "I don't have that one"; added a catch-all
  synonym set mapping it (plus "pricing", "what do you offer") to the full list, while still refusing
  unknown services, verified live.

- Profiled tool-call latency and pinned it on the tunnel, not the database — ~26 ms for the Postgres
  query vs ~376–756 ms through the Cloudflare quick-tunnel (~94% of the round-trip); rejected Redis and
  flagged hosting the Core API (Dockerfile + compose already built) as the real ~390 ms win.

- Surfaced 3 real defects through a live call on actual data — booking can't complete on a natural call
  (checkAvailability speaks a sentence but never returns the hold id createBooking needs), "evening"
  requests return morning slots (candidate SQL capped at LIMIT 200, starving the ranker before
  afternoon), and the Core API had no /webhooks/vapi/events route (worked around by routing events to
  the mock server).

- Restored the web-harness config generator — a pnpm leftover from the TypeScript→Python port that no
  longer ran, rebuilt as a Python `make vapi-harness` target so the browser web call could be placed
  at all.

⚠️ The whole chain runs on a laptop tunnel that dies on restart, and Vagaro is still unconnected
(availability rests on a temporary dev fixture), so nothing here is production-ready and the faster
voice stack stays unproven until the 10-day A/B.

---

## 8 August 2026

### New features — 8 added

- **Grace answers from PalmLeaf's real data** — a knowledge base of approved Q&A (hours, location,
  memberships, policies) plus 14 named therapists and corrected prices ($115/$160/$230, not the
  invented $135/$185) seeded into the booking database, with 12 massage styles as duration aliases.
  The service catalogue still ships unapproved, so she declines to quote a price until the client
  signs off.

- **Turn latency roughly halved** — ~1.9–2.5 s to ~1.0–1.3 s, by moving to GPT-4.1-mini and Cartesia
  Sonic, smart endpointing (a dynamic ~50–200 ms in place of a fixed 1.2 s wait), and tighter
  generation (temperature 0.6, 150 tokens). A second variant is staged for a 10-day A/B, so the stack
  is settled by calls, not opinion.

- **A natural greeting that stays lawful** — the "virtual assistant" label is gone (no enacted
  Illinois AI-disclosure law), but a shortened recording clause stays, mandatory under all-party-consent
  statute 720 ILCS 5/14-2. A system-prompt sentinel plus CI checks still force Grace to admit she is
  automated if a caller asks, and fail the build if the greeting and its validator drift apart.

- **Hold lifecycle tightened against cross-caller lockout** — offered-but-unchosen slots now release
  the instant a caller picks one (verified live), on a re-ask for different times, and on hang-up.
  Before, they stayed locked until the timer expired, denying other callers slots that were already dead.

- **Safer edge-case handling** — Grace now refuses to confirm a therapist who isn't on the roster,
  won't "cancel" an appointment made before she existed (she files a callback task instead), and a
  medical disclosure locks booking for the rest of the call. A cancellation-policy engine landed with
  them and flagged a website-vs-questionnaire fee conflict for the client to resolve.

- **Escalation and transfer that behave like service** — Grace acknowledges, alerts a human with
  context, then transfers; the alert is delivered by a background notify worker off the call path, so
  a slow alerting system can never become silence on a live call.

- **A read-only Vagaro discovery script** — it authenticates, enumerates the live API and records
  sanitised request/response shapes to answer the write-capability question, gated until credentials
  arrive.

- **The system prompt rebuilt end to end** — 8 sections and all 13 tool descriptions rewritten, with
  the suite now at 125 tests under mypy-strict across 71 files behind 4 import contracts.

⚠️ **Grace still cannot complete a booking** — every service is marked unapproved until PalmLeaf sends
its confirmed price list, so she declines to quote or book. Vagaro is still unconnected (credentials
queued) and the faster voice stack is unproven until the 10-day A/B runs on real calls.

---

## 7 August 2026

### New features — 8 added

- **A PostgreSQL booking database** — ~two dozen tables (catalogue, schedules, occupancy, appointment
  mirror, bookings, outbox, queues) across 17 forward-only migrations, retiring the fixtures file.

- **Double-booking blocked inside the database** — a GiST exclusion constraint over each therapist's
  time range refuses overlapping holds; live-tested, the second hold rejected and the same slot for
  another provider accepted.

- **A SQL availability engine** — one query intersects shifts, hours and time-off against active
  occupancy for bookable slots (148 over three days), refusing to quote on a mirror >30 min stale or
  an unapproved service.

- **An 8-state booking state machine** — all 64 transitions tested, a row-level trigger rejects any
  status change missing its audit event, and the calendar write is gated behind a settled deposit
  via an outbox.

- **A booking-system port with a stateful fake** — interface and in-memory stand-in coded ahead of
  Vagaro so the domain builds and tests today; 8 contract tests pin pagination, not-found and
  phone-normalisation behaviour.

- **A rate-limited, resilient API client** — a 2-per-second / 3,000-per-day token bucket and circuit
  breaker cap it under Vagaro's 5,000-a-month quota, local-mirror reads holding real spend near 1,900.

- **Grace's tool service, live on FastAPI** — it quotes approved services from Postgres in spoken
  form; an import-linter contract now fails the build if any call-path module reaches an adapter.

- **A containerised Vagaro webhook receiver** — inserts and acknowledges within the 20-second window
  and dedupes on event id, shipping as one Docker box (service + Postgres) on Hostinger, internal
  reports bearer-gated.

⚠️ **No live Vagaro yet** — credentials still queued, so the port has no real adapter and the mirror
no real appointments; Grace's number still serves fixtures, and the cutover is the next task.

---

## 6 August 2026

### New features — 5 added

- **Grace has a real phone number, and she has taken her first live call** — `+1 651-386-9103`,
  rented and connected today. Calling it reaches her for real: greeting, recording disclosure, and a
  full mock booking conversation, over a live tunnel end to end.

- **The phone system is now readable from code** — 9 call-routing rules, 17 extensions and 4 numbers
  pulled live from PalmLeaf's real RingCentral account into a file we keep, which re-checks itself
  every run and reports anything that changed. The second run already came back clean.

- **Transfers now carry the caller's real number, not Grace's** — when Grace hands a call to a
  person, whoever picks up now sees the customer's own number, so a callback reaches the right
  person instead of ringing Grace's line back.

- **One command puts Grace on the internet** — the mock booking system gets a public address in a
  single step, which is what today's call actually rode on, and what every future test call will
  need too.

- **A complete, approved plan for connecting Grace to PalmLeaf's real booking system** — every
  question about how Vagaro's data actually reaches her now has a written, reviewed answer, staged
  into build phases. Nothing in it is built yet; that starts next.

### What changed

- **Grace took a live phone call for the first time — the single risk flagged in every report until
  today.** The voice path worked end to end on the first real attempt: she answered, spoke the
  required recording disclosure, and carried a caller through a booking. What she said was still
  invented test data, and the number isn't PalmLeaf's real line yet — but the phone call itself,
  the hardest unknown in the whole project, is no longer a guess.

- **Vagaro access — the biggest blocker in the project — got real answers instead of assumptions.**
  Reading Vagaro's own documentation confirmed exactly how it will talk to Grace: six kinds of
  webhook notification (appointments, customers, payments and more), a rule that we must
  acknowledge each one within 20 seconds or it retries five times over 15 minutes, and a hard limit
  of about 5,000 requests a month — roughly 166 a day. That last number is why the design never
  asks Vagaro a question mid-call and instead keeps a constantly-updated local copy of the schedule.
  The access request itself is already filed and sitting in Vagaro's approval queue.

- **We can now read PalmLeaf's phone system directly, and it disagreed with the plan.** The routing
  for 847.961.4800 lives in nine company-wide rules, not on the extension the design assumed — the
  per-extension route is closed on this account entirely — and none of them state how long a call
  rings, so whether voicemail can beat a forward has to be settled by a test call, not a document.

- **A safety net just caught its own near-miss.** The file where every credential and web address
  lives had never actually been read by the deploy tools — filling it in did nothing, silently.
  Fixing that surfaced a second, sharper problem immediately: an early version of the fix would have
  overwritten a working setup with blanks the moment someone copied the template, because a blank
  value there beats a real one already in place. Both are fixed, and neither ever shipped.

- **A gap between what the documents claimed and what the build actually checked is now closed.**
  The rule that every planning document must follow a fixed template existed but was deliberately
  left out of the real gate because 19 of them didn't conform yet; today's rewrite finished the last
  of them, so all 20 pass, and the same check that used to be optional now blocks a build the same
  way a failing test does.

⚠️ **Today's call proved the phone path, not the business behind it.** Grace still answers from
fixed pretend data, not PalmLeaf's real services or calendar, and today's number is not the one
customers will actually dial — that still needs RingCentral's write access, which does not exist
yet. The tunnel that carried today's call is a laptop process: fine for a supervised test,
disqualifying for anything unattended. Two questions about the real phone line — how long a call
rings before voicemail wins, and how many calls it can hold at once — still have no answer from
configuration alone.

---

## 5 August 2026

### New workflows — 8 added (n8n went from 6 files to 14 — but only 5 you can start or stop)

- **WF-25 Reporting Orchestrator** — owns all five report schedules and only routes time; writes
  nothing itself. ✅ **Live** — the single on/off switch for every report.

- **WF-19 Platform Heartbeat** — every 15 minutes, into `platform_heartbeat`. ✅ **Live** — proves
  n8n is alive and Vapi still answers.

- **WF-07 Nightly Reconciliation Report** — 03:15, started by WF-25, into
  `reconciliation_reports`. ✅ Deployed — records a row saying the service is missing until it exists.

- **WF-11 Hourly Call Digest** — :20 past the hour, started by WF-25, into `call_digests`.
  ✅ Deployed — same "records the gap" behaviour.

- **WF-17 Vagaro Change Fan-out** — on demand, into `fanout_log`. ✅ **Live** — its credential was
  created this afternoon.

- **WF-23 Core API Report Fetch** — only when a report calls it; returns data rather than storing
  it. ✅ Deployed — the shared "fetch a report, survive a missing service" step.

- **WF-24 Vapi Call Fetch** — only when a report calls it; returns data. ✅ Deployed — the shared
  "fetch calls, work out what happened on each" step.

- **WF-26 Send Report Email** — only when a report calls it; sends one email. 🔨 **Built, not
  deployed** — waiting on the mail account and the recipient address.

Eight of the fourteen files are now sub-workflows with **no trigger of their own** — they cannot run
unless a parent calls them.

### New features — 6 added

- **One switch for all reporting** — turning off 1 workflow stops all 5 reports and nothing else;
  previously that was 5 separate schedules to hunt down.

- **n8n storage tables** (8 created) — where every report actually lands. **None existed**, which is
  what was silently breaking them.

- **Shared logic, written once** — the "read the calls, work out what happened" step existed in 3
  near-identical copies; it is now 1.

- **Reports arrive by email** — 4 of the 5 reports hand a finished message to one shared sender,
  instead of sitting in a table nobody opens.

- **Working failure reporting** — the handler meant to report a failed workflow now records it where
  we can read it, instead of failing itself.

- **Three new build rules** (18 total) — the build rejects a workflow naming another by raw internal
  ID, and a fetch that would skip a quiet day.

### What changed

- **Reporting collapsed from five independent schedules to one switch, and the logic behind it from
  three copies to one.** WF-25 owns every report timer and calls each report as a sub-workflow;
  the "read the calls, work out what happened" step that three reports each carried privately is now
  a single shared step, so a definition changes in one place instead of three.

- **Three silent production failures, found by asking the live systems rather than trusting our
  records.** Every report wrote to storage tables that had never been created; the error handler
  itself crashed on a setting n8n's cloud blocks; and the escalation webhook checked its signature
  inside a script step that cannot read the secret on this plan — all now fixed and re-verified.

- **Deploy order turned out to govern saving, not just starting.** n8n refuses to even save a
  workflow that calls one which is not yet published, so the deploy tool now sorts by dependency and
  publishes shared steps first — the first attempt failed halfway through until it did.

- **Four reports gained email delivery through a single shared sender.** The hourly digest
  deliberately opts out: 24 routine emails a day is how a reporting inbox becomes a folder people
  stop opening, taking the four that matter with it.

⚠️ **Grace still has not taken a live call**, so every report will stay empty until she does. Email
delivery is entirely unproven — the mail account and recipient address it needs still don't exist,
so WF-26 has never actually sent anything.

---

## 4 August 2026

### New workflows — 3 added

Each reads call records straight from Vapi's call API, so none depends on anything we are still
blocked on. **All three are deployed, active, and running on schedule.**

- **WF-20 Daily Call Digest** — 07:30 daily, Chicago time, into `call_metrics` (7 fields).
  Yesterday's totals: calls, bookings, escalations, medical holds, average length, and the share
  handled without a human.

- **WF-21 Weekly QA Sampler** — Mondays 09:00, into `call_samples` (9 fields). 20 calls picked at
  **random** with recording links, so ordinary calls get reviewed — not only the ones that already
  went wrong.

- **WF-22 Call Quality Alert** — hourly at 7 minutes past, into `call_flags` (5 fields). Calls that
  errored, ended under 15 seconds, or were handed to a person — the three signals that mean
  something is wrong.

Each ends with a Postgres step that is **deliberately switched off** until we have a hosted
database, so turning it on later is a setting, not a rebuild.

### New features — 6 added

- **Per-tool reference pages** (16) — every one of Grace's 15 tools, generated from the code: each
  input, what it means, timeouts, and what she says on failure.

- **Per-workflow reference pages** (7) — every n8n workflow written out step by step with a live
  diagram; previously one diagram existed and it contradicted what was deployed.

- **Reporting database schema** (3 tables) — permanent storage for the figures above, ready to
  switch on.

- **Empty-day zero row** — a day with no calls records an explicit zero instead of nothing, because
  a missing report looks identical to a broken one.

- **Document check** (20 documents) — fails the build if a planning document loses its header,
  misnumbers its sections, or still names the old technology.

- **Two new n8n safety rules** (16 total) — one allows a switched-off step to carry an unfinished
  credential; one stops a scheduled report silently skipping when there is no data.

### What changed

- **Rewrote the whole codebase from TypeScript to Python** — about 3,200 lines covering everything
  that talks to Vapi and n8n. Done now it cost one session; after the next phase of work it would
  have been roughly five times the size.

- **Proved the Python version behaves identically**, rather than assuming it. We pointed it at the
  same live assistant and the same live workflows and it reports zero differences, and all 14 tests
  and safety checks return exactly what they did before.

- **Fixed a deploy bug that had been silently failing the whole time.** We were writing an internal
  ID into the field n8n uses for a display name, and n8n quietly corrected it on every deploy — so
  our change-detection kept reporting a difference that could never be resolved.

- **Closed a privacy hole the language change introduced.** Python's schema tools use developer
  comments as public descriptions, so internal engineering notes were being sent to Grace as part
  of her instructions. They are stripped now, with a build check so they cannot come back.

- **Built the reporting workflows to read Vapi directly**, rather than waiting on a service that
  does not exist. That is why n8n had looked empty: the three older workflows are correct but have
  nothing to trigger them.

- **Reference pages for all 15 tools and all 6 workflows are now generated from the code itself**,
  and the build fails if they fall out of date — previously one tool in fifteen was documented by
  hand, and our only workflow diagram contradicted what was deployed. Reading that output then
  caught two faults in the generator: it reported three workflows as having no timezone when all
  three run on Chicago time, and it could not tell which table each one writes to. Both were the
  generator misreading correct settings, which is the worst fault possible in a tool whose only job
  is documentation you can trust.

⚠️ **Grace still has not taken a live call** — her tools point at a placeholder address, so every
one of them would fail today. The reporting workflows now run, but they have nothing to report until
she does. The emergency stop that silences the phone line also lost its one-click button and is now
a slower manual step — [05-pending-and-blocked.md](05-pending-and-blocked.md).

---

## 3 August 2026

- **Grace and all 15 of her tools are live in Vapi, deployed straight from our code.** Her tools
  cover checking availability, booking, rescheduling, cancelling, taking a message and transferring
  to a person. Nothing was set up by hand in a dashboard, so every change is reviewable and can be
  rolled back.

- **The system can now tell, at any moment, whether what's running matches what we intended.**
  This was harder than it sounds: Vapi silently fills in dozens of its own default settings, which
  made the obvious version of this check permanently report false alarms. It now ignores anything we
  didn't explicitly set, and reports a clean match immediately after deployment.

- **All 15 tools are defined in one place, and everything else is generated from it** — the tool
  definitions sent to Vapi, the instructions Grace reads, and the checks that validate her requests.
  Adding a tool is a single entry. Nothing can fall out of sync, because nothing is maintained twice.

- **Added a one-second check that catches invalid settings before anything reaches Vapi.** It
  compares our configuration against Vapi's own published list of what it accepts. It immediately
  found four settings in our plans that Vapi no longer supports at all, and two more that Vapi
  rejects outright — those used to fail mid-deployment, and now fail instantly with an explanation.

- **Built a practice system so Grace can be tested today, without Vagaro, Stripe, Google or a phone
  line.** It answers her requests with realistic data and checks that everything she sends is valid.
  It found three speaking bugs straight away — Grace said "Monday the third" for a Tuesday, and read
  $115 as "one 10-five" instead of "one fifteen". Her way of speaking times, dates and prices is now
  protected by 14 automated tests.

- **Three staff-alert workflows are live in n8n**, covering urgent alerts, automatic escalation after
  15 and 30 minutes, and failure notifications. Getting them running meant fixing three real
  problems, including one where a workflow would deploy successfully and appear fine, then fail the
  first time it actually ran.

⚠️ **Not proven yet:** Grace has not taken a live call and no workflow has actually run — she is
pointed at a placeholder address, so a real call would fail. Two smaller gaps: we cannot yet pull
changes back out of n8n into our code, and one workflow reports a false change every time it
deploys. Details in [05-pending-and-blocked.md](05-pending-and-blocked.md).

> *Corrected 4 Aug: the "false change every time" was not a cosmetic comparison issue as written
> here — it was a real bug affecting all three workflows, now fixed. See today's entry.*
