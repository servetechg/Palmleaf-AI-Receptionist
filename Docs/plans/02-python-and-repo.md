# 02 — Python, Repository Layout & Conventions

**Status:** Active
**Read before:** writing any file in this repository.
**Implements:** ADR-0010, ADR-0014, ADR-0016, ADR-0017, ADR-0018
**Enforces:** I1, I4, I9
**Last verified:** 2026-08-04 against `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml` and the packages present in `src/`.

> **In one paragraph:** this document settles how the repository is laid out, which Python
> toolchain is used and how each tool is configured, how schemas are defined once and reused
> everywhere, and how the architectural boundaries of [01-architecture](01-architecture.md) §2
> are made mechanically unbreakable. It deliberately does **not** specify any business
> behaviour — no schema, no endpoint, no workflow. It is the shape of the box, not what goes
> in it.

---

## 1. What exists today versus what is planned

This distinction matters more than usual here, because roughly two thirds of the layout below is
not built. Directories marked **live** are present in the repository right now and are the ones
any current task touches. Directories marked **planned** are the target shape; they arrive with
Core API and the database, and are recorded here so the boundaries are agreed before the first
file lands rather than argued about afterwards.

```
palmleaf-grace/
├── pyproject.toml              live   one project, one dependency set, all tool config
├── Makefile                    live   the task runner (§7)
├── .github/workflows/ci.yml    live   the T1 gate
├── src/
│   ├── grace_contracts/        live   schemas and port protocols. Depends on NOTHING.
│   │   ├── tools/                     one Pydantic model per Vapi tool, plus the registry
│   │   └── vapi/                      the request/response envelope
│   ├── grace_platform/         live   config-as-code tooling. Not a runtime service.
│   │   ├── vapi/                      generate, build prompt, validate, deploy, mock server
│   │   ├── n8n/                       lint, deploy
│   │   └── docs/                      the reference generators and the doc linter
│   ├── grace_domain/           planned  pure business rules. No I/O, no clock. (ADR-0011)
│   ├── grace_db/               planned  SQLAlchemy models, Alembic migrations, repositories
│   ├── grace_adapters/         planned  one module per external system (ADR-0007)
│   └── grace_api/              planned  FastAPI. The hot path. (ADR-0017)
├── platform/                   live   config-as-code, deployed by CI only (ADR-0010)
│   ├── vapi/                          assistants, tools, prompt sections, structured outputs
│   ├── n8n/workflows/                 one JSON file per workflow
│   └── postgres/schema.sql            reporting tables — skeleton, see [04-n8n-layer](04-n8n-layer.md) §9
├── tests/                      live   pytest
└── Docs/
    ├── plans/                         active, buildable now — this folder
    ├── reference/                     frozen until access arrives
    ├── generated/                     written by `make docs`. Never hand-edited.
    └── Completed/                     the delivery record
```

**One project, not a workspace.** The port did not reproduce the multi-package workspace the
superseded layout described. A single `pyproject.toml` with several packages under `src/` gives
the same import boundaries — because those are enforced by `import-linter` against package
names, not by packaging — without the overhead of keeping several dependency sets in step. If a
package ever genuinely needs to ship separately, splitting it out later is mechanical.

### 1.1 The package dependency graph

The arrows are the entire point of the layout. Everything else is filing.

```
grace_contracts   ←── depends on nothing at all
     ▲
     ├──────────── grace_domain      pure. no httpx, no asyncpg, no redis.
     │                  ▲
     ├──────────── grace_db          SQLAlchemy + Alembic
     │                  ▲
     ├──────────── grace_adapters    the only package allowed to talk to a third party
     │                  ▲
     └──────────── grace_api         composes the above. Handlers may NOT reach adapters.
```

`grace_platform` sits outside this graph. It is build-time tooling — it reads `grace_contracts`
to generate artefacts, and no runtime package imports it.

The final arrow is the one that matters most: **`grace_api.routes.vapi.handlers` may not import
`grace_adapters`.** That is invariant **I1** — no third-party call on the path where a caller is
waiting — and §6 makes it mechanical.

---

## 2. Runtime, dependencies and environments

**Python 3.12+**, managed with **uv** (ADR-0014). `uv` collapses the whole install-and-virtualenv
step into two fast, lockfile-backed commands, and CI runs the same ones.

```bash
uv venv                       # create .venv
uv pip install -e ".[dev]"    # install the project plus the dev extras
```

Or, equivalently and preferably, `make install`.

**Everything runs through the project venv.** The Makefile invokes `.venv/bin/python -m <tool>`
rather than a bare `ruff` or `mypy`, so a globally-installed tool of a different version can
never silently be the one that ran. That is why the commands in this document all look like
`.venv/bin/python -m …` — deliberate, not verbosity.

| Component | Version | Pinned in |
|---|---|---|
| Python | 3.12+ | `pyproject.toml#requires-python`, CI, Docker base image |
| uv | current | `astral-sh/setup-uv` in CI |
| Postgres | 16 | Docker image tag, managed-instance engine version |
| Redis | 7.x | Docker image tag |

Runtime dependencies stay deliberately small — `pydantic` for schemas, `httpx` for HTTP. The dev
extra adds `pytest`, `ruff` and `mypy`. Every package added to the runtime set is a package that
must be patched, audited and understood at 2am, so additions belong in review rather than in
passing.

---

## 3. Validation strategy — Pydantic v2 as the single schema source

This is the most load-bearing convention in the repository, and the one the language port was
chosen to preserve intact (ADR-0014).

**One Pydantic model per tool defines everything about that tool.** From that single class:

| Derived artefact | Produced by | Consumed by |
|---|---|---|
| The JSON Schema published to Vapi | `model_json_schema()`, via `make vapi-generate` | Vapi, at call time |
| The prompt's tool table | `make vapi-prompt` | the model, as instructions |
| Runtime request validation | the model itself, in the handler | the hot path |
| The per-tool reference page | `make docs` | humans — [Docs/generated/tools/](../generated/tools/) |

Because all four come from one class, **they cannot disagree.** A tool whose published schema
accepts a field its handler rejects is the single most likely integration bug in a system like
this one, and deriving both from one source eliminates the category rather than testing for it.
CI enforces currency: `make vapi-build-check` and `make docs-check` fail when a model changes and
the generated artefacts were not regenerated.

```python
#: TARGET — src/grace_contracts/tools/read_tools.py (shape, abridged)
class CheckAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_code: str = Field(
        description="Service code, e.g. massage_60. Call getServicesAndPricing first.",
    )
    preferred_date: str = Field(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
        description="Local date, YYYY-MM-DD.",
    )
    time_preference: Literal["morning", "afternoon", "evening", "any"] = "any"
    provider_preference: str | None = Field(
        default=None, description="Provider name, if the caller asked for someone specific."
    )
```

`extra="forbid"` is mandatory on every tool input. A model inventing an extra argument must be a
loud validation error in the logs, never a silently discarded field.

**Field descriptions are not decoration.** `Field(description=…)` is what the model reads when
deciding whether to call a tool and what to put in each argument, and it is what the generated
reference page shows a human. A missing or vague description is a behavioural defect, not a
style nit — treat that text as prompt engineering, because that is exactly what it is.

**Three Pydantic-specific hazards**, all found at the port boundary and all now guarded:

1. **The class docstring becomes the schema `description`.** Internal implementation notes were
   being shipped to the model as instructions. The generator strips docstrings, and the
   validator fails the build if any reappear.
2. **Enums are hoisted into `$defs` and referenced.** Vapi has no `$ref` resolver, so the
   generator inlines them.
3. **Python distinguishes `1` from `1.0`; JSON does not.** Integral floats are collapsed before
   drift comparison, or the drift check goes permanently red on the first run.

---

## 4. Type checking

**mypy, strict.** The configuration lives in `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
disallow_any_explicit = false
plugins = ["pydantic.mypy"]
```

Strict for the same reason the superseded configuration was strict: these schemas are the
contract with Vapi, and a type error here surfaces as a failed tool call with a customer on the
line. The `tests.*` override relaxes `disallow_untyped_defs` only — test bodies are still
checked.

`# type: ignore` requires a specific error code and a comment explaining why. A bare ignore is
rejected in review.

---

## 5. Code style

**ruff**, for both linting and formatting, at `line-length = 100`, targeting `py312`.

The selected rule families are `E`/`W` (pycodestyle), `F` (pyflakes), `I` (import sorting),
`N` (naming), `UP` (modernisation), `B` (bugbear), `A` (builtin shadowing), `C4`
(comprehensions), `SIM` (simplification), `TCH` (type-checking imports) and `RUF`. `E501` is
ignored because the formatter owns line length. `RUF001`–`RUF003` are ignored because the
generated markdown uses en dashes deliberately — `"length 1–4"` is correct typography, not a
homoglyph.

Naming, since this repository spans four syntaxes:

| Kind | Convention | Example |
|---|---|---|
| Python modules and identifiers | `snake_case` | `check_availability` |
| Classes | `PascalCase` | `CheckAvailability`, `VagaroAdapter` |
| Vapi tool names and n8n node fields | `camelCase` | `checkAvailability` |
| Files, directories, URLs | `kebab-case` | `first-message.txt` |
| DB tables and columns | `snake_case` | `calendar_occupancy`, `starts_at` |
| Queues and job names | `dot.namespaced` | `outbox.dispatch` |
| Metrics | prom `snake_case` + unit | `grace_tool_duration_seconds` |
| Environment variables | `SCREAMING_SNAKE`, prefixed | `GRACE_DATABASE_URL` |

`camelCase` survives in exactly one place: JSON crossing a platform boundary. `checkAvailability`
is the tool name Vapi knows, so it stays `checkAvailability` in the generated JSON while the
Python model defining it is `CheckAvailability`. The generator owns that conversion; no
hand-written mapping table exists, because a hand-written one would drift.

---

## 6. Import boundaries (ADR-0018, invariant I1)

The superseded boundary rules were not a style preference. They were a mechanical control
enforcing the dependency rule in [01-architecture](01-architecture.md) §2, and **ruff cannot
express them** — it can ban a module globally, but not "this package may not import that
package". Without a replacement the protection disappears **silently**: no error, no warning,
just a guarantee that quietly stopped holding.

`import-linter` runs in CI as its own step:

```ini
; TARGET — .importlinter
[importlinter]
root_packages = grace_contracts, grace_domain, grace_db, grace_adapters, grace_api

[importlinter:contract:1]
name = contracts depends on nothing
type = forbidden
source_modules = grace_contracts
forbidden_modules = grace_domain, grace_db, grace_adapters, grace_api

[importlinter:contract:2]
name = domain is pure — no I/O
type = forbidden
source_modules = grace_domain
forbidden_modules = grace_db, grace_adapters, httpx, asyncpg, redis

[importlinter:contract:3]
name = I1 — the hot path cannot reach a third party
type = forbidden
source_modules = grace_api.routes.vapi.handlers
forbidden_modules = grace_adapters
```

Contract 3 is the one that keeps callers off dead air. A handler that needs something from
Vagaro does not call Vagaro; it writes an outbox row and returns, and a worker performs the call
afterwards ([booking-write-path](../reference/booking-write-path.md) §3).

**Prove the rules work rather than trusting them.** AC-02.3 requires deliberately violating each
contract on a throwaway commit, confirming CI goes red, then reverting. A boundary rule nobody
has watched fail is a boundary rule nobody knows is wired up.

---

## 7. The Makefile is the task runner

There is no build-graph tool. A Makefile with explicit targets is legible, has no daemon, no
cache to invalidate and no version of its own to keep current — and at this size, the caching a
build graph would buy is worth less than the simplicity it costs.

| Target | Does |
|---|---|
| `make install` | `uv venv`, then `uv pip install -e ".[dev]"` |
| `make check` | **the full gate, exactly as CI runs it** |
| `make typecheck` · `lint` · `test` | the individual pieces |
| `make vapi-build` | regenerate tool JSON and `system.md` from the Pydantic models |
| `make vapi-validate` | validate generated tools against the live Vapi OpenAPI schema |
| `make vapi-diff` / `vapi-apply` | diff or deploy the assistant. `ENV=dev` unless overridden |
| `make vapi-mock` | run the mock tool server for local web calls |
| `make n8n-lint` | lint workflow JSON before it can reach the instance |
| `make n8n-diff` / `n8n-apply` | diff or publish workflows |
| `make docs` | regenerate the per-tool and per-workflow reference |
| `make docs-check` | fail if that generated reference is stale |
| `make docs-lint` | enforce the document template across `plans/` and `reference/` |

**`make check` is the contract.** CI runs the same targets, so a green `make check` locally means
a green CI — and any divergence between the two is itself a defect to fix, not to work around.

---

## 8. Environment and configuration

Every environment variable is declared in one place with a type, a default where one is safe, and
a description. A missing or malformed variable fails at process start with a readable message
naming the variable — never at 2am on the first request that happens to need it.

The declaration uses `pydantic-settings`, which is the §3 schema mechanism pointed at the
environment instead of at a request body:

```python
#: TARGET — src/grace_api/config.py (excerpt)
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRACE_", frozen=True)

    environment: Literal["development", "test", "staging", "production"]
    log_level: Literal["trace", "debug", "info", "warn", "error"] = "info"
    database_url: PostgresDsn
    database_pool_max: int = Field(default=10, ge=2, le=50)
    redis_url: RedisDsn
    default_tenant_slug: str = "palmleaf"
    business_timezone: str = "America/Chicago"

    vapi_webhook_secret: SecretStr = Field(min_length=32)
    internal_api_token: SecretStr = Field(min_length=32)
    tool_deadline_ms: int = 2500          # ADR-0012. NOT the p95 target.
    hold_ttl_seconds: int = 240
    reservation_ttl_seconds: int = 900
```

`SecretStr` matters: it keeps credentials out of logs and tracebacks by default, which is the
failure mode that actually leaks them.

**Env var inventory.** [infrastructure](../reference/infrastructure.md) §3 maps these onto
environments; this is the list.

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
| `GRACE_N8N_BASE_URL` / `_API_KEY` | platform deploy | ✅ |
| `GRACE_POSTGRES_REPORTING_URL` | n8n reporting workflows — deferred, [04-n8n-layer](04-n8n-layer.md) §9 | ✅ |
| `GRACE_SENTRY_DSN` | all | ➖ |
| `GRACE_OTEL_EXPORTER_OTLP_ENDPOINT` | all | ➖ |
| `GRACE_KILL_SWITCH_ENABLED` | core-api | ➖ |
| `GRACE_FEATURE_TRACK_B` / `_TRACK_A` / `_DEPOSITS` | core-api, workers | ➖ |

Dev secrets come from `.env.local`, which is gitignored. Staging and production secrets come from
the secret manager ([infrastructure](../reference/infrastructure.md) §5). **`.env` files never
contain production values and are never committed** — `.gitignore` carries `.env*` with an
`!.env.example` exception, and that exception file holds names and dummy values only.

---

## 9. Git conventions

**Branches.** `main` is always deployable. Work happens on `feat/<area>-<short>`, `fix/…` or
`chore/…`. No direct pushes to `main`; a pull request with green CI is required. This is
invariant **I9** at the repository level — CI is the only thing that deploys, so CI is the only
thing that may be trusted to have passed.

**Commits.** Conventional Commits, with the roadmap task ID in the footer, so any change can be
traced back to the task that justified it:

```
feat(availability): add tstzrange occupancy repository

Implements the anti-join slot query with a GiST index.
p95 measured at 18ms against 10k occupancy rows.

Task: B-04
```

Scopes: `contracts` `domain` `db` `adapters` `core-api` `worker` `booking-worker` `vapi` `n8n`
`platform` `infra` `ci` `docs` `security`.

**Pull requests state four things:** what changed, which roadmap task it belongs to, which
acceptance criteria are now met, and — if a migration is included — the rollback plan.

---

## 10. Documentation that lives with the code

| File | Contains | Updated when |
|---|---|---|
| `README.md` | the system map and a 10-minute local bootstrap | setup or topology changes |
| [01-architecture](01-architecture.md) §4 | every ADR | a decision is made |
| `Docs/generated/` | per-tool and per-workflow reference | automatically, by `make docs` |
| `Docs/Completed/` | what is verified built, and on what evidence | a work area finishes |
| `platform/*/README.md` | how that platform directory is deployed | its deploy path changes |

**`Docs/generated/` is never hand-edited.** It is written by `make docs` from the tool registry
and the workflow JSON, and `make docs-check` fails CI when a description changes without a
regeneration. That is what makes per-tool documentation impossible to drift — the property the
hand-written set demonstrably could not hold.

---

## 11. Acceptance criteria

✅ **AC-02.1** — `make install && make check` passes from a clean clone on Python 3.12, with no
network access beyond the package index.

✅ **AC-02.2** — Deleting any required environment variable causes a startup failure that names
that variable. Verified by a test constructing `Settings` with the variable absent.

✅ **AC-02.3** — A deliberate violation of each of the three §6 contracts fails CI. Proven on a
throwaway commit, then reverted. *(Restored by ADR-0018; unenforceable between the port and that
decision.)*

✅ **AC-02.4** — `make vapi-build` run twice produces byte-identical output, and
`make vapi-build-check` fails when a Pydantic model changes without regeneration.

✅ **AC-02.5** — `make docs` run twice produces byte-identical output, and `make docs-check` fails
when a tool description changes without regeneration.

✅ **AC-02.6** — CI runs typecheck, lint, tests, generated-artefact currency, Vapi schema
validation and the n8n lint on every pull request, and blocks merge on any failure.

✅ **AC-02.7** — No Pydantic tool model ships a class docstring into its published JSON Schema,
and the validator fails the build if one appears.

## 12. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-02.1** | Does the single-project layout hold once `grace_api` and the workers exist? | One `pyproject.toml` is right for four packages that always deploy together. The booking worker ships a different container with Playwright in it, so it may want its own dependency set. Splitting later is mechanical; splitting now is speculative. | Engineering, at Phase C |
| **Q-02.2** | Should something forbid `grace_domain` from reading the clock? | ADR-0011 requires domain functions to take `now` explicitly. `import-linter` works at module granularity, so it cannot express "not this attribute" — today the guard is review plus unit tests that pass a fixed `now`. A custom ruff rule could close it mechanically. | Engineering |
| **Q-02.3** | Where do database migrations run from in production? | Alembic is settled (ADR-0016); the *execution point* is not. Running them from the API container's entrypoint races as soon as there is more than one replica. [infrastructure](../reference/infrastructure.md) §6 must settle this before the first two-replica deploy. | Engineering, at Phase A |
