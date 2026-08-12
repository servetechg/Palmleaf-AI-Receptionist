# Phone numbers

Two files, two different routes to Grace. `deploy_phone_numbers()` in
`src/grace_platform/vapi/deploy.py` reads both, matches remote numbers by `name`, and prints
`+ / ~ / =` like every other part of the deployer. A file whose configuration is not ready is
**skipped, not fatal** — the same behaviour the n8n deployer uses for a workflow waiting on a
credential.

| File | Provider | Status |
|---|---|---|
| `grace-line.json` | `vapi` | Grace's own number, provisioned by Vapi. Area code 651 — Vapi had no 847 stock (offered 272/572/651); cosmetic either way, since this number is never published and callers only ever see the forwarded main line. |
| `main.json` | `byo-phone-number` | PalmLeaf's real line, 847.961.4800, via a SIP trunk. Dormant — the trunk does not exist. |

## `grace-line.json` — the pilot number

Vapi issues a free US number and binds it to the assistant recorded in `.lock.json`. Nothing
about RingCentral is involved: RingCentral reaches this number later as an ordinary forward
(`Docs/reference/telephony.md` §1.1). The number is never published — see loophole L8.

`fallbackDestination` is the safety net (L4). If the assistant cannot be reached — Vapi
outage, dead tunnel, `assistant-request` failure — the caller is transferred to
`GRACE_FRONT_DESK_NUMBER` instead of hearing an error and a hang-up. While that variable is
unset the deployer drops the whole block and says so: `TransferDestinationNumber` requires
`number`, so a destination missing it is no destination at all, not a partial one.

`numberDesiredAreaCode` is create-only. `UpdateVapiPhoneNumberDTO` has no such field, so the
diff ignores it on an existing number — comparing it would report drift that can never be
resolved.

## `main.json` — the BYO route, dormant

Registering PalmLeaf's own number with Vapi needs a SIP trunk (Twilio Elastic SIP, per
`Docs/reference/telephony.md` §2), which is deferred: the pilot forwards to `grace-line.json`
instead, and Twilio re-enters only for SMS (GATE-09) or a porting decision. Until
`GRACE_SIP_TRUNK_CREDENTIAL_ID` exists, this file skips with a "waiting on configuration"
notice.

## What resolves at deploy time

| Placeholder | Source | Notes |
|---|---|---|
| `${GRACE_ASSISTANT_ID}` | `platform/vapi/.lock.json` → `assistantId` | **Not** an environment variable. The only id certain to be real is the one the last apply recorded; a hand-typed one could bind a live number to the wrong assistant. |
| `${GRACE_MAIN_LINE_NUMBER}` | environment | E.164, per telephony.md §5 |
| `${GRACE_SIP_TRUNK_CREDENTIAL_ID}` | environment — Vapi credential for the SIP trunk | `CreateByoPhoneNumberDTO` requires it |
| `${GRACE_FRONT_DESK_NUMBER}` | environment | Optional: absence prunes `fallbackDestination` rather than blocking the file |

Applied numbers are recorded in `.lock.json` under `phoneNumberIds`.

## The kill switch is not here

Turning Grace off is a RingCentral-side action — the manager unforwards the number
(telephony.md §3.1), or `make rc-kill` disables the `grace-*` answering rule. Deleting or
unbinding the Vapi number would leave callers hearing a failure instead of a human, so nothing
in this directory implements a stop.
