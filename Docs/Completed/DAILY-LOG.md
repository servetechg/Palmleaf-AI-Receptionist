# Daily Log

Plain-language summary of work delivered, newest first.
Format rules: [DAILY-LOG-GUIDELINES.md](DAILY-LOG-GUIDELINES.md). Technical detail: numbered files in this folder.

---

## 3 August 2026

- **Audited the existing plans against the real Vapi and n8n systems and found settings that do not
  work** — 32 corrections. Worst one: the assistant was silently switching off end-of-call reporting,
  which would have disabled call summaries and privacy redaction with no error shown.

- **Grace is now live in the Vapi account** — the assistant and all 15 of her tools (check
  availability, book, reschedule, cancel, take a message, transfer to a person), deployed from
  version control rather than clicked into a dashboard.

- **Built a stand-in "practice system" so Grace can be tested without Vagaro, Stripe, Google or a
  phone line.** It caught three speaking bugs immediately, including Grace saying "Monday the third"
  for a Tuesday.

- **Staff alerting and escalation are live in n8n** — three workflows covering urgent alerts,
  automatic escalation after 15 and 30 minutes, and failure notifications.

- **Removed the Slack dependency, which improved the design** — notifications now go through one
  internal route, so n8n stores no outside passwords and SMS compliance rules can't be bypassed.

- **Added automatic safety checks** — every future change is verified against the live Vapi system
  before it can ship, including a hard rule protecting the legally required recording disclosure.

⚠️ **Not yet done:** Grace has not taken a live call. She points at a placeholder address, so a real
call would fail. One short setup task away — see [06-pending-and-blocked.md](06-pending-and-blocked.md).
