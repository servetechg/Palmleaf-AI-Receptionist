# RingCentral

Read-only. `make rc-snapshot` GETs the live account and writes `snapshot/*.json`; re-running
reports per-file drift, the same way `n8n-diff` does. No write path exists in this repository
yet — `src/grace_platform/ringcentral/client.py` documents the rules Phase 2 inherits when it
gains one.

The snapshot is the **rollback reference**. 847.961.4800 is PalmLeaf's only business number;
before any code changes it, its pre-Grace state has to be in git.

## What the first live run found — 6 August 2026

Auth: **working**. Private JWT app against `https://platform.ringcentral.com`, logging in as
the Super Admin extension. Every read below succeeded on the first attempt with no scope errors.

**Account.** `3041612036`, RingEX Core™, status Confirmed, main number **+1 847 961 4800**,
operator extension `3041612036` (ext 101, Soneth Zanoria). 17 extensions: 10 IVR menus, 3 users,
2 voicemail boxes, 1 department/call queue (`Soneth & Clinic Phone`, ext 5), 1 announcement.

**Numbers.** Four: the main company number, two direct numbers (ext 101, ext 103) and a
fax-only number. Only the main number is customer-facing.

**Where the routing lives — the finding that changes the plan.** The account has RingCentral's
`NewCallHandlingAndForwarding` feature enabled, so the **per-extension** answering-rule API
returns:

```
403 This API is not available with enabled feature [NewCallHandlingAndForwarding].
```

The **company-level** endpoint `/restapi/v1.0/account/~/answering-rule` is unaffected and is
where the rules for the main line actually live. Phase 2's whitelist rule is therefore a
*company* answering rule, not an extension one. The failed extension call is snapshotted as
`extension-answering-rules.json` so the constraint is recorded rather than rediscovered.

**Answering rules — 9, all company-level.** Every custom rule is keyed on
`calledNumbers: [{"phoneNumber": "+18479614800"}]` and a weekly schedule, and every one of them
uses `callHandlingAction: "Bypass"` with `extension: {"id": …}` — i.e. hand the call to another
extension (an IVR menu or voicemail box) rather than forward it to a number.

| id | name | enabled | target extension |
|---|---|---|---|
| `business-hours-rule` | (BusinessHours) | yes | 3226354036 — IVR 1002 "IVR FSOS (847) 474-3533" |
| `after-hours-rule` | (AfterHours) | yes | 3981763036 — Voicemail 4 "Voicemail Greetings" |
| `5980745036` | 1st Shift Sched (Weekdays) | yes | 3226354036 — IVR 1002 |
| `539433037` | 2nd Shift Sched (Weekdays) | yes | 4093004036 — IVR 7687 "IVR - Soneth" |
| `6068302036` | 3. Wknd Open hrs | yes | 4093004036 — IVR 7687 |
| `6244998036` | In-Office Receptionist | yes | 4058507036 — IVR 1004 "IVR - In-Office" |
| `4516027036` | 4. After Hrs send to VM 8:30pm-8:00am | no | 3892017036 — IVR 7684 |
| `6071753036` | Ramon Mascarenas | no | 3945552036 — IVR 7685 |
| `6203771036` | Ramon Temporary Ext | no | 4038921036 — IVR 7686 |

Company business hours are 08:00–20:30 every day; the operator extension's own schedule is
08:00–21:00 Mon–Fri and 08:00–20:30 at weekends.

**L3 — does voicemail race a forward?** Not answerable from configuration alone, and now we
know why: no rule declares a `forwarding` object at all, so there are no ring counts to read.
Ring/timeout behaviour lives inside the IVR menus and the call queue each rule bypasses to.
L3 stays an **empirical** question — a Stage A test call that is allowed to run to voicemail.

**L9 — concurrent-call limits.** `service-info` publishes `limits` but none of them concern
concurrent calls (`cloudRecordingStorage`, `freeSoftPhoneLinesPerExtension`,
`maxExtensionNumberLength`, `maxMonitoredExtensionsPerUser`, `meetingSize`). RingEX Core™ with
`includedPhoneLines: 0` on the billing plan. So the account itself does not answer GATE-11's
concurrency question either; at ~45 calls/day it is near-certainly moot, and it stays an
observation to make during the pilot rather than a documented figure.

**Voicemail greetings.** Not captured. `/extension/{id}/greeting` returns 404 on this account,
and guessing at further endpoints is not worth the risk on a live line. Greeting *references*
are visible inside each answering rule (`greetings[].custom.id` /
`greetings[].preset.id`), which is what a rollback would need.

## What Phase 2 consumes from this

The write path (`pilot.py`, `make rc-pilot-diff` / `rc-pilot-apply` / `rc-kill`) builds a single
custom **company** answering rule named `grace-pilot-whitelist`, and the payload shape comes
straight out of `snapshot/answering-rule-*.json` rather than from documentation: `type: Custom`,
a `schedule.weeklyRanges` block, `calledNumbers` pinned to +1 847 961 4800, plus a `callers`
condition holding `GRACE_PILOT_CALLERS`, and a call-handling action pointing at Grace's Vapi
number. Whether that action is an external forward or a `Bypass` to a new extension configured
to forward is the one shape not yet observed — no existing rule forwards externally, so Phase 2
must confirm it against a live GET before writing anything.

The nine rules above are also the refusal list: L7 says write code may only ever create,
enable or disable rules named `grace-*`, and every id in that table is one it must hard-exit
rather than touch.
