# 03 — Vapi Layer

**Completed:** 3 August 2026 · **Commit:** `e8db9cd`
**Status:** deployed and live on dev. Assistant `51fd2d26-b00f-42a7-964d-adef6437ddaf`.

---

## What was built

```
platform/vapi/
├── assistants/grace.json          the assistant, corrected against the live spec
├── tools/                         13 generated + transferToHuman + endCall
├── structured-outputs/            grace-call-outcome
├── prompts/
│   ├── first-message.txt          ★ I7-protected; the only source of the greeting
│   ├── sections/                  8 hand-written sections
│   └── system.md                  GENERATED — do not edit
├── generate-tools.ts              zod → JSON Schema → tools/*.json
├── build-prompt.ts                sections + generated TOOLS table → system.md
├── validate.ts                    T1 offline gate
├── deploy.ts                      merge-based drift, lock file, guard rails
├── lib/{vapi-client,drift}.ts
└── .lock.json                     committed — deployed ids + lastAppliedSha
```

---

## The assistant

| Setting | Value | Why |
|---|---|---|
| model | `claude-sonnet-5` @ temp 0.3 | policy-bound role, not creative |
| maxTokens | 250 | hard cap on rambling |
| voice | 11labs `sarah`, `eleven_turbo_v2_5` | placeholder until the client approves |
| transcriber | deepgram `nova-3`, endpointing 180 | keywords cannot contain spaces — "Buffalo Grove" had to become two entries |
| `serverMessages` | 5 entries **including `end-of-call-report`** | setting this replaces the defaults |
| `server.url` | the **events** webhook | tools carry their own URL; Vapi resolves by priority stack |
| `artifactPlan.structuredOutputIds` | `grace-call-outcome` | replaces the deprecated `analysisPlan` |
| `compliancePlan` | both false | HIPAA needs an Enterprise add-on; a commercial decision |

**Not subscribed** to `conversation-update`, `transcript`, `speech-update`, `model-output` —
those fire every turn and would stream raw caller utterances, including medical detail (I6)
and card digits mid-read (I5), to our server *before* redaction. That is a compliance control,
not a performance choice.

---

## The 15 tools

13 generated from zod + 2 hand-authored Vapi tool types.

| # | Tool | Kind | Budget | Notes |
|---|---|---|---|---|
| 1 | `getBusinessInfo` | function | 150ms | approved entries only |
| 2 | `lookupCustomer` | function | 250ms | scoped to the calling number |
| 3 | `getServicesAndPricing` | function | 200ms | the only source of a price |
| 4 | `checkAvailability` | function | 400ms | ≤3 slots, `request-start` filler |
| 5 | `createBooking` | function | 600ms | medical gate enforced server-side |
| 6 | `rescheduleAppointment` | function | 700ms | fee decided by the tool, not the model |
| 7 | `cancelAppointment` | function | 600ms | model may never waive a fee |
| 8–10 | `send*` | function, **async** | — | ack via `request-start`, never `result` |
| 11 | `transferToHuman` | **transferCall** | — | hand-authored, `destinations: []` |
| 12 | `takeMessage` | function | 300ms | no health detail |
| 13 | `flagMedicalHold` | function | 300ms | boolean only, no free text anywhere (I6) |
| 14 | `flagEscalation` | function, async | — | deliberately silent; transfer speaks next |
| 15 | `endCall` | **endCall** | — | hand-authored; replaces the removed assistant flag |

Read tools carry a conservative `backoffPlan` (1 retry). **Write tools carry none** — a
retried booking is a real-world duplicate.

---

## The system prompt

`system.md` is assembled from 8 sections; the `## TOOLS` table is **generated from the
registry**, so the prompt cannot describe a tool that does not exist or miss one that does.

Sections: identity · style · grounding · **TOOLS (generated)** · booking sequence ·
medical screening · payments · escalation · recording/unknown.

Two places where the prompt does real safety work:

- **GROUNDING** — every fact must come from a tool result. No estimating, no "usually",
  no filling a gap with a plausible answer.
- **ESCALATION** — mandates `flagEscalation` *then* `transferToHuman`, in that order, every
  time. Without the first call the person picking up answers blind, because a `transferCall`
  tool carries no arguments.

---

## Deployment

`deploy.ts --env dev|prod --diff|--apply`. Order: tools → structured outputs → assistant
(so ids exist before the assistant references them) → verify → write `.lock.json`.

### Drift detection that converges

The naive approach cannot work: Vapi materialises every server default, so `local` vs
`remote` is permanently red and goes red again each time Vapi adds a default.

Instead: **diff `remote` against `deepMerge(remote, local)`.** Drift is non-empty *iff a key
we actually declare differs remotely*; server-added keys we do not declare are invisible.

Plus `normalise()` (strip volatile ids/timestamps, mask `credentialId`, sort unordered
arrays, canonicalise), a `MANAGED_PATHS` allowlist, and a `FORBIDDEN_DRIFT` hard-fail set
covering `firstMessage`, the system prompt, `serverMessages`, every `server.url`, every tool's
`parameters`, and `compliancePlan`.

**Verified:** `--diff` immediately after `--apply` reports `✓ no drift` against the live
assistant. That is AC-08.1, and it is the test the old design could never have passed.

### Guard rails

- `--apply` to prod refuses on a dirty git tree
- refuses if `first-message.txt` fails the I7 check, or if `grace.json` inlines a greeting
- `.lock.json` records `lastAppliedSha`

---

## Defects found by actually deploying

The doc review caught what was wrong on paper. Calling the API found four more.

| # | Defect | Where it surfaced | Now caught by |
|---|---|---|---|
| 1 | `silenceTimeoutSeconds`, `backchannelingEnabled`, `endCallFunctionEnabled` are not properties of `CreateAssistantDTO`; `backgroundDenoisingEnabled` renamed | `validate.ts`, offline | validator |
| 2 | `endCall` is a tool type, not a flag → 15 tools | `validate.ts`, offline | validator |
| 3 | Vapi rejects `anyOf` — what a constrained `.nullable()` renders to | **deploy-time 400** | `generate-tools.ts`, offline |
| 4 | Vapi rejects scalar `const` — what `z.literal()` renders to | **deploy-time 400** | `generate-tools.ts`, offline |

Plus two smaller ones: transcriber keywords cannot contain spaces, and `voicemailDetection`
has no `enabled` property.

Items 3 and 4 now fail offline with the fix instruction attached, e.g.:

```
createBooking: parameter "properties.lastName" renders as `anyOf`, which Vapi rejects.
    Cause: a nullable field with a constraint, e.g. .max(60).nullable().
    Fix:   use .optional() instead of .nullable() on tool INPUT schemas.
```

---

## Not done in this area

- The assistant points at `placeholder.invalid` — see `05-pending-and-blocked.md`
- No HMAC webhook credential created (needs the dashboard; A-13 undischarged)
- `voiceId: "sarah"` is a placeholder, not client-approved (GATE-05)
- Vapi concurrency still at the default 10; the target is 25/50 (doc 18 §1.3)
- No Simulations authored yet — `simulations/` is empty
