# palmleaf-grace

**Grace** — the AI phone receptionist for PalmLeaf Massage & Wellness in Buffalo Grove, Illinois.

A caller phones the clinic. Grace answers, understands what they want, checks real availability,
books the appointment, and hands off to a person the moment anything needs judgement she should not
be making. She never invents a price, never takes a card number, and never records a health detail.

| | |
|---|---|
| **What is built and proven** | [`Docs/Completed/00-STATUS.md`](Docs/Completed/00-STATUS.md) |
| **Plain-language progress log** | [`Docs/Completed/DAILY-LOG.md`](Docs/Completed/DAILY-LOG.md) |
| **Full architecture** | [`Docs/plans/00-INDEX.md`](Docs/plans/00-INDEX.md) |
| **Account setup** | [`Docs/plans/18-platform-setup.md`](Docs/plans/18-platform-setup.md) |

> **Current state, stated plainly.** Everything below is built, deployed and verified — but
> **Grace has not yet taken a live call.** Her tools point at a placeholder address, so a real call
> would fail. One setup step away; see [§9](#9-what-is-not-done-yet).

---

## 1. How the system works

### The one rule everything else serves

**Grace may never state a fact that did not come from a tool.** Not a price, not a time, not a
policy, not a provider's name. If a tool has not told her something, she does not know it and she
hands off to a person.

Every design decision below exists to enforce that.

### The two paths

```
          ┌──────────────────────────────────────────────┐
 caller ──►  VAPI — speech in, speech out, decides WHEN   │
          │         to call a tool. Owns no facts.        │
          └───────────────────┬──────────────────────────┘
                              │  HTTPS, one call per tool
                              │  ── caller is waiting: fast path ──
          ┌───────────────────▼──────────────────────────┐
          │  TOOL SERVER — answers WHAT the fact is       │
          │  today: the mock server (this repo)          │
          │  later:  Core API + Postgres                 │
          └───────────────────┬──────────────────────────┘
                              │  writes a queue row, returns immediately
                              │  ── nobody is waiting: slow path ──
          ┌───────────────────▼──────────────────────────┐
          │  n8n — staff alerts, escalation timers,       │
          │        digests. Never on the call path.       │
          └──────────────────────────────────────────────┘
```

**Why the split matters.** Voice is real-time: silence over about a second sounds broken. So
anything the caller waits for must be fast and local. Anything that can happen afterwards — texts,
staff alerts, escalation timers — goes to n8n, where slowness is harmless.

n8n is never called while a caller is on the line. That is a hard rule, not a preference.

### What lives where

| Layer | Owns | Never owns |
|---|---|---|
| **Vapi** | Listening, speaking, interruption, deciding *which* tool to call | Any fact about the business |
| **Tool server** | The actual answer: prices, availability, bookings | Phrasing decisions beyond the sentence it returns |
| **n8n** | Notifications, escalation timing, reports | Anything a caller waits for; anything transactional |

---

## 2. Repository map

Every file and folder, and why it exists.

### `src/grace_contracts/` — the shared vocabulary

The single source of truth for what Grace's tools accept and return. Everything else is generated
from here, so nothing can drift out of sync.

| File | Purpose |
|---|---|
| `tools/shared.py` | Reusable field types — phone numbers, dates, booking references — plus the two hard rules about what Vapi will not accept |
| `tools/read_tools.py` | Tools 1–4: look things up. No side effects, safe to retry |
| `tools/write_tools.py` | Tools 5–7: book, reschedule, cancel. Never retried — a repeated booking is a real duplicate |
| `tools/messaging_tools.py` | Tools 8–10: send a text. Run in the background |
| `tools/escalation_tools.py` | Tools 12–14: take a message, flag a health disclosure, hand off to a person |
| `tools/registry.py` | **The registry.** One row per tool. Adding a tool means editing this file and nothing else |
| `vapi/envelope.py` | The exact message format Vapi and our server exchange |

### `src/grace_platform/` — the tooling

Scripts that turn the contracts into live configuration and keep it honest.

| File | Purpose | When it runs |
|---|---|---|
| `vapi/generate_tools.py` | Turns the registry into the tool definitions Vapi needs | `make vapi-build`, and in CI as a check |
| `vapi/build_prompt.py` | Assembles Grace's instructions from `prompts/sections/`, injecting a generated tool table | `make vapi-build` |
| `vapi/validate.py` | Checks our config against Vapi's own published rules — **offline, under a second** | Every commit, before every deploy |
| `vapi/deploy.py` | Pushes config to Vapi, or reports what differs | `make vapi-diff` / `make vapi-apply` |
| `vapi/lib/client.py` | Talks to the Vapi API | used by the above |
| `vapi/lib/drift.py` | Decides whether what is running still matches the code | used by deploy |
| `vapi/mock_server/server.py` | Stand-in for the real backend so Grace can be tested today | `make vapi-mock` |
| `vapi/mock_server/fixtures.py` | Realistic canned answers — prices, appointment slots | used by the mock |
| `vapi/mock_server/speech.py` | Turns numbers into speech: "two fifteen", "one thirty-five" | used by the mock; moves into the real backend later |
| `n8n/lint.py` | 15 structural checks on workflows before they ship | Every commit |
| `n8n/deploy.py` | Pushes workflows to n8n, or reports what differs | `make n8n-diff` / `make n8n-apply` |
| `n8n/lib/client.py` | Talks to the n8n API | used by deploy |

### `platform/` — the configuration that gets deployed

This is what actually becomes live settings on Vapi and n8n. It is checked into git so every change
is reviewable and reversible — nothing is configured by clicking in a dashboard.

| Path | Purpose | Hand-edited? |
|---|---|---|
| `vapi/assistants/grace.json` | Grace herself — voice, model, timing, which events we receive | ✏️ yes |
| `vapi/prompts/first-message.txt` | 🔒 **Protected.** Her opening line, containing the legally required recording and AI disclosures | ✏️ yes, with review |
| `vapi/prompts/sections/*.md` | Her instructions, in eight parts | ✏️ yes |
| `vapi/prompts/system.md` | The assembled instructions | ⚙️ generated |
| `vapi/tools/*.json` | The 15 tool definitions | ⚙️ generated (2 exceptions below) |
| `vapi/tools/transferToHuman.json` | Transfer tool — a different Vapi type, no schema source | ✏️ yes |
| `vapi/tools/endCall.json` | Hang-up tool — same reason | ✏️ yes |
| `vapi/structured-outputs/call-outcome.json` | What we record about a call afterwards | ✏️ yes |
| `vapi/.lock.json` | The live IDs of everything deployed. Committed, so deployments are traceable in git | ⚙️ generated |
| `vapi/web-harness/index.html` | Browser page for talking to Grace. **The only JavaScript in the project**, because it runs in a browser | ✏️ yes |
| `n8n/workflows/WF-*.json` | The three live workflows | ✏️ yes |
| `n8n/credentials.example.json` | Which credentials must exist. Never real values | ✏️ yes |

### Root

| File | Purpose |
|---|---|
| `Makefile` | Every command. `make check` runs the same gate CI runs |
| `pyproject.toml` | Dependencies and the strict type/lint settings |
| `.github/workflows/ci.yml` | What runs on every push |
| `.mcp.json.example` | Template for agent access to Vapi and n8n. Real file is gitignored |
| `tests/` | Automated tests |

---

## 3. Grace's 15 tools, by category

A "tool" is Grace's only way to learn a fact or change something. She decides *when* to call one;
the server decides *what the answer is*.

### 🔍 Looking things up (safe to retry)

| Tool | What it does | When Grace calls it |
|---|---|---|
| `getBusinessInfo` | Hours, address, parking, policies | Caller asks a factual question |
| `lookupCustomer` | Recognises the caller by their number | Early in the call, to greet by name |
| `getServicesAndPricing` | Services, durations, prices | **Before stating any price.** She may not quote from memory |
| `checkAvailability` | Real open appointment slots | Caller mentions a day or time |

### 📝 Changing a booking (never retried)

| Tool | What it does | Safeguard |
|---|---|---|
| `createBooking` | Books the appointment | **Refuses unless the health screening question was asked.** Enforced by the server, not just the instructions |
| `rescheduleAppointment` | Moves an appointment | The *tool* decides any fee — Grace may not |
| `cancelAppointment` | Cancels | Same. She can never waive a fee |

A repeated booking would be a real duplicate in someone's calendar, so these three are the only
tools with retries deliberately switched off.

### 💬 Sending a text (runs in the background)

`sendIntakeForm` · `sendDepositLink` · `sendBookingConfirmation`

These finish after Grace has moved on, so she says what she is doing ("I'm texting that now") rather
than waiting. **Payment always goes by text link** — she will interrupt a caller who starts reading
a card number.

### 🤝 Handing off to a person

| Tool | What it does |
|---|---|
| `takeMessage` | Takes a callback message |
| `flagMedicalHold` | Records **that** a health matter was mentioned — never **what**. There is deliberately no free-text field |
| `flagEscalation` | Captures why she is handing off, so the person answering has context |
| `transferToHuman` | The actual transfer |
| `endCall` | Hangs up |

**`flagEscalation` and `transferToHuman` always fire together, in that order.** The transfer tool
carries no information at all — without the first call, whoever picks up answers blind.

---

## 4. Where to see each piece in a dashboard

Everything below is live right now and can be inspected.

### Vapi — `dashboard.vapi.ai`

| What you built | Where to see it | Live ID |
|---|---|---|
| Grace herself | **Assistants** → `Grace — PalmLeaf [dev]` | `51fd2d26-b00f-42a7-964d-adef6437ddaf` |
| Her instructions | Same page → *Model* → System Prompt | generated from `prompts/` |
| Her opening line | Same page → *First Message* | from `first-message.txt` |
| The 15 tools | **Tools** — all 15 listed | see `platform/vapi/.lock.json` |
| Post-call summary shape | **Structured Outputs** → `grace-call-outcome` | `3e25e0f5-1cf1-49a5-8c02-7ee10e92f948` |
| Calls once placed | **Calls** → transcript, recording, outcome | — |

### n8n — `palmleafmassage.app.n8n.cloud`

| What you built | Where to see it | Live ID |
|---|---|---|
| Error handler | **Workflows** → `[dev] WF-00 Global Error Handler` | `TskMxWsdNPdtyzwz` |
| Staff escalation | **Workflows** → `[dev] WF-12 Escalation & Alerting` | `Nig7UzGSTwVZuFLg` |
| On-call chase-up | **Workflows** → `[dev] WF-18 On-call Escalation` | `IvXEhYoHdxT3e7oA` |
| Runs, once triggered | **Executions** | — |

All three are tagged **`managed:git`** and **`env:dev`**. That tagging is how the deploy script knows
what it owns — anything untagged (like the pre-existing `AI Agent workflow`) is invisible to it and
will never be touched.

### Reading the dev/prod naming

The `[dev]` prefix is not decoration. One n8n account serves both environments, separated by name
prefix, tags, and webhook path. Production workflows would appear as `[prod] WF-12 …`. The reasoning
and the risks are recorded in **ADR-0013**.

---

## 5. How something gets from an idea to live

```
  edit src/ or platform/
        │
        ▼
  make vapi-build          regenerate tool definitions + instructions
        │
        ▼
  make check               typecheck · lint · tests · I7 · schema · workflow lint
        │
        ▼
  git commit               a reviewable change
        │
        ▼
  make vapi-diff           what would change on the live account?
        │
        ▼
  make vapi-apply          push it
        │
        ▼
  make vapi-diff           must now say "no drift"
```

**Nothing is configured by hand in a dashboard.** A dashboard edit shows up as drift on the next
check and is treated as a fault, not a shortcut — because it is a change nobody reviewed and git
cannot undo.

### Every command

```bash
make install          # one-time setup
make check            # the full gate, exactly as CI runs it

make vapi-build       # regenerate tools + instructions from the registry
make vapi-validate    # offline check against Vapi's live rules
make vapi-diff        # does the live assistant still match the code?
make vapi-apply       # deploy   (ENV=prod for production)
make vapi-mock        # run the stand-in backend locally

make n8n-lint         # 15 workflow checks
make n8n-diff         # does the live workflow still match the code?
make n8n-apply        # deploy
```

---

## 6. What happens on every commit and push

Defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Target: under 90 seconds, no cost,
no calls to Vapi.

| Check | What it prevents |
|---|---|
| Typecheck (strict) | Type errors — these become live-call failures |
| Lint + format | Style drift |
| Tests | Regressions in how Grace speaks numbers and dates |
| 🔒 **Disclosure check** | The recording and AI disclosures being removed, **and** the greeting being inlined somewhere the first check would miss |
| Generated files current | Tool definitions silently disagreeing with the schemas |
| Instructions current | The prompt disagreeing with the actual tools |
| **Validate against live Vapi rules** | Using a setting Vapi has removed or deprecated |
| Workflow lint | 15 structural faults, including one that deploys fine then fails at runtime |
| Secret scan | Credentials being committed |

The Vapi validation runs against the **current** published API, not a cached copy — so if Vapi
deprecates something we use, CI tells us rather than a caller discovering it.

A separate job checks, on every push, whether the deployed configuration still matches git.

### Where history is maintained

- **Code and configuration:** git. Every deploy is traceable to a commit through `.lock.json`, which
  records the exact commit that was last applied.
- **What was built and verified:** [`Docs/Completed/`](Docs/Completed/00-STATUS.md) — one file per
  area, each stating what was proven and with what evidence.
- **Day-to-day progress:** [`Docs/Completed/DAILY-LOG.md`](Docs/Completed/DAILY-LOG.md).
- **Decisions and their reasoning:** ADRs in
  [`Docs/plans/01-architecture-foundation.md`](Docs/plans/01-architecture-foundation.md). A decision
  that gets reversed is marked superseded rather than quietly rewritten.

---

## 7. The safety rules built into the system

These are enforced by code and CI, not by hoping the model behaves.

| Rule | How it is enforced |
|---|---|
| **Every call opens with the recording + AI disclosure** | Protected file, two CI checks, and the deploy refuses without it |
| **No card numbers, ever** | Instructions interrupt the caller; payment only by text link |
| **Health disclosures record a flag, never a detail** | The tool has no free-text field, and the post-call summary uses fixed options only |
| **The health question is asked before every booking** | The booking tool *refuses* without it — server-side, not just instructed |
| **Grace never invents a price or a time** | She has no source except the tools |
| **Raw caller speech never streams to our server** | We deliberately do not subscribe to the per-sentence events that would carry it |

---

## 8. Getting set up

```bash
make install
make check
```

Platform credentials and agent access: [`Docs/plans/18-platform-setup.md`](Docs/plans/18-platform-setup.md).

To talk to Grace locally you also need a public tunnel, because Vapi has to reach your machine:

```bash
make vapi-mock                                    # terminal 1
cloudflared tunnel --url http://localhost:4242    # terminal 2, copy the https URL

GRACE_TOOLS_URL=https://<tunnel>/vapi/tools \
GRACE_EVENTS_URL=https://<tunnel>/webhooks/vapi/events \
  make vapi-apply

# then open platform/vapi/web-harness/index.html
```

---

## 9. What is not done yet

Full detail: [`Docs/Completed/05-pending-and-blocked.md`](Docs/Completed/05-pending-and-blocked.md).

| | |
|---|---|
| **No live call has been placed** | Grace points at a placeholder address. The tunnel above is the fix |
| **No workflow has actually run** | The escalation path is deployed but untriggered |
| **The `/internal/notify/*` endpoints do not exist** | n8n calls them; they arrive with Core API |
| **Core API, Postgres, workers** | Out of scope this phase — the mock server stands in |
| **Six more n8n workflows** | Digests, reports, QA sampling |
| **Automated conversation tests** | Designed, not yet written |

Blocked on outside access: Vagaro, RingCentral (so no phone number), Stripe, Google Calendar, and
A2P 10DLC registration for texting.

---

## 10. Stack

Python 3.12+, Pydantic v2, httpx, pytest, ruff, mypy strict, `uv`.

The only JavaScript is the browser test page, because it runs in a browser.

This reverses an earlier TypeScript decision — see **ADR-0014**, which records why the original
reasoning was thin, what actually decided it, and the four defects the port surfaced.
