# 02 — Contracts, Repo and Tooling

**Completed:** 3 August 2026 · **Commits:** `34e3f4d`, `e8db9cd`, `298c9fc`

---

## Repository

pnpm workspace, 4 packages, TypeScript strict, ESM throughout.

```
palmleaf-grace/
├── packages/contracts/     @grace/contracts — zod, zero other runtime deps
├── platform/vapi/          @grace/platform-vapi
├── platform/n8n/           @grace/platform-n8n
└── .github/workflows/ci.yml
```

`tsconfig.base.json` carries the full strictness set from doc 02 §3 — `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`, `verbatimModuleSyntax`. All four packages typecheck clean under it.

ESLint 9 flat config with `strictTypeChecked`, plus the boundary rules that keep the
architecture from eroding: `packages/contracts` may import nothing but zod;
`platform/**` may not reach `@grace/adapters` or `@grace/db`.

### Environment notes

- `pnpm` was not installed. Bootstrapped into `~/.local/bin` via corepack; documented in
  `README.md`. The bare shim resolves a broken pnpm version unless `packageManager` is
  pinned in `package.json` — it is.
- `.mcp.json` uses `${VAR}` expansion and is gitignored; `.mcp.json.example` is committed.
- `~/.config/environment.d/grace.conf` (perms 600) exports the credentials to GUI-launched
  apps, which do not read `~/.bashrc`. Recorded in doc 18 §3.1.

---

## `packages/contracts`

**13 function-tool schemas**, each with an input and output zod schema, plus a registry that
is the single source everything else derives from.

| File | Contents |
|---|---|
| `tools/_shared.ts` | `LocalDate`, `Instant`, `PublicSlotId`, `BookingRef`, `PhoneE164`, `TimePreference`, `EscalationReason`, `Urgency`, `ToolAck` |
| `tools/read-tools.ts` | 1–4: `getBusinessInfo`, `lookupCustomer`, `getServicesAndPricing`, `checkAvailability` |
| `tools/write-tools.ts` | 5–7: `createBooking`, `rescheduleAppointment`, `cancelAppointment` |
| `tools/messaging-tools.ts` | 8–10: `sendIntakeForm`, `sendDepositLink`, `sendBookingConfirmation` |
| `tools/escalation-tools.ts` | 12–14: `takeMessage`, `flagMedicalHold`, `flagEscalation` |
| `tools/registry.ts` | `TOOL_REGISTRY` — name, description, schemas, budget, async, write |
| `vapi/envelope.ts` | The Vapi ⇄ Core API wire contract |

`transferToHuman` (11) and `endCall` (15) are absent by design: they are Vapi tool *types*
with no parameters and therefore no zod source.

### Conventions enforced

- **`.strict()` on every input.** An invented parameter is a loud validation error, never a
  silently ignored field. Verified live: the mock server rejects `{urgency:"high"}` on
  `checkAvailability` with a spoken retry.
- **`.describe()` on every field.** That text is what the model reads when deciding how to
  fill a parameter — prompt engineering, not documentation.
- **Never `.nullable()` on an input.** A constrained nullable renders as `anyOf`, which Vapi
  rejects. `.optional()` is also the better affordance: the model omits rather than reasoning
  about explicit null. Enforced statically by `generate-tools.ts`.
- **Never `z.literal()` on an input.** It renders as a scalar `const`, which Vapi rejects.
  Enforce the value in the handler instead — which is where I4 wants it anyway.

### The registry as single source

`TOOL_REGISTRY` drives three things that would otherwise drift:

1. `platform/vapi/tools/*.json` via `generate-tools.ts`
2. The `## TOOLS` table in the system prompt via `build-prompt.ts`
3. The mock server's dispatch and validation (and Core API's router, later)

Adding a tool is one registry row. Nothing else is hand-maintained.

---

## CI — the T1 static gate

`.github/workflows/ci.yml`. Target under 90 seconds, zero cost, no Vapi calls.

| Step | Catches |
|---|---|
| `typecheck` | type errors across all 4 packages |
| `lint` | style + the architecture boundary rules |
| `test` | 14 speech-formatter unit tests |
| I7 greps | missing recording/AI disclosure, **and** an inlined `firstMessage` |
| `vapi:generate --check` | generated tool JSON out of date vs the registry |
| `vapi:prompt --check` | `system.md` out of date vs `sections/` |
| `vapi:validate --refresh` | any `grace.json` key not in the **live** `CreateAssistantDTO`, or deprecated |
| `n8n:lint` | 15 structural workflow rules |
| secret scan | `sk_live_`, `whsec_`, `xoxb-`, Twilio SIDs |

A separate `drift` job runs the Vapi diff on pushes.

**`vapi:validate --refresh` is the highest-value step.** It is what found four dead assistant
fields, and it re-checks against current reality on every run — so if Vapi deprecates
something we use, CI tells us rather than a caller discovering it.

### A bug this work found in itself

`pnpm -r run test` **silently skips packages with no test script**. CI would have reported
green having run zero tests. The root `test` script now invokes vitest directly.
