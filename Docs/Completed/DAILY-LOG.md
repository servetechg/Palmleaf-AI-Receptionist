# Daily Log

What was built, newest first. Technical work, written so anyone can follow it.
Format rules: [DAILY-LOG-GUIDELINES.md](DAILY-LOG-GUIDELINES.md). Full detail: numbered files in this folder.

---

## 4 August 2026

- **Moved the entire codebase from TypeScript to Python** — about 3,200 lines. The original language
  choice was made before it was ever put to the client, and the reasoning behind it was thin. Doing
  this now cost one session; after the next phase it would have been roughly five times the work.

- **Proved the new code does exactly what the old code did**, rather than assuming. The Python
  version was pointed at the *same* live assistant and the *same* live workflows, and reports no
  differences on either. The tests, the safety checks and the practice system all behave identically.

- **Found a bug that was silently present the whole time.** Our deploy was writing an internal ID
  into a field n8n uses for the display name. n8n quietly corrected it every time, so every check
  reported a change that could never be resolved. All three workflows now match cleanly.

- **Closed a privacy hole created by the new language.** Python's schema tools use developer notes
  as public descriptions, which meant internal implementation comments were being sent to Grace as
  part of her instructions. Stripped, with an automatic check so it cannot come back.

- **Rewrote the project README as a complete map** — every file and folder, what each of Grace's 15
  tools does and when she uses it, where to find each piece in the Vapi and n8n dashboards with live
  IDs, and how a change travels from an edit to something running.

- **Consolidated the progress records** so each entry is a real feature rather than a fragment, and
  refreshed them for the new language.

⚠️ **Unchanged:** Grace still has not taken a live call and no workflow has actually run. She points
at a placeholder address. Everything else is verified; that one step is not.
  Details in [05-pending-and-blocked.md](05-pending-and-blocked.md).

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
deploys. Details in [05-pending-and-blocked.md](05-pending-and-blocked.md).

> *Corrected 4 Aug: the "false change every time" was not a cosmetic comparison issue as written
> here — it was a real bug affecting all three workflows, now fixed. See today's entry.*
