# 14 — Infrastructure & Deployment

**Read before:** Phase A.
**Enforces:** invariant I9.

---

## 1. Topology

Deliberately small. Two services, two workers, one database, one cache. Design brief §6 rules out
Kubernetes at this scale, and that judgement holds — the operational overhead would exceed the system.

```
                      ┌────────────────────────────────┐
   Internet ─────────►│  Load balancer / TLS           │
                      │  (Caddy or cloud LB)           │
                      └───────┬────────────────┬───────┘
                              │                │
                      ┌───────▼──────┐  ┌──────▼───────┐
                      │ core-api #1  │  │ core-api #2  │   stateless, rolling deploy
                      └───────┬──────┘  └──────┬───────┘
                              └────────┬───────┘
             ┌────────────────┬────────┴────────┬──────────────────┐
             ▼                ▼                 ▼                  ▼
      ┌────────────┐   ┌────────────┐   ┌──────────────┐   ┌──────────────┐
      │ Postgres16 │   │  Redis 7   │   │ sync-worker  │   │booking-worker│
      │ managed    │   │  managed   │   │  (1–2)       │   │ (1, Track B) │
      │ PITR on    │   │  AOF on    │   └──────────────┘   └──────────────┘
      └────────────┘   └────────────┘
                              │
                      ┌───────▼──────┐
                      │  n8n (prod)  │   separate host/container; own DB schema
                      └──────────────┘
```

**Region: `us-west-2`** — co-located with Vapi's infrastructure to minimise tool round-trip latency
(design brief §9). Measure this in Phase D; if Vapi's edge for this account is elsewhere, move.

**Hosting choice.** Start on a single managed VPS host (Hetzner/DigitalOcean) with Docker Compose plus
*managed* Postgres and Redis — never self-hosted stateful services. Migrate to ECS Fargate when either
(a) a second tenant goes live, or (b) the deploy story starts costing more than an hour a week. The
Dockerfiles and compose files are written so that migration is a task-definition exercise, not a rewrite.

---

## 2. Containers

One Dockerfile per app, multi-stage, non-root, distroless-or-slim runtime.

```dockerfile
# TARGET — infra/docker/core-api.Dockerfile
FROM node:22-slim AS base
RUN corepack enable
WORKDIR /app

FROM base AS deps
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY packages/*/package.json packages/
COPY apps/core-api/package.json apps/core-api/
RUN pnpm install --frozen-lockfile

FROM deps AS build
COPY . .
RUN pnpm --filter @grace/core-api... build && pnpm deploy --filter @grace/core-api --prod /out

FROM node:22-slim AS runtime
RUN useradd -r -u 10001 grace
WORKDIR /app
COPY --from=build --chown=grace:grace /out ./
USER grace
ENV NODE_ENV=production NODE_OPTIONS="--enable-source-maps"
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "apps/core-api/dist/server.js"]
```

`booking-worker` differs: it uses `mcr.microsoft.com/playwright:v1.x-jammy` as the runtime base, gets
`--shm-size=1g`, and is memory-capped at 2 GB with a hard restart policy. Browsers leak; plan for it.

---

## 3. Environments

| Env | Purpose | Data | Vapi | PMS | Who deploys |
|---|---|---|---|---|---|
| **local** | development | seeded + demo | dev assistant | fake | developer |
| **ci** | automated tests | ephemeral testcontainers | none | fake | CI |
| **staging** | pre-production, load, chaos | seeded, production-shaped, **no real customers** | staging assistant + test number | fake (or read-only real) | CI on `main` |
| **production** | the client's phone line | real | prod assistant | real | CI on tag/approval |

**Rules:**
- Staging never writes to the real PMS, never sends real SMS (Twilio test credentials), never charges
  a real card (Stripe test mode).
- Production credentials exist only in the production secret store and GitHub Actions production
  environment (protected, requires approval).
- A developer cannot deploy to production from a laptop. There is no path. That is invariant I9.

---

## 4. Local development

```bash
git clone … && cd palmleaf-grace
corepack enable && pnpm install
cp .env.example .env.local && pnpm tsx scripts/bootstrap-env.ts   # generates dev secrets
pnpm stack:up                 # postgres + redis + n8n-dev (docker compose)
pnpm db:migrate && pnpm db:seed
pnpm dev                      # core-api :3000, sync-worker, watch mode
```

Local Vapi development uses `vapi listen` to tunnel webhook events to `localhost:3000` (design brief
§20.1) — no ngrok, no public exposure of a dev machine.

**README target: a new developer is running a full booking flow against fakes within 10 minutes.**
If it takes longer, fix the bootstrap, not the README.

---

## 5. Secrets

| Env | Store |
|---|---|
| local | `.env.local` (gitignored), dev-tier credentials only |
| ci | GitHub Actions secrets |
| staging/production | AWS Secrets Manager (or Doppler) — injected at container start, never baked into an image |

Rotation: quarterly, and immediately on suspected exposure. Verifiers accept current+previous secret for
24h so rotation is zero-downtime (§11 §9).

---

## 6. CI/CD

```
PR opened
 └─► ci.yml : lint → typecheck → unit → contract → integration → e2e → build → invariants
              + platform diff (report only)
              ~8 min, blocks merge

merge to main
 └─► deploy-staging.yml
       1. build & push images (tagged with git sha)
       2. run migrations against staging   ← separate step, must succeed alone
       3. deploy core-api (rolling, health-gated)
       4. deploy workers
       5. platform:vapi:apply --env staging
       6. platform:n8n:deploy --env staging
       7. smoke tests
       8. k6 nominal profile
       9. on any failure → automatic rollback to previous image tag

manual approval (production environment, protected)
 └─► deploy-prod.yml   (same steps, prod targets, plus:)
       0. verify staging has been green for ≥30 min
       10. post-deploy smoke: one synthetic call end to end
       11. announce in #palmleaf-alerts with the changelog
```

### 6.1 Migrations in CI

Migrations run as a **separate, idempotent step before** the new code deploys, and every migration must be
backward-compatible with the currently-running version. This is what makes rolling deploys safe.

The three-step rule for breaking changes:

```
Deploy 1: add the new column/table (nullable, defaulted). Code writes both old and new.
Deploy 2: backfill; code reads new, still writes both.
Deploy 3: stop writing old; drop it.
```

Never compress these. A dropped column during a rolling deploy takes calls down.

### 6.2 Rollback

| Failure | Rollback |
|---|---|
| Bad application code | Redeploy previous image tag. <2 min. Automated on smoke failure. |
| Bad migration | **Forward-fix only.** This is why migrations are additive. A down-migration on a live booking database is more dangerous than the bug. |
| Bad Vapi config | `platform/vapi/deploy.ts --apply` from the previous commit; `.lock.json` makes the previous state explicit. |
| Bad n8n workflow | Same, from `platform/n8n/`. |
| Everything on fire | **Carrier kill switch** (§10 §3.1) — calls go to staff. Then debug calmly. |

---

## 7. Scaling path

| Trigger | Action |
|---|---|
| p95 tool latency creeping up | Check DB pool saturation and query plans first. Add a core-api instance only after. |
| >25 sustained concurrent calls | +1 core-api instance (stateless; linear) |
| Outbox lag >30s sustained | +1 sync-worker; increase BullMQ concurrency per queue |
| Track B queue backing up | Do **not** parallelise per tenant (§07 §5.3). Add tenants across workers instead. |
| Second tenant | Same infrastructure — RLS and `tenant_id` already handle it. Add `tenant_channels` rows. |
| ~10 tenants | Move to ECS Fargate; split core-api and workers into separate services; managed Postgres with a read replica for reporting |
| ~50 tenants | Per-tenant queue namespacing; consider occupancy partitioning by tenant; regional deployment if geography spreads |

Nothing on this path is a re-architecture. That is the payoff of ADR-0008 and ADR-0004.

---

## 8. Backup, DR, and data safety

| Item | Policy |
|---|---|
| Postgres backups | Managed automated backups + **PITR**, 14-day retention |
| **Restore drill** | Quarterly, to a scratch instance, timed and documented. An untested backup is not a backup. |
| RPO / RTO | 5 min / 30 min |
| Redis | AOF persistence; treated as **rebuildable** — queues are recoverable from the outbox, cache is warmable. Redis loss must never lose a booking, and does not, because of ADR-0005. |
| Object storage (recordings, screenshots) | Versioning on, lifecycle rules matching the retention policy (§03 §16) |
| Config | Everything in git. The repo plus the secret store is sufficient to rebuild the system. |
| Disaster runbook | §16 §16 — full rebuild from an empty account, tested once before go-live |

---

## 9. Cost tracking

Tag every cloud resource with `project=palmleaf-grace`, `env=<env>`, `tenant=palmleaf`. Wire the cost
dashboard (§12 §5.4) to the actual invoices. Validate the design brief §16 estimate ($700–950/month) in
week two of production and report the real number to the client, whichever direction it moves.

Fixed infra estimate at this topology: VPS ~$40 · managed Postgres ~$25 · managed Redis ~$15 · n8n host
~$20 · object storage + monitoring ~$15 = **~$115/month**, consistent with the brief's $85–150 range.

---

## 10. Acceptance criteria

✅ **AC-14.1** A clean clone reaches a working local stack with a successful seeded booking in ≤10 minutes.
✅ **AC-14.2** All images build reproducibly and run as a non-root user.
✅ **AC-14.3** Staging deploys automatically on merge to `main` and rolls back automatically on smoke failure.
✅ **AC-14.4** Production deploy requires a manual approval and cannot be triggered from a developer machine.
✅ **AC-14.5** A rolling deploy completes with zero dropped requests under the k6 nominal profile.
✅ **AC-14.6** Migrations run as a distinct, idempotent step and are backward-compatible with the previous release.
✅ **AC-14.7** A PITR restore drill has been performed and timed within RTO.
✅ **AC-14.8** Flushing Redis loses no booking and no outbox event (proven on staging).
✅ **AC-14.9** No production secret is retrievable from any developer machine or committed file.
✅ **AC-14.10** `platform` diff on `main` reports zero drift against the live Vapi and n8n instances.
