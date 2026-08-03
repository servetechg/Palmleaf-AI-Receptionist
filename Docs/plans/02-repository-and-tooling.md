# 02 — Repository, Tooling & Conventions

**Read before:** writing any file.
**Implements:** ADR-0001, ADR-0007, ADR-0010.

---

## 1. Repository layout

Repository name: **`palmleaf-grace`**. Package scope: **`@grace/*`**.

```
palmleaf-grace/
├── apps/
│   ├── core-api/                  # Fastify — Vapi tools, webhooks, health. THE HOT PATH.
│   │   ├── src/
│   │   │   ├── server.ts          # composition root: build & start
│   │   │   ├── app.ts             # buildApp(deps) → FastifyInstance  (testable, no listen)
│   │   │   ├── plugins/           # fastify plugins, registration order matters
│   │   │   │   ├── request-context.ts     # AsyncLocalStorage: requestId, tenantId, deadline
│   │   │   │   ├── hmac-vapi.ts           # x-vapi-signature verification
│   │   │   │   ├── tenant.ts              # resolve + pin tenant, set RLS GUC
│   │   │   │   ├── idempotency.ts         # generic idempotent-write middleware
│   │   │   │   ├── deadline.ts            # ADR-0012
│   │   │   │   ├── error-handler.ts       # taxonomy → HTTP + NL fallback
│   │   │   │   └── observability.ts       # pino, otel, prom-client
│   │   │   ├── routes/
│   │   │   │   ├── vapi/
│   │   │   │   │   ├── index.ts           # POST /vapi/tools   (single router entry)
│   │   │   │   │   ├── dispatch.ts        # toolName → handler map, exhaustive
│   │   │   │   │   └── handlers/          # one file per tool, 13 files
│   │   │   │   │       ├── get-business-info.ts
│   │   │   │   │       ├── lookup-customer.ts
│   │   │   │   │       ├── get-services-and-pricing.ts
│   │   │   │   │       ├── check-availability.ts
│   │   │   │   │       ├── create-booking.ts
│   │   │   │   │       ├── reschedule-appointment.ts
│   │   │   │   │       ├── cancel-appointment.ts
│   │   │   │   │       ├── send-intake-form.ts
│   │   │   │   │       ├── send-deposit-link.ts
│   │   │   │   │       ├── send-booking-confirmation.ts
│   │   │   │   │       ├── transfer-to-human.ts
│   │   │   │   │       ├── take-message.ts
│   │   │   │   │       └── flag-medical-hold.ts
│   │   │   │   ├── webhooks/
│   │   │   │   │   ├── vapi-events.ts     # end-of-call-report, status-update
│   │   │   │   │   ├── vagaro.ts          # ACK <20s, enqueue, never process inline
│   │   │   │   │   ├── stripe.ts          # signature-verified payment events
│   │   │   │   │   └── twilio.ts          # delivery receipts, STOP/HELP
│   │   │   │   ├── internal/              # mTLS/token-gated: n8n callbacks, worker callbacks
│   │   │   │   └── health.ts              # /healthz /readyz /metrics
│   │   │   └── formatters/                # domain result → natural-language string
│   │   └── test/
│   ├── sync-worker/               # BullMQ consumers: outbox dispatch, mirror sync, SMS, reminders
│   │   └── src/
│   │       ├── main.ts
│   │       ├── queues.ts                  # queue names + typed job payloads
│   │       ├── dispatcher/outbox.ts       # outbox → queue
│   │       └── processors/                # one file per job type
│   ├── booking-worker/            # Playwright Track B. Isolated container, own image.
│   └── admin-console/             # Phase F. Next.js staff UI. Stub only until then.
│
├── packages/
│   ├── contracts/                 # ZERO runtime deps except zod. The shared vocabulary.
│   │   └── src/
│   │       ├── tools/             # zod schema per tool: input, output, NL template
│   │       ├── ports/             # PmsPort, CalendarPort, PaymentsPort, MessagingPort
│   │       ├── events/            # domain event + outbox payload schemas
│   │       ├── webhooks/          # vapi, vagaro, stripe, twilio payload schemas
│   │       └── errors.ts          # error taxonomy (§04 §7)
│   ├── domain/                    # PURE. No I/O, no clock, no env. ADR-0011.
│   │   └── src/
│   │       ├── availability/      # slot generation, ranking, buffers
│   │       ├── booking/           # saga states + transition table
│   │       ├── policy/            # 48h engine, cancellation, deposit
│   │       ├── pricing/           # member/non-member resolution
│   │       ├── screening/         # medical gate
│   │       └── time/              # business-hours arithmetic, tz-safe helpers
│   ├── db/                        # drizzle schema, migrations, repositories, RLS helpers
│   │   └── src/
│   │       ├── schema/            # one file per table group
│   │       ├── repositories/      # one file per aggregate
│   │       ├── migrations/        # generated SQL, committed, never edited after merge
│   │       └── client.ts          # pool, tenant-scoped transaction helper
│   ├── adapters/                  # port implementations. Network lives here and nowhere else.
│   │   └── src/{vagaro,google-calendar,stripe,twilio,vapi,slack}/
│   ├── observability/             # logger, tracer, metrics registry, redaction
│   ├── config/                    # zod-validated env loading, per-app config objects
│   └── testing/                   # testcontainers, fixtures, fakes for every port
│
├── platform/                      # config-as-code for managed services. ADR-0010.
│   ├── vapi/
│   │   ├── assistants/grace.json
│   │   ├── tools/*.json           # generated FROM packages/contracts — never hand-edited
│   │   ├── prompts/system.md
│   │   └── deploy.ts              # diff + apply against Vapi REST
│   └── n8n/
│       ├── workflows/WF-*.json
│       ├── credentials.example.json
│       └── deploy.ts
│
├── infra/
│   ├── docker/                    # Dockerfile per app + compose files
│   ├── terraform/                 # Phase D+: VPS/ECS, RDS, secrets, DNS
│   └── grafana/                   # dashboards + alert rules as JSON
│
├── scripts/                       # one-shot operational scripts, all idempotent
├── docs/                          # ADR additions, runbooks that belong with the code
├── .github/workflows/             # ci.yml, deploy-staging.yml, deploy-prod.yml
├── .mcp.json                      # Vapi + n8n MCP — DEV CREDENTIALS ONLY
├── turbo.json  pnpm-workspace.yaml  tsconfig.base.json  eslint.config.js
└── README.md
```

### 1.1 Package dependency graph (enforced)

```
                    ┌──────────────┐
                    │  contracts   │  ← zod only
                    └──┬────┬───┬──┘
            ┌──────────┘    │   └───────────┐
            ▼               ▼               ▼
      ┌──────────┐   ┌───────────┐   ┌───────────┐
      │  domain  │   │ adapters  │   │    db     │
      │  (pure)  │   └─────┬─────┘   └─────┬─────┘
      └────┬─────┘         │               │
           └───────┬───────┴───────┬───────┘
                   ▼               ▼
             ┌───────────┐   ┌─────────────┐
             │ core-api  │   │ sync-worker │   booking-worker
             └───────────┘   └─────────────┘
```

**Forbidden edges (CI-enforced):**
- `domain` → anything except `contracts`
- `contracts` → anything except `zod`
- `db` → `adapters`
- `adapters` → `db`
- `core-api/routes/vapi/handlers/**` → `adapters/**` *(this is invariant I1 — the hot path cannot reach a third party)*

---

## 2. Runtime and package manager

| Tool | Version | Pinned in |
|---|---|---|
| Node.js | 22.x LTS | `.nvmrc`, `package.json#engines`, Docker base image |
| pnpm | 9.x | `package.json#packageManager` (corepack) |
| TypeScript | 5.6+ | root devDependency |
| Postgres | 16 | Docker image tag, RDS engine version |
| Redis | 7.x | Docker image tag |

`pnpm-workspace.yaml`:

```yaml
packages:
  - 'apps/*'
  - 'packages/*'
  - 'platform'
```

**Module system:** ESM throughout (`"type": "module"`). Import specifiers include the `.js` extension in
relative imports (TS `moduleResolution: "bundler"` is *not* used — we run on Node directly).

---

## 3. TypeScript configuration

`tsconfig.base.json` — strictness is not negotiable; it is the cheapest defect-prevention available.

```jsonc
// TARGET
{
  "compilerOptions": {
    "target": "ES2023",
    "lib": ["ES2023"],
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "noUncheckedIndexedAccess": true,      // array access returns T | undefined
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "noPropertyAccessFromIndexSignature": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "composite": true,
    "incremental": true
  }
}
```

Each package extends it and sets `outDir: dist`, `rootDir: src`, and `references` to its dependencies.

**Rule:** `any` is banned outside `*.test.ts`. Use `unknown` and narrow. `@ts-expect-error` requires a
comment explaining why and a linked issue.

---

## 4. Validation strategy — Zod as the single schema source

Zod schemas in `packages/contracts` are the origin of:

1. TypeScript types (`z.infer`)
2. Runtime validation at every boundary (tool input, webhook body, env, adapter response)
3. **The JSON Schema published to Vapi as the tool's parameter definition** (via `zod-to-json-schema`)

That third item is the important one. It means a tool's parameters cannot drift from the handler that
serves them — the same object generates both.

```ts
// TARGET — packages/contracts/src/tools/check-availability.ts
import { z } from 'zod';

export const CheckAvailabilityInput = z.object({
  serviceCode: z.string().min(1).describe('Service code, e.g. massage_60. Use getServicesAndPricing first.'),
  preferredDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe('Local date, YYYY-MM-DD'),
  timePreference: z.enum(['morning', 'afternoon', 'evening', 'any']).default('any'),
  providerPreference: z.string().nullable().default(null).describe('Provider name if the caller asked for one'),
  partySize: z.number().int().min(1).max(4).default(1),
}).strict();

export const CheckAvailabilityOutput = z.object({
  slots: z.array(z.object({
    slotId: z.string(),
    startsAt: z.string().datetime(),
    providerId: z.string(),
    providerName: z.string(),
    priceCents: z.number().int(),
    holdExpiresAt: z.string().datetime(),
  })).max(3),
  alternativesAvailable: z.boolean(),
});

export type CheckAvailabilityInput = z.infer<typeof CheckAvailabilityInput>;
export type CheckAvailabilityOutput = z.infer<typeof CheckAvailabilityOutput>;
```

`.describe()` text is what the LLM reads when deciding how to fill a parameter. Treat it as prompt
engineering, not documentation — it is the highest-leverage text in the repo after the system prompt.

`.strict()` on inputs is mandatory: an LLM inventing an extra parameter should be a loud validation
error in the logs, not a silently ignored field.

---

## 5. Code style and formatting

| Concern | Tool | Config |
|---|---|---|
| Format | Prettier 3 | 100 cols, single quotes, trailing commas, semicolons |
| Lint | ESLint 9 flat config | `typescript-eslint` strict-type-checked + custom boundary rules |
| Imports | `eslint-plugin-import-x` | ordered: node → external → `@grace/*` → relative |
| Commits | commitlint | Conventional Commits |
| Hooks | lefthook | pre-commit: format+lint staged; pre-push: typecheck+unit |

Naming:

| Kind | Convention | Example |
|---|---|---|
| Files | kebab-case | `check-availability.ts` |
| Types / classes | PascalCase | `SlotHold`, `VagaroAdapter` |
| Functions / vars | camelCase | `computeFreeSlots` |
| Constants | SCREAMING_SNAKE | `MAX_HOLD_SECONDS` |
| DB tables | snake_case, plural | `calendar_occupancy`, `slot_holds` |
| DB columns | snake_case | `starts_at`, `tenant_id` |
| Queues / jobs | dot.namespaced | `outbox.dispatch`, `pms.write_appointment` |
| Metrics | prom snake_case + unit | `grace_tool_duration_seconds` |
| Env vars | SCREAMING_SNAKE, prefixed | `GRACE_DATABASE_URL` |

---

## 6. The boundary lint rules (ADR-0001, invariant I1)

These are the rules that keep the architecture from eroding. Add them in Phase A, not later.

```js
// TARGET — eslint.config.js (excerpt)
export default [
  // ... base configs ...
  {
    files: ['packages/domain/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [
          { group: ['@grace/db', '@grace/adapters', '@grace/config'],
            message: 'ADR-0011: domain is pure. Pass data in as arguments.' },
          { group: ['node:*', 'pg', 'ioredis', 'axios', 'undici'],
            message: 'ADR-0011: domain performs no I/O.' },
        ],
      }],
      'no-restricted-globals': ['error',
        { name: 'Date', message: 'ADR-0011: accept `now: Date` as a parameter.' },
        { name: 'fetch', message: 'ADR-0011: domain performs no I/O.' },
      ],
    },
  },
  {
    // INVARIANT I1 — the hot path cannot reach a third party.
    files: ['apps/core-api/src/routes/vapi/handlers/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [
          { group: ['@grace/adapters/*', '!@grace/adapters/testing'],
            message: 'I1: no third-party call on the synchronous tool path. Emit an outbox event instead.' },
        ],
      }],
    },
  },
  {
    files: ['packages/contracts/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [{ group: ['@grace/*'], message: 'contracts depends on nothing.' }],
      }],
    },
  },
];
```

Additionally add a `depcruise` (dependency-cruiser) check in CI for the package-graph edges in §1.1 —
ESLint catches imports, dependency-cruiser catches `package.json` dependency edges.

---

## 7. Turborepo pipeline

```jsonc
// TARGET — turbo.json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build":      { "dependsOn": ["^build"], "outputs": ["dist/**"] },
    "typecheck":  { "dependsOn": ["^build"] },
    "lint":       {},
    "test:unit":  { "dependsOn": ["^build"], "outputs": ["coverage/**"] },
    "test:integration": { "dependsOn": ["^build"], "cache": false },
    "test:contract":    { "dependsOn": ["^build"], "cache": false },
    "db:generate": { "cache": false },
    "db:migrate":  { "cache": false }
  }
}
```

Root scripts:

```jsonc
{
  "scripts": {
    "dev":        "turbo run dev --parallel",
    "build":      "turbo run build",
    "check":      "turbo run lint typecheck test:unit",
    "test":       "turbo run test:unit test:integration test:contract",
    "db:generate":"pnpm --filter @grace/db db:generate",
    "db:migrate": "pnpm --filter @grace/db db:migrate",
    "stack:up":   "docker compose -f infra/docker/compose.dev.yml up -d",
    "stack:down": "docker compose -f infra/docker/compose.dev.yml down",
    "platform:vapi:diff": "tsx platform/vapi/deploy.ts --diff",
    "platform:n8n:diff":  "tsx platform/n8n/deploy.ts --diff"
  }
}
```

---

## 8. Environment and configuration

**Every** environment variable is declared in `packages/config` with a Zod schema and a description.
A missing or malformed variable fails at process start with a readable message — never at 2am on the
first request that happens to need it.

```ts
// TARGET — packages/config/src/env.ts (excerpt)
const Base = z.object({
  NODE_ENV: z.enum(['development', 'test', 'staging', 'production']),
  GRACE_LOG_LEVEL: z.enum(['trace','debug','info','warn','error']).default('info'),
  GRACE_DATABASE_URL: z.string().url(),
  GRACE_DATABASE_POOL_MAX: z.coerce.number().int().min(2).max(50).default(10),
  GRACE_REDIS_URL: z.string().url(),
  GRACE_DEFAULT_TENANT_SLUG: z.string().default('palmleaf'),
  GRACE_BUSINESS_TIMEZONE: z.string().default('America/Chicago'),
});

const CoreApi = Base.extend({
  PORT: z.coerce.number().int().default(3000),
  GRACE_VAPI_WEBHOOK_SECRET: z.string().min(32),
  GRACE_INTERNAL_API_TOKEN: z.string().min(32),
  GRACE_STRIPE_WEBHOOK_SECRET: z.string().startsWith('whsec_'),
  GRACE_TWILIO_AUTH_TOKEN: z.string().min(16),
  GRACE_TOOL_DEADLINE_MS: z.coerce.number().int().default(2500),
  GRACE_HOLD_TTL_SECONDS: z.coerce.number().int().default(240),
  GRACE_RESERVATION_TTL_SECONDS: z.coerce.number().int().default(900),
});
```

**Env var inventory** (full list; §14 §3 maps them to environments):

| Variable | Used by | Secret |
|---|---|---|
| `GRACE_DATABASE_URL` | all | ✅ |
| `GRACE_REDIS_URL` | core-api, workers | ✅ |
| `GRACE_VAPI_WEBHOOK_SECRET` | core-api | ✅ |
| `GRACE_VAPI_API_KEY` | platform deploy, adapters | ✅ |
| `GRACE_INTERNAL_API_TOKEN` | core-api ↔ n8n ↔ workers | ✅ |
| `GRACE_VAGARO_CLIENT_ID` / `_SECRET` / `_REGION` / `_BUSINESS_ID` | adapters | ✅ |
| `GRACE_VAGARO_WEBHOOK_TOKEN` | core-api | ✅ |
| `GRACE_GOOGLE_SA_JSON` (base64) | adapters | ✅ |
| `GRACE_STRIPE_SECRET_KEY` / `_WEBHOOK_SECRET` | adapters, core-api | ✅ |
| `GRACE_TWILIO_ACCOUNT_SID` / `_AUTH_TOKEN` / `_MESSAGING_SERVICE_SID` | adapters, core-api | ✅ |
| `GRACE_SLACK_WEBHOOK_URL` | workers | ✅ |
| `GRACE_N8N_BASE_URL` / `_API_KEY` | platform deploy | ✅ |
| `GRACE_SENTRY_DSN` | all | ➖ |
| `GRACE_OTEL_EXPORTER_OTLP_ENDPOINT` | all | ➖ |
| `GRACE_KILL_SWITCH_ENABLED` | core-api | ➖ |
| `GRACE_FEATURE_TRACK_B` / `_TRACK_A` / `_DEPOSITS` | core-api, workers | ➖ |

Secrets in dev come from `.env.local` (gitignored, generated by `scripts/bootstrap-env.ts`).
Secrets in staging/prod come from the secret manager (§14 §5). **`.env` files never contain production
values and are never committed.** `.gitignore` must include `.env*`, `!.env.example`.

---

## 9. Git conventions

**Branches.** `main` is always deployable. Work on `feat/<area>-<short>`, `fix/…`, `chore/…`.
No direct pushes to `main`; PR + green CI required.

**Commits.** Conventional Commits, with the roadmap task ID in the footer:

```
feat(availability): add tstzrange occupancy repository

Implements the anti-join slot query with GiST index.
p95 measured at 18ms with 10k occupancy rows.

Task: B-04
```

Scopes: `contracts` `domain` `db` `adapters` `core-api` `worker` `booking-worker` `vapi` `n8n`
`infra` `ci` `docs` `security`.

**Pull requests must state:** what changed, which roadmap task, which ACs are now met, and — if a
migration is included — the rollback plan.

---

## 10. Documentation that lives with the code

| File | Contains | Updated when |
|---|---|---|
| `README.md` | 10-minute local bootstrap, nothing else | setup changes |
| `docs/adr/NNNN-*.md` | New ADRs beyond the 12 here | a decision is made |
| `docs/runbooks/*.md` | Copies of §16 runbooks, kept next to the code | an incident teaches something |
| `packages/*/README.md` | The package's contract in ≤20 lines | its public API changes |
| `CHANGELOG.md` | Generated from conventional commits | release |

---

## 11. Phase A definition of done for this document

✅ **AC-02.1** `pnpm install && pnpm build && pnpm check` passes from a clean clone on Node 22.
✅ **AC-02.2** `pnpm stack:up` brings up Postgres + Redis; `pnpm db:migrate` succeeds against it.
✅ **AC-02.3** A deliberate violation of each §6 boundary rule fails `pnpm lint` (prove it with a
throwaway commit, then revert).
✅ **AC-02.4** Deleting any required env var causes a startup failure naming that variable.
✅ **AC-02.5** CI runs lint, typecheck, unit, integration on every PR and blocks merge on failure.
