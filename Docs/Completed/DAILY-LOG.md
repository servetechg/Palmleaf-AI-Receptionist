# Daily Log

Plain-language summary of work delivered, newest first.
Technical detail lives in the numbered files in this folder.

---

## 3 August 2026

- **Audited the existing plans against the real Vapi and n8n systems — and found they contained
  settings that do not work.** 32 corrections across two documents. The most serious: the call
  assistant was configured in a way that silently switched off end-of-call reporting, which would
  have quietly disabled call summaries, quality review and privacy redaction with no error anywhere.

- **Grace, the AI receptionist, is now live in the Vapi account.** The assistant plus all 15 of her
  tools (check availability, book, reschedule, cancel, take a message, transfer to a person, and so
  on) are deployed and version-controlled, so every future change is reviewable and reversible
  rather than clicked into a dashboard.

- **Built a stand-in "practice system" so Grace can be tested now, without waiting for Vagaro,
  Stripe, Google or the phone line.** It answers her tool requests with realistic data and — more
  importantly — checks that what she sends matches what we expect. It immediately caught three
  speaking bugs, including Grace saying *"Monday the third"* for a Tuesday, and quoting a price as
  *"one 10-five"* instead of *"one fifteen"*.

- **The staff alerting and escalation workflows are live in n8n.** Three workflows: urgent issues
  reach staff, unacknowledged urgent issues escalate automatically after 15 and 30 minutes, and any
  workflow failure raises an alert instead of disappearing.

- **Removed the Slack dependency, which improved the design rather than weakening it.** All
  notifications now go through one internal route, so n8n stores no outside passwords at all, and
  text-message compliance rules can no longer be accidentally bypassed. If Slack is wanted later it
  plugs in with no rework.

- **Put automatic safety checks in place, and started this delivery log.** Every future change is
  now checked against the live Vapi system before it can ship, including a hard rule that the legally
  required "this call may be recorded" greeting cannot be removed or edited around. Progress is
  tracked in this folder, with an explicit list of what is proven versus still unproven.

**Honest status:** everything above is built and independently verified, **but Grace has not yet
taken a live call.** She is currently pointed at a placeholder address, so a real call would fail.
Connecting her to the practice system is the next step and needs one short setup task — see
[06-pending-and-blocked.md](06-pending-and-blocked.md).
