# 18 — Platform Account Setup Runbook

**Read before:** the first `platform:vapi:deploy` or `platform:n8n:deploy`, and when onboarding a new
developer or a new tenant.
**Implements:** ADR-0010, ADR-0013. Enforces invariants I7, I9 (as relaxed by ADR-0013).

> This document covers the **manual, click-through, one-time** steps that config-as-code cannot perform:
> creating accounts, minting credentials, registering Slack apps, and raising quotas. Everything here is
> a prerequisite for the automated deploys in §08 §8 and §09 §6.3.
>
> **Nothing in this document should ever be committed with real values.** Every secret lands in an
> environment variable or a CI secret. See §6.

---

## 0. Current state (3 August 2026)

| Platform | Access | Notes |
|---|---|---|
| **Vapi** | ✅ full | Org contains one sample assistant (`Riley`), zero tools |
| **n8n Cloud** | ✅ full | `palmleafmassage.app.n8n.cloud`, pay-as-you-go. One untagged workflow, one OpenAI credential |
| Vagaro | ⛔ blocked | GATE-01, GATE-03 |
| RingCentral | ⛔ blocked | GATE-11 — no SIP trunk, therefore **no phone number** |
| Stripe | ⛔ blocked | GATE-08 |
| Google Calendar | ⛔ blocked | GATE-07 |
| Twilio | ⛔ blocked | GATE-09 (A2P 10DLC) |
| Slack | ⚠️ not created | §4 — no roadmap task creates it; this doc is the task |

**Consequence for this phase:** testing happens over **web calls only** (§08 §10). No phone number is
provisioned, and the transfer path cannot be verified end to end (**A-14**).

---

## 1. Vapi

### 1.1 API keys

Dashboard → **Organization Settings → API Keys**.

| Key | Used by | Where it lives |
|---|---|---|
| **Private** | `deploy.ts`, MCP server, CI | `VAPI_API_KEY` env var; `VAPI_API_KEY` GitHub secret |
| **Public** | the browser web-call harness (§08 §10) | `VAPI_PUBLIC_KEY` env var — safe to expose client-side |

The private key is org-wide and unscoped. Treat it as a root credential.

### 1.2 Webhook credentials (required before any deploy)

§08 §3.3: `Server.secret` does not exist. Authentication is a **Custom Credential** referenced by
`credentialId`. Create two, one per environment:

| Name | Type | Settings |
|---|---|---|
| `grace-dev-webhook` | HMAC | Algorithm `SHA256`, Signature Header `x-vapi-signature`, Timestamp Header `x-vapi-timestamp` |
| `grace-prod-webhook` | HMAC | identical |

Copy each resulting `credentialId` into `VAPI_EVENTS_CREDENTIAL_ID` / `VAPI_TOOLS_CREDENTIAL_ID` for the
matching environment. They are instance-specific, never committed, and masked on both sides of the drift
diff (§08 §8.1).

⚠️ **While you are in this screen, record the exact `Payload Format` option chosen** and confirm whether
it produces `{timestamp}.{rawBody}`. §04 §6.1's verifier must match whatever it actually produces. This is
assumption **A-13** and it is discharged here, not in code.

### 1.3 Concurrency — raise it before load testing

✅ Verified: Vapi defaults to **10 concurrent calls per account**. §01 §5 targets **25 sustained / 50
burst**.

Dashboard → **Settings → Billing → Reserved Concurrency (Call Lines)**. This is a billing action with
lead time — raise it in Phase C, not the week of the load test. `POST /call` returns a
`subscriptionLimits` object; assert against it in the load-test setup.

✅ Also verified: **no per-call or per-account spend cap exists.** Cost control is `maxDurationSeconds`,
concurrency, our own metering, and the §12 §6 daily-spend alert. Do not assume a cap will save you.

### 1.4 What NOT to configure

- **No phone number.** Not this phase (§0). When telephony unblocks, follow §10 §2 for the BYO-SIP trunk.
- **No knowledge base / files.** Explicitly rejected in §08 §11.3 — it would be a second, unapproved
  source of truth and would defeat GATE-02/GATE-04.
- **No dashboard edits to the assistant.** ADR-0010. Drift is a CI failure (§08 §8.1).

---

## 2. n8n Cloud

### 2.1 Two tokens, different jobs

Do not conflate these — they are separate credentials with separate lifecycles.

| Token | Where | Used by | Env var |
|---|---|---|---|
| **MCP Access Token** | Settings → Instance-level MCP | Claude Code / agent authoring | `N8N_MCP_TOKEN` |
| **Public API key** | Settings → n8n API | `deploy.ts`, `export.ts`, CI | `N8N_API_KEY` |

Also record the **MCP server URL** shown on the Instance-level MCP page (`N8N_MCP_URL`) — copy it
verbatim rather than constructing it; the path varies by n8n version.

⚠️ The MCP token is displayed **once**. Losing it means revoke + regenerate.

⚠️ Verified on the live instance: the API key's `scopes` include `workflow:create/update/delete/publish`
and credential access across **everything**. Scoped keys are Enterprise-only. One key reaches dev and
prod alike — this is the core risk ADR-0013 accepts and is why the hourly drift job is mandatory.

### 2.2 Tags — create these three first

`deploy.ts` filters on tags, and `GET /api/v1/tags` currently returns **empty**. Create:

```
env:dev        env:prod        managed:git
```

Nothing tagged `managed:git` is touched by anything other than CI. The existing untagged
`AI Agent workflow` is therefore ignored by the deploy filter (AC-09.11) — leave it alone.

### 2.3 Credentials to create by hand

Credentials are **never** deployed (§09 §6.2). Create each once, per environment, and reference by name.
`deploy.ts` resolves `__CRED__:<alias>` → name → id at push time.

| Alias | Type | Dev name | Prod name |
|---|---|---|---|
| `slack` | `slackApi` | `PalmLeaf Slack (dev)` | `PalmLeaf Slack (prod)` |
| `core-api` | `httpHeaderAuth` | `PalmLeaf Core API (dev)` | `PalmLeaf Core API (prod)` |

`httpHeaderAuth` carries `Authorization: Bearer $GRACE_INTERNAL_API_TOKEN` for the `/internal/*` calls.

**No Twilio credential.** §09 §3.4: staff SMS goes through `POST /internal/notify/sms` so the messaging
adapter's 10DLC, consent, and STOP/HELP enforcement cannot be bypassed. An n8n Twilio node would defeat
GATE-09 silently.

⚠️ Hand-created credentials sit outside the secret manager and outside the current+previous rotation
window promised in §11 §217. Rotating them is a manual, downtime-adjacent operation. Note it in the
runbook when Phase D scheduling is planned.

### 2.4 Plan-tier constraints

One instance serves both dev and prod (ADR-0013), so **concurrency and execution retention are shared**.
A dev test loop can consume prod's quota. Keep WF-16 (20 calls weekly) and any polling workflow
dev-disabled until the tier is raised. Never design a wait longer than execution retention (§09 §4.3).

---

## 3. MCP servers (agent authoring access)

Full step-by-step is in §19 Step 0. Summary of the end state:

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
  production, guarded by convention and detection only (§09 §5.2, §9).

### 3.1 Linux GUI-launch gotcha

Applications launched from a desktop dock do **not** read `~/.bashrc`. Environment variables exported
there reach terminal-launched processes only. Put credentials in `~/.config/environment.d/*.conf`
(`KEY=VALUE`, no `export`, no quotes, perms `600`) so the systemd user session exports them to GUI apps
too. Takes effect at next login.

Symptom if you skip this: MCP servers fail with *"'url' is not a valid URL"* (empty variable) or
*"401 rejected"* (stale value) even though the same variables resolve correctly in a terminal.

---

## 4. Slack app — two registrations

⚠️ **No roadmap task creates the Slack app**, yet WF-12, WF-14, WF-15, WF-16 and WF-18 all depend on it.
This section is that task.

⚠️ **Slack allows exactly one Request URL per app**, so dev and prod cannot share one. Create two:
`PalmLeaf Grace (dev)` and `PalmLeaf Grace`.

### 4.1 Per app

| Setting | Value |
|---|---|
| Bot scopes | `chat:write`, `chat:write.public`, `commands`, `channels:read` |
| Interactivity → Request URL | `https://palmleafmassage.app.n8n.cloud/webhook/<env>/slack-action` |
| Slash command | `/grace-kill` → same host, `/webhook/<env>/grace-kill` |
| Signing secret | → n8n, for manual verification (§09 §3.1) |
| Bot token | → the `slack` credential (§2.3) |

### 4.2 Channels

| Channel | Purpose | Referenced by |
|---|---|---|
| `#palmleaf-alerts` | P1/P2 escalations | §03 §116 `tenants.settings.escalationSlackChannel`, §12 §172 |
| `#palmleaf-ops-log` | P3 + WF-00 workflow failures | §09 §3.2, §4 |

Invite the bot to both. ⚠️ `#palmleaf-ops-log` appears only inside the WF-12 diagram in the old doc — it
is not in the settings schema. Add it, or route WF-00 to `#palmleaf-alerts` instead.

### 4.3 The 3-second rule

Slack requires HTTP 200 within 3 seconds. n8n's Slack **Trigger** node does not handle block actions or
slash commands — use a raw **Webhook** node with Raw Body on, `responseMode: responseNode`, and the
Respond node immediately after signature verification, before any Core API call. Post follow-ups via
`response_url` (5× within 30 minutes). Enforced by lint rule 14 (§09 §8).

---

## 5. Local development loop

```bash
# 1. Mock tool server — stands in for Core API, validates args with the real zod schemas
pnpm platform:vapi:mock                            # :4242

# 2. Public tunnel. NOTE: `vapi listen` is a local forwarder, NOT a public URL — you still need this.
cloudflared tunnel --url http://localhost:4242

# 3. Deploy the dev assistant pointed at the tunnel
GRACE_TOOLS_URL=https://<tunnel>/vapi/tools \
GRACE_EVENTS_URL=https://<tunnel>/webhooks/vapi/events \
  pnpm platform:vapi:deploy --env dev --apply

# 4. Talk to Grace — the only test channel this phase
open platform/vapi/web-harness/index.html
```

Fault injection for exercising the deadline fallbacks before Core API exists:

```bash
GRACE_MOCK_LATENCY_MS=1200 GRACE_MOCK_FAIL=checkAvailability pnpm platform:vapi:mock
```

---

## 6. Secret inventory

### 6.1 Developer machine

`~/.config/environment.d/grace.conf`, perms `600` (§3.1):

```
VAPI_API_KEY          Vapi private key
VAPI_PUBLIC_KEY       Vapi public key (browser-safe)
N8N_API_URL           https://palmleafmassage.app.n8n.cloud
N8N_MCP_URL           from Settings → Instance-level MCP, verbatim
N8N_MCP_TOKEN         MCP access token (shown once)
N8N_API_KEY           public API key
```

**Dev values only.** No production credential ever exists on a developer machine — invariant I9, §11 §224.

### 6.2 GitHub Actions secrets

| Secret | Used by |
|---|---|
| `VAPI_API_KEY_PROD` | `platform:vapi:deploy --env prod` |
| `VAPI_EVENTS_CREDENTIAL_ID_PROD` · `VAPI_TOOLS_CREDENTIAL_ID_PROD` | assistant + tool `server.credentialId` |
| `N8N_API_KEY_PROD` · `N8N_API_URL` | `platform:n8n:deploy --env prod` |
| `GRACE_N8N_WEBHOOK_SECRET_PROD` | worker → n8n HMAC (§09 §2.1) |
| `GRACE_INTERNAL_API_TOKEN_PROD` | n8n → Core API bearer |
| `SLACK_SIGNING_SECRET_PROD` | WF-14 signature verification |

CI is the only holder of production credentials, and the only deployer (ADR-0010, I9).

### 6.3 Rotation

Verifiers accept **current and previous** secret for a 24-hour window (§14 §130, §11 §217) — rotate
without downtime by adding the new value, deploying, then removing the old.

Two exceptions that do **not** follow this and must be rotated with care:
- n8n credentials created by hand in the UI (§2.3)
- Vapi HMAC custom credentials (§1.2) — dashboard-managed, no API CRUD surfaced

---

## 7. Verification checklist

Run before declaring platform setup complete.

| # | Check | Expect |
|---|---|---|
| 1 | `/mcp` in Claude Code | `vapi`, `vapi-docs`, `n8n` all connected |
| 2 | `mcp__vapi__list_assistants` | responds (empty list is fine) |
| 3 | `mcp__n8n__search_workflows` | responds |
| 4 | `GET /api/v1/tags` | `env:dev`, `env:prod`, `managed:git` all exist |
| 5 | `GET /api/v1/credentials` | the `slack` and `core-api` credentials exist per environment |
| 6 | Vapi dashboard → Billing | reserved concurrency ≥ 25 |
| 7 | Vapi dashboard → Credentials | both HMAC webhook credentials exist; payload format recorded (A-13) |
| 8 | Slack | two apps, bot invited to both channels, `/grace-kill` registered |
| 9 | `pnpm platform:vapi:deploy --env dev --apply` then `--diff` | zero drift (AC-08.1) |
| 10 | Web harness call | Grace greets with the recording disclosure (I7) |
| 11 | Vapi dashboard → the call | `end-of-call-report` delivered with populated `structuredData` (AC-08.9) |
| 12 | Signed curl → WF-12 webhook | P1 reaches `#palmleaf-alerts` within 30s (AC-09.4) |
| 13 | Unsigned curl → WF-12 webhook | 401 (AC-09.10) |

Items 10–13 are the ones that prove the corrections in §08 §12 and §09 §10 actually took effect. Items
1–9 only prove the plumbing exists.
