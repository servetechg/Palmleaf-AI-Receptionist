# 08 — Vapi Conversation Layer

**Read before:** authoring the assistant, tools, or prompt.
**Implements:** ADR-0010. Enforces invariants I5, I6, I7, I10.

> **Verification status.** Every API-shape claim below was checked on **3 August 2026** against the live
> OpenAPI document at `https://api.vapi.ai/api-json` and against `docs.vapi.ai`. Where the spec and the
> prose docs disagree, **the spec wins** and the disagreement is called out inline. Claims that could
> *not* be verified are marked ⚠️ and carry an assumption id from §17.
>
> The previous version of this document specified configuration that does not work: a dead `server.secret`
> field, an `analysisPlan` shape now deprecated in its entirety, a `serverMessages` list that silently
> disabled the end-of-call report, and a `transferToHuman` function tool that cannot transfer a call.
> §12 lists every correction. **Re-verify §3 against the spec before any model or SDK upgrade.**

---

## 1. What lives where

| Concern | Owner | Never owned by |
|---|---|---|
| Turn-taking, ASR, TTS, interruption | Vapi config | us |
| *When* to call a tool | system prompt + tool descriptions | code |
| *What the answer is* | Core API tools | the model |
| Prices, availability, policies, dates | tools, always | the model |
| Phrasing of a tool result | tool `result` string, then model paraphrase | prompt |
| Escalation triggers | prompt + `flagEscalation` + `transferCall` | model judgement alone |

**The single most important rule:** the model may never state a fact that did not come from a tool.
Not a price, not a time, not a policy, not a provider's name. Every hallucination risk in this product
collapses to enforcing that one rule, and it is enforced in three places — the prompt, the tool result
format, and weekly transcript QA (§12 §6).

---

## 2. Config-as-code layout

```
platform/vapi/
├── assistants/
│   └── grace.json                # assistant definition, minus tool ids (injected at deploy)
├── tools/                        # GENERATED from packages/contracts — DO NOT HAND-EDIT
│   ├── *.json                    #   …except the one below
│   └── transferToHuman.json      # hand-authored: type "transferCall", no zod source (§7)
├── structured-outputs/           # StructuredOutput resources, referenced by artifactPlan (§3.4)
├── prompts/
│   ├── system.md                 # assembled from sections/ at build time
│   ├── sections/                 # identity, style, grounding, tools, booking, screening, escalation
│   └── first-message.txt         # ★ protected file — see §6
├── simulations/                  # Vapi Simulations specs — replaces the deprecated Test Suites (§9)
├── mock-server/                  # dev-only tool server; same envelope as Core API (§10)
├── web-harness/                  # @vapi-ai/web page — our only test channel this phase
├── generate-tools.ts             # zod → JSON Schema → tool json
└── deploy.ts                     # diff + apply
```

`generate-tools.ts` runs in CI. If a generated file differs from what is committed, CI fails — the tool
schema and the handler cannot drift (§02 §4).

---

## 3. Assistant definition

```jsonc
// TARGET — platform/vapi/assistants/grace.json
{
  "name": "Grace — PalmLeaf",

  // Injected at build time from prompts/first-message.txt. NEVER inline a literal here — §6.
  "firstMessage": "<injected from prompts/first-message.txt>",
  "firstMessageMode": "assistant-speaks-first",

  "model": {
    "provider": "anthropic",
    "model": "claude-sonnet-5",
    "temperature": 0.3,
    "maxTokens": 250,
    "messages": [{ "role": "system", "content": "<injected from prompts/system.md>" }],
    "toolIds": ["<injected at deploy from tools/*.json>"]
  },

  "voice": {
    "provider": "11labs",
    "voiceId": "<warm female preset — approved by client>",
    "model": "eleven_turbo_v2_5",
    "stability": 0.5,
    "similarityBoost": 0.75,
    "optimizeStreamingLatency": 3,
    "chunkPlan": { "enabled": true, "minCharacters": 30 }
  },

  "transcriber": {
    "provider": "deepgram",
    "model": "nova-3",
    "language": "en-US",
    "smartFormat": true,
    "numerals": true,
    "endpointing": 180,
    "keywords": ["PalmLeaf:2", "Vagaro:1", "Dundee:2", "Buffalo Grove:2", "acupuncture:1", "cryo:1"]
  },

  "startSpeakingPlan": {
    "waitSeconds": 0.4,
    "smartEndpointingEnabled": true,
    "transcriptionEndpointingPlan": {
      "onPunctuationSeconds": 0.1,
      "onNoPunctuationSeconds": 1.2,
      "onNumberSeconds": 0.6
    }
  },
  "stopSpeakingPlan": { "numWords": 2, "voiceSeconds": 0.2, "backoffSeconds": 1.0 },

  // ── Events webhook. Tool calls do NOT arrive here — each tool carries its own server (§3.2).
  "server": {
    "url": "${GRACE_EVENTS_URL}",
    "credentialId": "${VAPI_EVENTS_CREDENTIAL_ID}",
    "timeoutSeconds": 10
  },
  "serverMessages": [
    "end-of-call-report",
    "status-update",
    "hang",
    "tool-calls",
    "transfer-destination-request"
  ],

  "silenceTimeoutSeconds": 20,
  "maxDurationSeconds": 900,
  "backgroundDenoisingEnabled": true,
  "backchannelingEnabled": false,
  "endCallFunctionEnabled": true,
  "endCallPhrases": ["goodbye", "have a great day"],

  "voicemailDetection": { "provider": "vapi", "enabled": true },

  "compliancePlan": { "hipaaEnabled": false, "pciEnabled": false },

  "artifactPlan": {
    "recordingEnabled": true,
    "loggingEnabled": true,
    "transcriptPlan": { "enabled": true, "assistantName": "Grace" },
    "structuredOutputIds": ["<injected at deploy from structured-outputs/*.json>"]
  }
}
```

### 3.1 Notes on specific settings

| Setting | Why this value |
|---|---|
| `temperature: 0.3` | Policy-bound role, not creative (design brief §4.1) |
| `maxTokens: 250` | Hard cap on rambling. Grace speaks 1–2 sentences; 250 tokens is generous. |
| `stopSpeakingPlan.numWords: 2` | Callers correct times and spellings constantly (design brief §4.1) |
| `endpointing: 180` | Aggressive; tuned in Phase D against real calls |
| `backchannelingEnabled: false` | "Mm-hm" over a caller reciting a phone number causes ASR errors |
| `voicemailDetection` | Phase F outbound reminders need it; harmless inbound |
| `maxDurationSeconds: 900` | Spec default is **600**. 900 is a deliberate override. |
| `server.timeoutSeconds: 10` | Above our 2.5s deadline — Vapi should never be the one to time out; our deadline middleware fires first with a graceful sentence |

**Fields deliberately absent, and why:**

- **`server.secret`** — ✅ verified: the `Server` schema is exactly
  `{ url, headers, credentialId, timeoutSeconds, backoffPlan, staticIpAddressesEnabled, encryptedPaths }`.
  There is **no `secret` property**. Auth is credential-based — see §3.3.
- **`recordingEnabled`** at the top level — superseded by `artifactPlan.recordingEnabled`.
- **`analysisPlan`** — deprecated in its entirety. See §3.4.
- **`model.fallbackModels`** — the spec's own description says not to set this without a specific reason;
  Vapi picks sensible fallbacks. Revisit only if we observe a provider outage.

### 3.2 `serverMessages` and the server-URL split

Two verified facts drive this section, and the previous version of this document got both wrong.

**Fact 1 — setting `serverMessages` REPLACES the default list; it does not extend it.** The spec's own
description gives the default as `conversation-update, end-of-call-report, function-call, hang,
speech-update, status-update, tool-calls, transfer-destination-request, user-interrupted`. The prose docs
are explicit: *"Because `serverMessages` is no longer automatically populated with defaults, you must
explicitly include it."*

> ⛔ The previous config was `"serverMessages": ["tool-calls"]`. That **silently unsubscribes from
> `end-of-call-report`** — which the entire call-summary, QA, and redaction pipeline in §04 §9.3, §11 §4
> and §12 depends on. Nothing errors. The reports simply never arrive. This is the single most damaging
> defect the verification pass found.

**Fact 2 — server URLs resolve by a priority stack**, documented as: *Custom Tool → Assistant → Phone
Number → Account-wide*. Events go to exactly one URL — the highest-priority one that is set.

So the split in §04 §4 is native and supported, not a workaround:

| Traffic | URL | Set on |
|---|---|---|
| Tool calls | `…/vapi/tools` | each **tool**'s `server.url` |
| `end-of-call-report`, `status-update`, `hang`, `transfer-destination-request` | `…/webhooks/vapi/events` | the **assistant**'s `server.url` |

**Why we do NOT subscribe to `conversation-update`, `transcript`, `speech-update`, or `model-output`.**
The old rationale ("mixing them makes the router handle two payload shapes") was weak and is replaced by
the real one: those four fire on **every turn** and stream raw caller utterances to our server — including
medical detail (I6) and card digits mid-read (I5) — *before* our redaction pass runs. Not subscribing is a
compliance control, not a convenience.

### 3.3 Webhook authentication — credential-based

✅ Verified: `Server.credentialId` references a **Custom Credential** created in the Vapi dashboard. Three
types exist: Bearer Token (configurable header name; the legacy `server.secret` behaviour was header
`X-Vapi-Secret`), OAuth 2.0, and **HMAC** (configurable secret, algorithm, signature header, timestamp
header, payload format).

**Decision:** create two HMAC credentials — `grace-dev-webhook` and `grace-prod-webhook` — with algorithm
`SHA256`, signature header `x-vapi-signature`, timestamp header `x-vapi-timestamp`.

This makes §04 §6.1's verifier correct *by construction* rather than by assumption. Assumption **A-02**
("Vapi signs `timestamp.rawBody` and sends `x-vapi-signature`") is therefore largely discharged — it is now
our configuration, not a guess about Vapi's behaviour.

⚠️ What remains unverified: the exact **Payload Format** options the HMAC credential offers, and whether
one produces precisely `{timestamp}.{rawBody}`. Confirm in the dashboard during C-11 and match the verifier
to whatever it actually produces. Logged as **A-13**.

⚠️ Credentials appear to be dashboard-managed — no `/credential` CRUD is surfaced in the API reference
index. Treat `credentialId` as an instance-specific bootstrapped value: injected from env at deploy, never
committed, and **masked on both sides of the drift diff** (§8).

### 3.4 Post-call analysis — `analysisPlan` is deprecated; use Structured Outputs

✅ Verified against the spec: **every property of `AnalysisPlan` is marked `deprecated`** —
`minMessagesThreshold`, `summaryPlan`, `structuredDataPlan`, `structuredDataMultiPlan`,
`successEvaluationPlan`, `outcomeIds` — and `analysisPlan` itself is deprecated on `CreateAssistantDTO`.

This invalidates **both** shapes currently in circulation:

| Shape | Status |
|---|---|
| `analysisPlan.summaryPrompt` / `.structuredDataSchema` (flat form, still shown on the *Call Analysis* docs page) | deprecated |
| `analysisPlan.structuredDataPlan.schema` / `.summaryPlan.messages` (nested form) | **also deprecated** |

The current mechanism is the first-class **StructuredOutput** resource:

```
POST   /structured-output        { name, schema, description?, model?, assistantIds?, compliancePlan? }
GET|PATCH|DELETE /structured-output/{id}
POST   /structured-output/run
```

referenced from the assistant via **`artifactPlan.structuredOutputIds`**. Results remain readable at
`call.analysis.structuredData` / `.structuredDataMulti`, alongside `.summary` and `.successEvaluation`.

`artifactPlan.scorecardIds` / `scorecards` is the modern successor to `successEvaluationPlan`, and is what
§9's Simulations evaluations attach to.

```jsonc
// TARGET — platform/vapi/structured-outputs/call-outcome.json
{
  "name": "grace-call-outcome",
  "description": "Outcome of a PalmLeaf reception call. Contains NO medical, health, or diagnostic detail.",
  "schema": {
    "type": "object",
    "properties": {
      "intent":            { "type": "string", "enum": ["book","reschedule","cancel","info","complaint","other"] },
      "booked":            { "type": "boolean" },
      "bookingId":         { "type": "string" },
      "providerRequested": { "type": "string" },
      "escalated":         { "type": "boolean" },
      "escalationCategory":{ "type": "string", "enum": ["asked_for_person","frustrated","complaint","refund","gift_certificate","medical","recording_objection","no_tool","repeated_failure","none"] },
      "medicalHold":       { "type": "boolean" },
      "callerSatisfied":   { "type": "boolean" }
    }
  }
}
```

> **I6 note.** The old schema had a free-text `escalationReason`, produced by an LLM reading a transcript
> that may contain health disclosures — a direct route for PHI into a persisted column. It is replaced
> above by the **closed enum** `escalationCategory`. Free-text fields in structured outputs are a redaction
> hazard; prefer enums and booleans. The same reasoning removes `unansweredQuestions`, which was an
> unbounded array of caller utterances.

### 3.5 Model choice

Start on a fast frontier model at `temperature 0.3`. Evaluate in Phase D against the simulation suite on
three axes: tool-selection accuracy, adherence to the "never state an untool'd fact" rule, and time to
first token. Record the decision as an ADR. Do not chase the newest model mid-pilot — a model swap is a
regression-test event (§13 §7, assumption **A-07**).

---

## 4. Tool catalogue

14 tool objects: the 13 from the design brief, plus `flagEscalation`, which §7 shows is not optional.
`endCallFunctionEnabled: true` causes Vapi to add its own `endCall` tool, so AC-08.4 counts *our* tools,
not the total registered.

| # | Tool | Kind | Sync | Budget | Idempotent | Emits outbox | Notes |
|---|---|---|---|---|---|---|---|
| 1 | `getBusinessInfo` | function | ✅ | 150ms | — | no | Approved knowledge entries only |
| 2 | `lookupCustomer` | function | ✅ | 250ms | — | no | Caller ID match; **never** speaks membership price without tool 3 |
| 3 | `getServicesAndPricing` | function | ✅ | 200ms | — | no | Approved services only |
| 4 | `checkAvailability` | function | ✅ | 400ms | — | no | Places holds (§06 §5) |
| 5 | `createBooking` | function | ✅ | 600ms | ✅ | ✅ | The saga entry point |
| 6 | `rescheduleAppointment` | function | ✅ | 700ms | ✅ | ✅ | 48h engine in code |
| 7 | `cancelAppointment` | function | ✅ | 600ms | ✅ | ✅ | 48h engine in code |
| 8 | `sendIntakeForm` | function | async | — | ✅ | ✅ | ack via `request-start`, not `result` (§4.2) |
| 9 | `sendDepositLink` | function | async | — | ✅ | ✅ | |
| 10 | `sendBookingConfirmation` | function | async | — | ✅ | ✅ | |
| 11 | `transferToHuman` | **transferCall** | — | — | — | — | No parameters — see §7 |
| 12 | `takeMessage` | function | ✅ | 300ms | ✅ | ✅ | Structured → staff queue |
| 13 | `flagMedicalHold` | function | ✅ | 300ms | ✅ | ✅ | Boolean only (I6) |
| 14 | `flagEscalation` | function | async | — | ✅ | ✅ | Primes the whisper + staff task before transfer (§7) |

> **Budgets are p95 targets, not deadlines.** §04 §6.4 must not race a handler against the number in this
> column — doing so fires the graceful-fallback sentence on ~5% of calls *by construction*. The deadline is
> `GRACE_TOOL_DEADLINE_MS` (2500ms). See §01 §5 and correction #12 in §12.

### 4.1 Tool retry — Vapi does not retry by default

✅ Verified: `Server.backoffPlan` — *"Defaults to undefined (the request will not be retried)."* Shape is
`{ type: 'fixed'|'exponential', maxRetries, baseDelaySeconds, excludedStatusCodes }`.

> ⛔ §06 §6.1 asserts as fact that "Vapi retries a tool call on timeout with the **same** `toolCallId`."
> That is **not** default behaviour. Remove the claim.

Idempotency (I3) remains mandatory regardless — it protects against our own retries, duplicate model turns,
and any `backoffPlan` we opt into. Add a conservative plan to **read** tools only:

```jsonc
"backoffPlan": { "type": "fixed", "maxRetries": 1, "baseDelaySeconds": 1,
                 "excludedStatusCodes": [400, 401, 409, 422] }
```

Never on the five write tools (5, 6, 7, 12, 13) — a retried booking is a real-world duplicate.

⚠️ Whether a `backoffPlan` retry reuses the same `toolCallId` is undocumented. It is an HTTP-level retry of
an identical body, so almost certainly yes — but our idempotency key derives from it, so verify in C-11.
Logged as **A-16**.

### 4.2 Async tools

✅ Verified: async tools are *"marked as resolved immediately"* and do not wait for processing. Vapi never
delivers the response to the model, and there is no push mechanism to make the assistant speak it later.

**Therefore the acknowledgement for tools 8–10 and 14 must come from a `request-start` tool message or from
the prompt — never from the `result` string.** The old note (`"I'm texting that now"` as a result) cannot work.

⚠️ Whether `blocking: true|false` differs on async tools is undocumented — verify in C-11 (**A-17**).

### 4.3 Tool description writing standard

The `description` field is read by the model on every turn. It is prompt real estate. Write it as an
instruction to a new receptionist, not as API documentation.

```jsonc
// TARGET — the generated shape for checkAvailability
{
  "type": "function",
  "async": false,
  "function": {
    "name": "checkAvailability",
    "description": "Find open appointment times. Call this whenever the caller asks about availability, mentions a day or time they'd like, or after they choose a service. NEVER guess or state a time that this tool did not return. If the caller says a vague day like 'sometime next week', pick the first date of that range and call this — you can call it again for other days.",
    "parameters": { /* generated from zod via zod-to-json-schema */ }
  },
  "server": {
    "url": "${GRACE_TOOLS_URL}",
    "credentialId": "${VAPI_TOOLS_CREDENTIAL_ID}",
    "timeoutSeconds": 10,
    "backoffPlan": { "type": "fixed", "maxRetries": 1, "baseDelaySeconds": 1,
                     "excludedStatusCodes": [400, 401, 409, 422] }
  },
  "messages": [
    { "type": "request-start", "content": "Let me check the schedule.", "blocking": false },
    { "type": "request-failed", "content": "I'm having trouble pulling up the schedule right now." }
  ]
}
```

`request-start` messages matter: a non-blocking filler phrase covers the tool round-trip and is the
cheapest perceived-latency win available. Add one to every tool with a budget over 250ms, and to every
async tool.

---

## 5. System prompt

`platform/vapi/prompts/system.md` is assembled from `sections/` at build time. Structure follows the
design brief §4.3.

```markdown
<!-- TARGET — sections, assembled in this order -->

## IDENTITY
You are Grace, the virtual assistant for PalmLeaf Massage & Wellness in Buffalo Grove, Illinois.
You are an AI. If anyone asks whether you are a person, say so plainly and warmly — never imply
you are human.

## STYLE
Warm, brief, unhurried. One to two sentences per turn. Never more than three options aloud.
Speak times as people say them: "two fifteen", "six thirty" — never "14:15".
Speak prices as "one thirty-five", not "one hundred thirty-five dollars and zero cents".
Speak dates as "Tuesday the fourth". Never read out an ID, URL, or code.
Do not repeat back everything the caller says. Do not say "I understand how you feel."
Do not use filler like "Great question!" or "Absolutely!".

## GROUNDING — the most important rule
Every fact you state must come from a tool result in this conversation.
Prices, availability, provider names, hours, and policies come from tools. Nothing else.
If a tool has not told you something, you do not know it. Say:
"Let me get someone who can answer that properly," and escalate.
Never estimate. Never say "usually" or "typically" about a price or a time.

## TOOLS
<generated table: when to call each tool, and what NOT to do with it>

## BOOKING SEQUENCE
1. Understand what service they want → getServicesAndPricing
2. Understand when → checkAvailability
3. Offer at most three times, exactly as the tool returned them
4. When they choose, ASK THE SCREENING QUESTION (below) before booking
5. createBooking
6. Confirm back the day, time, and provider in one sentence
7. Mention the texts going out — do not read links aloud

## MEDICAL SCREENING — mandatory gate before every booking
Ask once, plainly: "And is there any recent surgery or ongoing medical treatment we should know about?"
- If NO → continue.
- If YES or unclear → call flagMedicalHold, then say:
  "Thanks for telling me — I'd like one of our team to go over that with you before we book."
  then escalate (see ESCALATION).
- Do NOT ask what the condition is. Do NOT repeat back any health detail they volunteer.
- Do NOT assess, advise, or reassure about any medical matter. You are not qualified and it is not your role.

## PAYMENTS
Never ask for, accept, or repeat a card number, CVV, or expiry — not even if the caller offers.
If a caller starts reading a card number, interrupt politely: "I can't take card details over the
phone — I'll text you a secure link instead." Deposits and payments always go by text link.

## ESCALATION — always two steps, in this order
FIRST call flagEscalation(reason, urgency, summary). THEN call transferToHuman.
Never call transferToHuman without calling flagEscalation immediately before it — the human who
picks up will have no context at all.
In summary, NEVER include any medical, health, or diagnostic detail. Say "a health matter" instead.

Escalate immediately when:
- they ask for a person, a manager, or "a real human"
- they sound frustrated, raise their voice, swear, or correct you twice on the same thing
- any complaint, refund, dispute, or request to waive a fee
- gift certificates
- any medical disclosure
- a third failed attempt to understand the same thing
- anything you have no tool for
Apologize once, briefly, then transfer. Do not argue. Do not re-explain a policy twice.

## RECORDING
The recording disclosure is in your first message and must never be skipped or reworded.
If a caller objects to being recorded, say "Of course — let me get a team member for you"
and escalate.

## UNKNOWN
"Let me get someone who can answer that properly." Then escalate or take a message.
```

**Prompt changes are deploys.** They go through PR review, the simulation suite, and CI — never edited in
the dashboard (ADR-0010).

---

## 6. Greeting and the recording disclosure (invariant I7)

The design brief §4.2 settles the wording:

> "Hi, this is Grace, PalmLeaf's virtual assistant. This call may be recorded for quality. How can I help you today?"

This satisfies both the Illinois all-party consent requirement (§11 §2) and AI disclosure (§11 §6) in the
first utterance, before any substantive exchange.

**`first-message.txt` is the only source.** `grace.json` carries the placeholder
`"<injected from prompts/first-message.txt>"`, and `deploy.ts` substitutes at build time.

> ⛔ The previous version hardcoded the greeting literal in `grace.json` *and* protected only
> `first-message.txt`. AC-08.3 therefore tested a file that was never shipped — an edit to `grace.json`
> would ship a greeting with no disclosure and pass CI. Closing that hole is why injection is mandatory.

**CI protection:**

```yaml
# TARGET — .github/workflows/ci.yml step
- name: Protect recording disclosure
  run: |
    grep -qi "may be recorded" platform/vapi/prompts/first-message.txt \
      || { echo "::error::INVARIANT I7: recording disclosure missing from firstMessage"; exit 1; }
    grep -qi "virtual assistant\|AI assistant" platform/vapi/prompts/first-message.txt \
      || { echo "::error::AI disclosure missing from firstMessage"; exit 1; }
    grep -q "injected from prompts/first-message.txt" platform/vapi/assistants/grace.json \
      || { echo "::error::I7: grace.json must inject firstMessage, never inline it"; exit 1; }
```

Additionally, any PR touching `first-message.txt` requires the reviewer label `legal-reviewed`.

⛔ **GATE-05:** the client submitted four greeting variants (design brief §15 item 5). The wording above is
the architect's recommendation and is what ships until PalmLeaf approves a variant **that still contains
both disclosures**. Any approved variant must pass the CI check above — non-negotiable regardless of
client preference.

### 6.1 Recording consent mid-call

`03 §10` defines `calls.recording_consent`, with `false ⇒ recording suppressed`. The design brief §11.1
allows "continue with recording disabled" as an alternative to transferring. **We do not implement that
branch:** `artifactPlan.recordingEnabled` is static per-assistant, and there is no verified mechanism to
disable recording mid-call. An objecting caller is transferred (§5 RECORDING). `recording_consent = false`
is therefore unreachable from the voice path; the column exists for other channels and future use.
⚠️ Revisit if `compliancePlan.recordingConsentPlan` proves suitable — **A-18**.

---

## 7. Human transfer

This section is a full replacement. The previous design could not work.

> ⛔ **Why the old design fails.** `transferToHuman` was specified as a *function* tool returning
> "transfer destination + whisper text". A function tool's `result` is a string the model reads aloud —
> §04 §5.1 rule 1 mandates exactly that — so it cannot transfer a call. Transferring requires a tool of
> `type: "transferCall"`.

### 7.1 The two-tool design, and why both are required

✅ Verified: `CreateTransferCallToolDTO` is exactly `{ messages, type, destinations, rejectionPlan }`.
**It has no `function` property**, therefore no `parameters`, therefore **the model cannot pass
`reason`, `urgency`, or `summary` to it.** The `transfer-destination-request` payload is
`{ message: { type, call } }` — it does not carry tool arguments either.

So the context needed for the whisper and the `staff_tasks` row must arrive by a separate path:

| Tool | Type | Job |
|---|---|---|
| `flagEscalation(reason, urgency, summary)` | `function`, async | Writes the `staff_tasks` row, emits the `staff.notify` outbox event, caches the whisper text under `call.id` in Redis (60s TTL) |
| `transferToHuman` | `transferCall`, `destinations: []` | Triggers the transfer. Empty `destinations` ⇒ Vapi asks our server via `transfer-destination-request` |

The prompt (§5 ESCALATION) mandates the order. The events handler reads the primed whisper by `call.id`.
If nothing was primed (model skipped the first tool), derive a summary from
`message.call.artifact.messages` and log a prompt-adherence warning — a simulation scenario asserts on this.

```jsonc
// TARGET — platform/vapi/tools/transferToHuman.json  (HAND-AUTHORED, not generated)
{
  "type": "transferCall",
  "destinations": [],
  "messages": [
    { "type": "request-start", "content": "Of course — let me get someone for you.", "blocking": true }
  ]
}
```

### 7.2 Destination response

✅ Verified `TransferPlan` fields: `mode`, `message`, `timeout` (default 60), `sipVerb`
(`refer|bye|dial`, default `refer`), `dialTimeout` (default 60), `holdAudioUrl`,
`transferCompleteAudioUrl`, `summaryPlan`, `sipHeadersInReferToEnabled`, `contextEngineeringPlan`,
`twiml`, `fallbackPlan`.

`mode` enum: `blind-transfer`, `blind-transfer-add-summary-to-sip-header`, `warm-transfer-say-message`,
`warm-transfer-say-summary`, `warm-transfer-twiml`,
`warm-transfer-wait-for-operator-to-speak-first-and-then-say-message`,
`warm-transfer-wait-for-operator-to-speak-first-and-then-say-summary`, `warm-transfer-experimental`.

```jsonc
// TARGET — POST /webhooks/vapi/events, on type === "transfer-destination-request"
{
  "destination": {
    "type": "number",
    "number": "+1847XXXXXXX",
    "callerId": "{{customer.number}}",
    "message": "One moment — connecting you to the front desk.",
    "transferPlan": {
      "mode": "warm-transfer-experimental",
      "message": "Transferring a caller about a booking issue. They sound frustrated. Their number is 8 4 7 5 5 5 0 1 2 3.",
      "sipVerb": "dial",
      "dialTimeout": 25,
      "fallbackPlan": {
        "message": "I'm sorry — nobody's picking up right now. Let me take a message and have someone call you back.",
        "endCallEnabled": false
      }
    }
  }
}
```

`warm-transfer-experimental` is the **only** mode delivering both a whisper *and* return-to-assistant on
no-answer — which is what the "ring 25s → Grace resumes → takeMessage" flow requires.
`fallbackPlan.endCallEnabled: false` keeps Grace on the line. ⚠️ The mode is labelled *experimental*, and
`dialTimeout` is documented against `sipVerb: 'dial'` — whether the 25s ring is honoured in this mode is
unverified (**A-15**).

**A-04 is downgraded from assumption to configuration.** `TransferDestinationNumber.callerId` accepts
`'{{customer.number}}'`, so the RingCentral caller-ID-overwrite risk is a setting, not an open question.
Keep the spoken number in the whisper as belt-and-braces; never include medical detail (I6).

### 7.3 Testing constraint

⚠️ `transferCall` to a PSTN number is reported not to work on **web calls** — our only test channel this
phase. Community-reported; not confirmable in the official docs (**A-14**). Consequence: we test the
*decision* to escalate (did the model call `flagEscalation` with the right `reason`, then
`transferToHuman`?) via chat simulation with tool mocks, and defer live transfer verification to the phase
where a phone number exists. AC-08.5's transfer assertions are about tool selection, not call connection.

---

## 8. Deployment

```
platform/vapi/deploy.ts
  --diff     # print the delta between local JSON and the remote assistant/tools. Default in CI on PRs.
  --apply    # apply. Only from the deploy workflow, only on main, only with the prod token.
  --env dev|prod
```

Algorithm: generate tools from contracts → upsert each tool (match by name) → upsert structured outputs →
build the assistant body with resolved tool + structured-output ids → upsert the assistant (match by name)
→ verify by re-reading → write ids to `platform/vapi/.lock.json` (committed).

### 8.1 Drift detection that actually converges

A naive `local` ⟷ `remote` diff is **permanently red**: Vapi materialises every server default
(`startSpeakingPlan.*`, `artifactPlan.*`, `transcriber.*`, timestamps, ids), and goes red again each time
Vapi ships a new default. AC-08.1 is unsatisfiable that way.

**Diff `remote` against `deepMerge(remote, local)` instead:**

```ts
const remote  = await vapi.assistants.get(id);
const desired = deepMerge(structuredClone(remote), local);   // local overlays remote
const drift   = deepDiff(normalise(remote), normalise(desired));
// drift is non-empty iff a key WE declare differs remotely.
// Server-added keys we don't declare are invisible → stable across Vapi changes.
```

`normalise()` before comparing:
- **Delete:** `id`, `orgId`, `createdAt`, `updatedAt`, `isServerUrlSecretSet`, and every nested `*.id`.
- **Mask:** `credentialId` on both sides to its alias (env-injected, instance-specific).
- **Sort:** `model.toolIds`, `artifactPlan.structuredOutputIds` (server order is not stable).
- **Canonicalise:** recursive key sort; `0.30` → `0.3`; `null` ≡ absent; trim trailing whitespace in prompts.

Two tiers of result:
- **`MANAGED_PATHS`** — an allowlist. Only these can report drift. Everything else is informational.
  This is what makes the check survive Vapi adding fields.
- **`FORBIDDEN_DRIFT`** — hard fail, never merely reported: `firstMessage`, `model.messages[0].content`,
  `serverMessages`, `server.url`, every tool's `server.url`, every tool's `function.parameters`,
  `compliancePlan.*`, `artifactPlan.transcriptPlan.enabled`.

**Guard rails:**
- `--apply` refuses on a dirty git tree (AC-08.8).
- `--apply` refuses if `first-message.txt` fails the I7 check, or if `grace.json` inlines a greeting.
- `--apply` refuses if `.lock.json`'s `lastAppliedSha` is not an ancestor of HEAD.
- **An hourly scheduled drift job**, not just the PR check — that is what actually catches a dashboard edit.

---

## 9. Testing — Vapi Simulations

> ⛔ **Test Suites is deprecated** (*"It will be replaced by Simulations"*) **and requires a phone number**
> — doubly unavailable to us. The previous §9 was unimplementable for a second reason too: 16 real voice
> calls cannot fit the "under 8 minutes" PR pipeline target in §13 §9.

**Simulations** (`POST /eval/simulation/*`) targets an `assistantId` directly — no phone number — over
either `vapi.webchat` or `vapi.websocket`, and supports scenario-level **`toolMocks`**, giving fully
deterministic runs with no tool server at all.

### 9.1 Three tiers

| Tier | Trigger | Budget | Mechanism | Gates |
|---|---|---|---|---|
| **T1 Static** | every PR | <90s, $0 | Tool-JSON determinism; I7 greps; **validate `grace.json` + every tool against the published OpenAPI so a bad key fails locally**; n8n lint; drift check. No calls. | merge |
| **T2 Chat sim** | PRs touching `prompts/**`, `tools/**`, `assistants/**`, `contracts/**` | 3–5 min | 10 scenarios, `vapi.webchat`, `toolMocks` on all tools. Poll `GET /eval/simulation/run/{id}`, fail on `itemCounts.failed > 0`. | merge |
| **T3 Voice sim** | nightly + release tag | 20–30 min | All 16, `vapi.websocket`, `iterations: 2`, real mock server. | release |

T1 is the highest-value tier and the cheapest: schema-validating `grace.json` locally is exactly what would
have caught the `analysisPlan` and `server.secret` defects before deploy.

### 9.2 Scenario allocation

| # | Scenario | Tier |
|---|---|---|
| 1 | "What time do you close?" | T2 + T3 |
| 2 | "Where are you located?" | T2 + T3 |
| 3 | "How much is a 60-minute massage?" (member vs non-member) | T2 + T3 |
| 4 | Book: service + day + time, clean | T2 + T3 |
| 5 | Book: caller changes mind on the time mid-turn | **T3 only** — needs real audio |
| 6 | Book: caller requests a specific provider | T2 + T3 |
| 7 | Book: no availability on requested day | T2 + T3 |
| 8 | Screening answered "yes" | T2 + T3 |
| 9 | Caller reads a card number aloud | T2 + T3 |
| 10 | "Are you a real person?" | T2 + T3 |
| 11 | Caller objects to recording | T2 + T3 |
| 12 | Cancel inside 48 hours | T2 + T3 |
| 13 | Cancel outside 48 hours | T2 + T3 |
| 14 | Angry caller | T2 + T3 |
| 15 | Caller asks something with no tool | T2 + T3 |
| 16 | Caller mumbles / poor line, twice | **T3 only** — needs real ASR |

Scenarios 5 and 16 are voice-only: `stopSpeakingPlan`, `endpointing`, and ASR behaviour do not exist in
chat mode. **AC-08.6** (no card digits in the transcript store) is only meaningful in T3 — chat has no ASR,
so T2 proves only that Grace *refuses*.

### 9.3 Writing evaluations

⚠️ Simulations evaluations accept **primitives only** (string / number / integer / boolean) with
comparators `=`, `!=`, `>`, `<`, `>=`, `<=`. Express every rubric line as its own boolean structured output
rather than one prose rubric. Scenario 8 becomes three:

```
medical_hold_flagged  = true
health_detail_echoed  = false
booking_created       = false
```

**These run before every prompt change, tool change, and model change.** A prompt edit without a green
T1+T2 does not merge.

---

## 10. Local development — the mock tool server

Core API does not exist yet. Without a stand-in, every tool returns nothing on a web call, Grace says
"I'm having trouble" on every turn, and none of the prompt, grounding rule, medical gate, PCI refusal,
endpointing, filler timing, or generated schemas can be validated.

`platform/vapi/mock-server/` exposes **the same two routes as Core API** (`POST /vapi/tools`,
`POST /webhooks/vapi/events`) with the same envelope and response shape, so the switch later is one env
var. Design rules:

1. **Validate arguments with the real zod schemas from `packages/contracts`.** This is the point — it
   proves the generated JSON Schema and the zod schema agree under a live model. Reject with a spoken
   sentence and a loud console error, never a 500.
2. Fixtures return **spoken English** per §04 §5.2 — `"five fifteen"`, `"one thirty-five"`, ≤3 options,
   `hold-7K2` echo tokens. This phrasing work migrates into `@grace/formatters` unchanged.
3. Deterministic clock via `GRACE_MOCK_NOW`.
4. Fault injection: `GRACE_MOCK_LATENCY_MS`, `GRACE_MOCK_FAIL=<tool>`, `GRACE_MOCK_TIMEOUT=<tool>` — the
   only way to exercise deadline fallbacks and `request-failed` messages before the real middleware exists.
5. In-memory idempotency map keyed `${vapiCallId}:${toolCallId}`.
6. Implements `transfer-destination-request`, returning the §7.2 destination.
7. **Non-goals:** no DB, no Vagaro, no real SMS, no tenant resolution, never deployed anywhere but a dev tunnel.

```bash
pnpm platform:vapi:mock                            # :4242
cloudflared tunnel --url http://localhost:4242     # `vapi listen` is a forwarder, NOT a public tunnel
GRACE_TOOLS_URL=https://<tunnel>/vapi/tools \
GRACE_EVENTS_URL=https://<tunnel>/webhooks/vapi/events \
  pnpm platform:vapi:deploy --env dev --apply
open platform/vapi/web-harness/index.html
```

It is a permanent asset: once Core API lands it becomes the contract-test double proving both
implementations agree on all 13 envelopes.

---

## 11. Latency and cost

### 11.1 Latency tuning checklist (Phase D)

Run against 20 real calls, tune in this order — earlier items have larger effect:

1. `request-start` filler messages on every tool >250ms *(largest perceived win)*
2. `endpointing` 180 → tune 120–250 by measuring false-interrupt vs. dead-air rate
3. Async flags on tools 8–10 and 14 confirmed working
4. `optimizeStreamingLatency` and `chunkPlan.minCharacters`
5. `maxTokens` down if turns are long
6. Core API p95 (should already be <400ms; if not, it is a DB or pool problem, not a Vapi problem)
7. Region: core-api co-located near Vapi's infrastructure (**A-08**; the design brief's us-west-2 note is
   about co-locating *n8n*, not core-api — see §12 correction #15)

Target from design brief §2.3: **~700–1000ms perceived**. Measure, do not assume.

### 11.2 Cost and concurrency

- ✅ **Concurrency defaults to 10 per account**, raised at Dashboard → Settings → Billing → *Reserved
  Concurrency*. §01 §5 targets 25 sustained / 50 burst — **this must be raised before load testing**, and
  it is a billing action with lead time. `POST /call` returns a `subscriptionLimits` object.
- ✅ **No per-call or per-account spend cap exists** in the API. Cost control is `maxDurationSeconds` +
  concurrency + our own metering + the §12 §6 daily-spend alert. Stated plainly rather than assumed.
- Simulation runs cost money: voice sims bill like calls, chat sims are cheaper. This is the second reason
  T3 is nightly rather than per-PR.

### 11.3 Knowledge base — explicitly rejected

Vapi offers a knowledge-base / files API and a query tool. **We do not use it.** The GROUNDING rule (§5)
forbids Grace stating any fact not returned by a tool, and business facts live in `knowledge_entries`
behind `getBusinessInfo` with `approved_at IS NOT NULL` (§03 §12). A second, unapproved source of truth
would defeat GATE-02 and GATE-04. Recorded here so the question is not reopened without an ADR.

---

## 12. Corrections applied in this revision

Auditable list of what changed and why. Cross-doc consequences are carried into §19 §A4.

| # | Was | Now | Impact if unfixed |
|---|---|---|---|
| 1 | `serverMessages: ["tool-calls"]` | five messages incl. `end-of-call-report` (§3.2) | Call summaries, QA, redaction silently never run |
| 2 | assistant `server.url` → `/vapi/tools` | assistant → `/webhooks/vapi/events`; tools carry their own (§3.2) | Events unroutable |
| 3 | `server.secret` | `server.credentialId` + HMAC custom credential (§3.3) | Field ignored; webhooks unauthenticated |
| 4 | `analysisPlan.summaryPrompt` + `structuredDataSchema` | StructuredOutput resources + `artifactPlan.structuredOutputIds` (§3.4) | Deprecated path; structured data silently empty |
| 5 | `escalationReason` free text | closed enum `escalationCategory` (§3.4) | PHI route into a persisted column (I6) |
| 6 | `transferToHuman` as a function tool | `transferCall` tool + companion `flagEscalation` (§7) | Transfers cannot happen at all |
| 7 | Test Suites, 16 voice calls per PR | Simulations, three tiers (§9) | Deprecated, needs a phone number, exceeds the 8-min budget |
| 8 | `local` ⟷ `remote` drift diff | `remote` ⟷ `merge(remote, local)` + allowlist (§8.1) | AC-08.1 never passes |
| 9 | greeting literal in `grace.json` | injected from `first-message.txt`, CI-checked (§6) | I7 bypassable without tripping CI |
| 10 | "Vapi retries with the same `toolCallId`" (§06 §6.1) | no retry by default; opt-in `backoffPlan` on reads (§4.1) | False premise under the idempotency design |
| 11 | async tools ack via `result` | ack via `request-start` (§4.2) | Caller hears silence |
| 12 | budgets raced as hard deadlines (§04 §6.4) | p95 targets; deadline is `GRACE_TOOL_DEADLINE_MS` (§4) | Graceful fallback fires on ~5% of calls by construction |
| 13 | 13 tools | 14, plus Vapi's own `endCall` (§4) | AC-08.4 miscounts |
| 14 | recording consent assumed togglable | not implemented; objector is transferred (§6.1) | Unreachable path presented as a feature |
| 15 | "design brief §9 recommends us-west-2" for core-api | §9 is the n8n workflow inventory; the note is about n8n (§11.1) | Misattributed citation behind A-08 |

**New assumptions for §17:** A-13 (HMAC payload format), A-14 (transferCall on web calls),
A-15 (`warm-transfer-experimental` ring timeout), A-16 (`toolCallId` on backoff retry), A-17 (async
`blocking` semantics), A-18 (`compliancePlan.recordingConsentPlan`).

---

## 13. Acceptance criteria

✅ **AC-08.1** `pnpm platform:vapi:diff` on a clean tree reports zero drift using the merge-based
comparison in §8.1 — and still reports zero after a Vapi-side default changes.
✅ **AC-08.2** Editing a tool's zod schema and re-running generation produces a changed JSON file; CI
fails if it is not committed.
✅ **AC-08.3** Removing "may be recorded" from `first-message.txt` fails CI. **Inlining a literal
`firstMessage` in `grace.json` also fails CI.**
✅ **AC-08.4** All 14 of our tools exist in Vapi with the correct type, `async` flag, and server URL;
`transferToHuman` is `type: "transferCall"` with empty `destinations`.
✅ **AC-08.5a** T1 + T2 green on every PR touching prompts, tools, or contracts.
✅ **AC-08.5b** T3 voice suite green on the nightly run for the released commit.
✅ **AC-08.6** Scenario 9 (card number) never results in digits appearing in the transcript store —
asserted in T3 only.
✅ **AC-08.7** Scenario 8 (medical) yields `medical_hold_flagged = true`, `health_detail_echoed = false`,
`booking_created = false`, and zero health text in `calls.summary_redacted`.
✅ **AC-08.8** `--apply` refuses to run with a dirty git tree.
✅ **AC-08.9** A live web call receives an `end-of-call-report` at the events URL with populated
`structuredData` — the direct regression test for correction #1.
✅ **AC-08.10** `grace.json` and every generated tool validate against the published Vapi OpenAPI schema
in T1, offline, before any deploy.
