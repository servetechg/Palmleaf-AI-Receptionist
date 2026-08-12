# 06 — Platform Account Setup Runbook

**Status:** Active
**Read before:** the first `make vapi-apply` or `make n8n-apply`, and when onboarding a new developer or a new tenant.
**Implements:** ADR-0010, ADR-0013
**Enforces:** I7, I9 (as relaxed by ADR-0013)
**Last verified:** 2026-08-04 against the live Vapi org and the n8n Cloud instance.

> **In one paragraph:** this document covers the **manual, click-through, one-time** steps that
> config-as-code cannot perform — creating accounts, minting credentials, raising quotas, and
> standing up the local development loop. Everything here is a prerequisite for the automated
> deploys in [03-vapi-layer](03-vapi-layer.md) §8 and [04-n8n-layer](04-n8n-layer.md) §10.3. It
> deliberately does **not** cover anything CI can do for itself.
>
> **Nothing in this document should ever be committed with real values.** Every secret lands in an
> environment variable or a CI secret. See §7.

---

## 1. Current state (4 August 2026)

| Platform | Access | Notes |
|---|---|---|
| **Vapi** | ✅ full | Org contains one sample assistant (`Riley`), zero tools |
| **n8n Cloud** | ✅ full | `palmleafmassage.app.n8n.cloud`, pay-as-you-go. One untagged workflow, one OpenAI credential |
| Vagaro | ⛔ blocked | GATE-01, GATE-03 |
| RingCentral | ⛔ blocked | GATE-11 — no SIP trunk, therefore **no phone number** |
| Stripe | ⛔ blocked | GATE-08 |
| Google Calendar | ⛔ blocked | GATE-07 |
| Twilio | ⛔ blocked | GATE-09 (A2P 10DLC) |
| Reporting Postgres | ⛔ not yet hosted | Needs a hosted instance n8n Cloud can reach. §6. |

**Consequence for this phase:** testing happens over **web calls only** ([03-vapi-layer](03-vapi-layer.md) §10). No phone number is
provisioned, and the transfer path cannot be verified end to end (**A-14**).

---

## 2. Vapi

### 2.1 API keys

Dashboard → **Organization Settings → API Keys**.

| Key | Used by | Where it lives |
|---|---|---|
| **Private** | `deploy.py`, MCP server, CI | `VAPI_API_KEY` env var; `VAPI_API_KEY` GitHub secret |
| **Public** | the browser web-call harness ([03-vapi-layer](03-vapi-layer.md) §10) | `VAPI_PUBLIC_KEY` env var — safe to expose client-side |

The private key is org-wide and unscoped. Treat it as a root credential.

### 2.2 Webhook credentials (required before any deploy)

[03-vapi-layer](03-vapi-layer.md) §3.3: `Server.secret` does not exist. Authentication is a **Custom Credential** referenced by
`credentialId`. Create two, one per environment:

| Name | Type | Settings |
|---|---|---|
| `grace-dev-webhook` | HMAC | Algorithm `SHA256`, Signature Header `x-vapi-signature`, Timestamp Header `x-vapi-timestamp` |
| `grace-prod-webhook` | HMAC | identical |

Copy each resulting `credentialId` into `VAPI_EVENTS_CREDENTIAL_ID` / `VAPI_TOOLS_CREDENTIAL_ID` for the
matching environment. They are instance-specific, never committed, and masked on both sides of the drift
diff ([03-vapi-layer](03-vapi-layer.md) §8.1).

⚠️ **While you are in this screen, record the exact `Payload Format` option chosen** and confirm whether
it produces `{timestamp}.{rawBody}`. [core-api](../reference/core-api.md) §6.1's verifier must match whatever it actually produces. This is
assumption **A-13** and it is discharged here, not in code.

### 2.3 Concurrency — raise it before load testing

✅ Verified: Vapi defaults to **10 concurrent calls per account**. [01-architecture](01-architecture.md) §5 targets **25 sustained / 50
burst**.

Dashboard → **Settings → Billing → Reserved Concurrency (Call Lines)**. This is a billing action with
lead time — raise it in Phase C, not the week of the load test. `POST /call` returns a
`subscriptionLimits` object; assert against it in the load-test setup.

✅ Also verified: **no per-call or per-account spend cap exists.** Cost control is `maxDurationSeconds`,
concurrency, our own metering, and the [observability](../reference/observability.md) §6 daily-spend alert. Do not assume a cap will save you.

### 2.4 What NOT to configure

- **No third-party chat integration.** Out of scope; staff notification is `/internal/notify/*`.
- **No phone number.** Not this phase (§0). When telephony unblocks, follow [telephony](../reference/telephony.md) §2 for the BYO-SIP trunk.
- **No knowledge base / files.** Explicitly rejected in [03-vapi-layer](03-vapi-layer.md) §11.3 — it would be a second, unapproved
  source of truth and would defeat GATE-02/GATE-04.
- **No dashboard edits to the assistant.** ADR-0010. Drift is a CI failure ([03-vapi-layer](03-vapi-layer.md) §8.1).

---

## 3. n8n Cloud

### 3.1 Two tokens, different jobs

Do not conflate these — they are separate credentials with separate lifecycles.

| Token | Where | Used by | Env var |
|---|---|---|---|
| **MCP Access Token** | Settings → Instance-level MCP | Claude Code / agent authoring | `N8N_MCP_TOKEN` |
| **Public API key** | Settings → n8n API | `deploy.py`, `export.py`, CI | `N8N_API_KEY` |

Also record the **MCP server URL** shown on the Instance-level MCP page (`N8N_MCP_URL`) — copy it
verbatim rather than constructing it; the path varies by n8n version.

⚠️ The MCP token is displayed **once**. Losing it means revoke + regenerate.

⚠️ Verified on the live instance: the API key's `scopes` include `workflow:create/update/delete/publish`
and credential access across **everything**. Scoped keys are Enterprise-only. One key reaches dev and
prod alike — this is the core risk ADR-0013 accepts and is why the hourly drift job is mandatory.

### 3.2 Tags — create these three first

`deploy.py` filters on tags, and `GET /api/v1/tags` currently returns **empty**. Create:

```
env:dev        env:prod        managed:git
```

Nothing tagged `managed:git` is touched by anything other than CI. The existing untagged
`AI Agent workflow` is therefore ignored by the deploy filter (AC-09.11) — leave it alone.

### 3.3 Credentials to create by hand

Credentials are **never** deployed ([04-n8n-layer](04-n8n-layer.md) §6.2). Create each once, per environment, and reference by name.
`deploy.py` resolves `__CRED__:<alias>` → name → id at push time.

| Alias | Type | Dev name | Prod name | Used by |
|---|---|---|---|---|
| `vapi` | `httpHeaderAuth` | `PalmLeaf Vapi (dev)` | `PalmLeaf Vapi (prod)` | WF-20/21/22 — **the only one needed today** |
| `core-api` | `httpHeaderAuth` | `PalmLeaf Core API (dev)` | `PalmLeaf Core API (prod)` | WF-12/18 — dormant until Core API exists |
| `postgres` | `postgres` | `PalmLeaf Postgres (dev)` | `PalmLeaf Postgres (prod)` | **Deferred** — see §6 |

**Create `vapi` first.** It is the single prerequisite for the three reporting workflows, and
therefore for the n8n instance doing anything observable at all. Set it as Header Auth with name
`Authorization` and value `Bearer <VAPI_API_KEY>`.

The `core-api` credential carries `Authorization: Bearer $GRACE_INTERNAL_API_TOKEN` for the
`/internal/*` calls, and is inert until those endpoints exist.

n8n deliberately holds **no third-party credentials**. Every outbound notification goes through Core
API's `/internal/notify/*`, so 10DLC, opt-out and consent enforcement live in one place and cannot be
bypassed ([04-n8n-layer](04-n8n-layer.md) §3.4). Adding a Twilio node here would reintroduce exactly that bypass.

✅ `PalmLeaf Core API (dev)` already exists (`MLPOdQtg1zcSlYUJ`) with a **placeholder token** — rotate it
when Core API is real.

**No Twilio credential.** [04-n8n-layer](04-n8n-layer.md) §3.4: staff SMS goes through `POST /internal/notify/sms` so the messaging
adapter's 10DLC, consent, and STOP/HELP enforcement cannot be bypassed. An n8n Twilio node would defeat
GATE-09 silently.

⚠️ Hand-created credentials sit outside the secret manager and outside the current+previous rotation
window promised in [05-security-and-compliance](05-security-and-compliance.md). Rotating them is a manual, downtime-adjacent operation. Note it in the
runbook when Phase D scheduling is planned.

### 3.4 Plan-tier constraints

One instance serves both dev and prod (ADR-0013), so **concurrency and execution retention are shared**.
A dev test loop can consume prod's quota. Keep WF-16 (20 calls weekly) and any polling workflow
dev-disabled until the tier is raised. Never design a wait longer than execution retention ([04-n8n-layer](04-n8n-layer.md) §4.3).

---

## 4. MCP servers (agent authoring access)

Full step-by-step is in [EXECUTED-vapi-n8n-plan](../Completed/EXECUTED-vapi-n8n-plan.md) Step 0. Summary of the end state:

| Server | URL | Auth |
|---|---|---|
| `vapi` | `https://mcp.vapi.ai/mcp` | `Bearer ${VAPI_API_KEY}` |
| `vapi-docs` | `https://docs.vapi.ai/_mcp/server` | none |
| `n8n` | `${N8N_MCP_URL}` | `Bearer ${N8N_MCP_TOKEN}` |

`.mcp.json` uses `${VAR}` expansion so no secret is written to disk; it is gitignored, and
`.mcp.json.example` is committed with placeholders.

**Two facts that shape policy:**

- ✅ The **Vapi** MCP server has no `update_assistant` and no `create_tool`/`update_tool`. It physically
  cannot mutate existing config — which independently reinforces ADR-0010.
- ⚠️ The **n8n** MCP server **does** expose `publish_workflow`, and `search_workflows` sees every workflow
  regardless of the per-workflow "Available in MCP" setting. On one instance that is a live path to
  production, guarded by convention and detection only ([04-n8n-layer](04-n8n-layer.md) §5.2, §9).

### 4.1 Linux GUI-launch gotcha

Applications launched from a desktop dock do **not** read `~/.bashrc`. Environment variables exported
there reach terminal-launched processes only. Put credentials in `~/.config/environment.d/*.conf`
(`KEY=VALUE`, no `export`, no quotes, perms `600`) so the systemd user session exports them to GUI apps
too. Takes effect at next login.

Symptom if you skip this: MCP servers fail with *"'url' is not a valid URL"* (empty variable) or
*"401 rejected"* (stale value) even though the same variables resolve correctly in a terminal.

---

## 5. Local development loop

```bash
#1 — Mock tool server — stands in for Core API, validating args with the real Pydantic models
make vapi-mock                                     # :4242

#2 — Public tunnel. NOTE: `vapi listen` is a local forwarder, NOT a public URL — you still need this.
cloudflared tunnel --url http://localhost:4242

#3 — Deploy the dev assistant pointed at the tunnel
GRACE_TOOLS_URL=https://<tunnel>/vapi/tools \
GRACE_EVENTS_URL=https://<tunnel>/webhooks/vapi/events \
  make vapi-apply ENV=dev

#4 — Talk to Grace — the only test channel this phase
open platform/vapi/web-harness/index.html
```

Fault injection, for exercising the deadline fallbacks before Core API exists:

```bash
GRACE_MOCK_LATENCY_MS=1200 GRACE_MOCK_FAIL=checkAvailability make vapi-mock
```

---

## 6. Reporting Postgres — deferred, and how to turn it on

WF-20/21/22 write to **n8n Data Tables**, which work today with no setup at all. Postgres is the
durable path and is **not yet hosted**, for one mundane reason: n8n Cloud cannot reach a database
running on a laptop.

Nothing about this is designed-but-unbuilt — the node exists in each workflow, disabled, with its
query written ([04-n8n-layer](04-n8n-layer.md) §9). This section is the click-through that switches
it on:

| # | Step | Notes |
|---|---|---|
| 1 | Create a hosted Postgres | A **Neon** or **Supabase** free tier is sufficient at this volume |
| 2 | Run `platform/postgres/schema.sql` against it | Creates `call_metrics`, `call_samples`, `call_flags`. Idempotent — every statement is `IF NOT EXISTS` |
| 3 | Create the n8n credential `PalmLeaf Postgres (dev)` | Type `postgres`. Alias `postgres`, per §3.3 |
| 4 | Enable the "Archive to Postgres" node in WF-20, WF-21 and WF-22 | It is present and positioned; only `disabled` changes |
| 5 | `make n8n-apply` | The linter permits the placeholder while the node is disabled, and requires it resolved once enabled |

**Until step 3 is done, deploys still succeed.** That is deliberate: lint rule 14 permits an
unresolved `__CRED__:postgres` on a *disabled* node, so the half-wired integration ships without
weakening the unresolved-placeholder check anywhere else.

⚠️ **Grant the credential write access to those three tables only.** It is a reporting sink, not an
application database, and it should not be able to read anything it did not write.

### 6.1 Decision — 7 August 2026: one Hostinger box, no extra vendor

The reporting sink above is superseded by a single decision: **Postgres and the tool server both run
on one Hostinger VPS.** Not Neon, not a separate application host — one machine, one bill, one
vendor to manage.

This resolves what looked like a real cost: earlier drafts treated the tool server as a second
service needing its own host (~$5/month). It does not. It is another process beside the database on
a box that has to exist anyway, deployed by the same `docker compose` file that already runs
Postgres locally.

| Piece | Where it runs | Why not elsewhere |
|---|---|---|
| Postgres | Hostinger VPS | The mirror, the bookings, the exclusion constraint. n8n Data Tables cannot express the constraint |
| `grace_api` (tool server) | **Same VPS** | Vapi POSTs to it during a call; it needs a permanent URL and sub-second answers |
| n8n workflows | n8n Cloud (paid) | Everything after a call ends: reports, escalation, alerting, fan-out |
| Vapi | Vapi Cloud (paid) | The assistant, the voice, the phone line |

**Vapi hosts the assistant, not our logic** — every tool is an HTTP call *out* to a URL we own. That
URL becomes the Hostinger box instead of a laptop tunnel, which is what makes unattended operation
possible at all.

### 6.2 Staying inside Vagaro's 5,000 calls a month

The plan allows ~166 requests/day. The rule that keeps us well under it: **spend the API only on
what changes; keep what does not in Postgres.**

| Data | Changes | How it is kept current | Requests/day |
|---|---|---|---|
| Services, prices, staff list | Rarely — a menu change is a business decision | One sync a day, plus on demand | ~5 |
| Business hours, policies, knowledge answers | Almost never | Held in Postgres, edited by hand, `approved_at` gated | **0** |
| Appointments and cancellations | Constantly | **Vagaro webhooks push to us** — pushes cost us nothing | **0** |
| Appointments — safety net for a missed webhook | — | Poller every 30 minutes, not every 10 | ~48 |
| Nightly reconciliation | Once | Full re-read of the coming window | ~10 |

**Roughly 63 requests a day — about 1,900 a month against a 5,000 allowance**, leaving headroom for a
resync after an outage. Two choices do the work: webhooks are free because Vagaro pushes them, and
static content never costs a request at all.

⚠️ A 10-minute poller would alone be 144/day (~4,300/month) and leave almost no margin. 30 minutes is
the deliberate figure, and it is only a backstop — webhooks are the real path, arriving in under
five seconds.

---

## 7. Secret inventory

### 7.1 Developer machine

**Preferred: `.env` in the repository root**, copied from the committed `.env.example` template,
which lists every variable the project reads with what each one unlocks. The Makefile loads it
automatically; git ignores it. Full guidance in [10-access-and-credentials](10-access-and-credentials.md) §7.

A shell-level file such as `~/.config/environment.d/grace.conf` with perms `600` still works and is
the better home for values shared across projects — the MCP tokens in particular, which the editor
needs before make ever runs:

```
VAPI_API_KEY          Vapi private key
VAPI_PUBLIC_KEY       Vapi public key (browser-safe)
N8N_API_URL           https://palmleafmassage.app.n8n.cloud
N8N_MCP_URL           from Settings → Instance-level MCP, verbatim
N8N_MCP_TOKEN         MCP access token (shown once)
N8N_API_KEY           public API key
```

⚠️ Do not set the same variable in both places. `.env` **wins** over an exported value, so a stale
entry there silently shadows a correct one in your shell — verified, not assumed.

**RingCentral — three values, `.env` only.** Created in the RingCentral developer console as a
**Private JWT** app on the production platform (`https://platform.ringcentral.com`), with the
read scopes for account and extension data. They are what `make rc-snapshot` authenticates with.

```
GRACE_RINGCENTRAL_CLIENT_ID       app client id, developer console → Credentials
GRACE_RINGCENTRAL_CLIENT_SECRET   app client secret, shown once
GRACE_RINGCENTRAL_JWT             the JWT credential minted for this app
```

The JWT's expiry is effectively non-existent (≈2094), so there is no refresh flow to build or
maintain — which also means the value is long-lived and must never leave `.env`. Nothing in CI
uses these: the snapshot is an operator command run against a live business phone line, not a
build step.

**Dev values only.** No production credential ever exists on a developer machine — invariant I9, [05-security-and-compliance](05-security-and-compliance.md).

### 7.2 GitHub Actions secrets

| Secret | Used by |
|---|---|
| `VAPI_API_KEY_PROD` | `platform:vapi:deploy --env prod` |
| `VAPI_EVENTS_CREDENTIAL_ID_PROD` · `VAPI_TOOLS_CREDENTIAL_ID_PROD` | assistant + tool `server.credentialId` |
| `N8N_API_KEY_PROD` · `N8N_API_URL` | `make n8n-apply ENV=prod` |
| `GRACE_REPORTS_EMAIL_TO` | recipient for the four reports that email (WF-26) |
| `GRACE_INTERNAL_API_TOKEN_PROD` | n8n → Core API bearer |
| `GRACE_TRANSFER_NUMBER` · `GRACE_MAIN_LINE_NUMBER` | telephony, once GATE-11 clears |

~~`GRACE_N8N_WEBHOOK_SECRET_PROD`~~ was removed when inbound webhook auth moved to an n8n Header
Auth credential created by hand in the UI, which is not a CI secret ([04-n8n-layer](04-n8n-layer.md) §2.1).

CI is the only holder of production credentials, and the only deployer (ADR-0010, I9).

### 7.3 Rotation

Verifiers accept **current and previous** secret for a 24-hour window ([infrastructure](../reference/infrastructure.md), [05-security-and-compliance](05-security-and-compliance.md)) — rotate
without downtime by adding the new value, deploying, then removing the old.

Two exceptions that do **not** follow this and must be rotated with care:
- n8n credentials created by hand in the UI (§2.3)
- Vapi HMAC custom credentials (§1.2) — dashboard-managed, no API CRUD surfaced

---

## 8. Verification checklist

Run before declaring platform setup complete.

| # | Check | Expect |
|---|---|---|
| 1 | `/mcp` in Claude Code | `vapi`, `vapi-docs`, `n8n` all connected |
| 2 | `mcp__vapi__list_assistants` | responds (empty list is fine) |
| 3 | `mcp__n8n__search_workflows` | responds |
| 4 | `GET /api/v1/tags` | `env:dev`, `env:prod`, `managed:git` all exist |
| 5 | `GET /api/v1/credentials` | the `vapi` and `core-api` credentials exist per environment |
| 6 | Vapi dashboard → Billing | reserved concurrency ≥ 25 |
| 7 | Vapi dashboard → Credentials | both HMAC webhook credentials exist; payload format recorded (A-13) |
| 8 | n8n → Executions, after triggering WF-20 by hand | a real execution with real output, and a row in the Data Table (AC-09.12) |
| 9 | `make vapi-apply ENV=dev` then `make vapi-diff` | zero drift (AC-08.1) |
| 10 | Web harness call | Grace greets with the recording disclosure (I7) |
| 11 | Vapi dashboard → the call | `end-of-call-report` delivered with populated `structuredData` (AC-08.9) |
| 12 | Signed curl → WF-12 webhook | *(blocked — needs Core API; see [04-n8n-layer](04-n8n-layer.md) §4)* |
| 13 | Unsigned curl → WF-12 webhook | 401 (AC-09.10) |

Items 10–13 are the ones that prove the corrections in [03-vapi-layer](03-vapi-layer.md) §12 and
[04-n8n-layer](04-n8n-layer.md) §12 actually took effect. Items 1–9 only prove the plumbing exists.

**Item 8 is the one worth watching.** It is the first check in this document that demonstrates the
n8n instance doing real work rather than merely holding correct configuration.

## 9. Acceptance criteria

✅ **AC-18.1** A new developer reaches a working Grace web call from a clean machine using only this
document, without asking anyone for an undocumented step.
✅ **AC-18.2** Every credential in §3.3 exists in both environments, and `make n8n-apply` resolves
every `__CRED__:` placeholder on an enabled node.
✅ **AC-18.3** No real secret value appears anywhere in this repository — `gitleaks` clean on full
history (AC-11.9).
✅ **AC-18.4** Triggering WF-20 by hand produces an n8n Execution with real output and a Data Table
row (AC-09.12).
✅ **AC-18.5** Reserved Vapi concurrency is ≥ 25 before any load test is run, per §2.3.

## 10. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-06.1** | Neon or Supabase for the reporting database? | §6 works with either and the schema is portable. Nobody has picked one, so the durable reporting path stays off and Data Tables remain the only record. Small, unblocked, and worth closing soon. | Engineering |
| **A-13** | What exactly does Vapi HMAC over? | §2.2 creates the webhook credentials, but the payload format could not be confirmed from the dashboard. Core API cannot verify signatures until it is known — see [03-vapi-layer](03-vapi-layer.md) §14. | Engineering, before Core API |
| **Q-06.2** | How are hand-created n8n credentials rotated? | They sit outside the secret manager and outside the current+previous rotation window promised in [05-security-and-compliance](05-security-and-compliance.md) §10. Rotating them is manual and downtime-adjacent. | Engineering, at Phase D |
| **Q-06.3** | When is the n8n tier raised? | One instance shares concurrency and execution retention between dev and prod (§3.4), so a dev test loop can starve production. Tolerable at pilot volume; not once real calls arrive. | Commercial, before go-live |
