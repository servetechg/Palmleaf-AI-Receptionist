# Daily Log

What was built, newest first. Technical work, written so anyone can follow it.
Format rules: [DAILY-LOG-GUIDELINES.md](DAILY-LOG-GUIDELINES.md). Full detail: numbered files in this folder.

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

⚠️ **Not proven yet:** Grace has not taken a live call and no workflow has actually run. She is
pointed at a placeholder address, so a real call would fail. Two smaller gaps: we cannot yet pull
changes back out of n8n into our code, and one workflow reports a false change every time it
deploys. Details in [06-pending-and-blocked.md](06-pending-and-blocked.md).
