# Grace — platform tooling. Everything runs through the project venv.
PY := .venv/bin/python

## Load .env if it exists, and pass it to every recipe. Optional by design:
## `make check` must run with no secrets at all, which is what CI does.
##
## ⚠️ A value in .env OVERRIDES the same variable exported in your shell —
## including an empty one, which is why .env.example keeps unset variables
## commented out rather than assigned blank. Verified, not assumed: make
## resolves a makefile assignment ahead of an inherited environment value.
## Template and format rules: .env.example (never commit .env).
-include .env
export

.PHONY: install check lint typecheck test docs docs-check docs-lint tunnel \
        vapi-generate vapi-prompt vapi-build vapi-validate vapi-diff vapi-apply vapi-mock \
        vapi-harness \
        n8n-lint n8n-diff n8n-apply rc-snapshot \
        db-up db-down db-migrate db-seed db-psql db-devfixture kb-apply imports api-run \
        vagaro-discover

install:
	uv venv && uv pip install -e ".[dev]"

## The full T1 gate, exactly as CI runs it.
check: typecheck lint imports test vapi-build-check vapi-validate n8n-lint docs-check docs-lint

typecheck:
	$(PY) -m mypy src tests

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

## Invariant I1, mechanically: a caller is waiting on the line, so the code path
## serving them must not be able to reach Vagaro, Stripe, Twilio or Google.
imports:
	.venv/bin/lint-imports

test:
	$(PY) -m pytest

## ── Vapi ─────────────────────────────────────────────────────────────────────
vapi-generate:
	$(PY) -m grace_platform.vapi.generate_tools

vapi-prompt:
	$(PY) -m grace_platform.vapi.build_prompt

vapi-build: vapi-generate vapi-prompt

vapi-build-check:
	$(PY) -m grace_platform.vapi.generate_tools --check
	$(PY) -m grace_platform.vapi.build_prompt --check

vapi-validate:
	$(PY) -m grace_platform.vapi.validate

vapi-diff:
	$(PY) -m grace_platform.vapi.deploy --env $(or $(ENV),dev) --diff

vapi-apply:
	$(PY) -m grace_platform.vapi.deploy --env $(or $(ENV),dev) --apply

vapi-mock:
	$(PY) -m grace_platform.vapi.mock_server.server

## The browser page that talks to Grace — the only test channel until a number is live.
## Needs VAPI_PUBLIC_KEY (browser-safe, NOT VAPI_API_KEY) and a completed vapi-apply.
vapi-harness:
	$(PY) -m grace_platform.vapi.harness

## ── tunnel ───────────────────────────────────────────────────────────────────
## Vapi has to reach the mock server from the internet, so local development needs
## a public URL for it. NOT `vapi listen`: that forwards Vapi's own webhooks to a
## local port and does not give the tools a reachable https origin.
##
## The tunnel is a laptop process, not infrastructure (loophole L5) — supervised
## test windows only. Unattended customer traffic waits for a hosted endpoint.
tunnel:
	@echo ""
	@echo "  Tunnelling http://localhost:$${GRACE_MOCK_PORT:-4242} (run 'make vapi-mock' in another terminal)."
	@echo "  When the URL appears, put these two lines in .env — replacing <tunnel>:"
	@echo ""
	@echo "      GRACE_TOOLS_URL=https://<tunnel>/vapi/tools"
	@echo "      GRACE_EVENTS_URL=https://<tunnel>/webhooks/vapi/events"
	@echo ""
	@echo "  then, in a third terminal:  make vapi-apply ENV=dev"
	@echo ""
	@command -v cloudflared >/dev/null 2>&1 \
	  || { echo "  ✗ cloudflared is not installed."; \
	       echo "    Install:   Linux → https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"; \
	       echo "               macOS → brew install cloudflared"; \
	       echo "    Or use ngrok instead:  ngrok http $${GRACE_MOCK_PORT:-4242}"; \
	       echo ""; exit 1; }
	cloudflared tunnel --url http://localhost:$${GRACE_MOCK_PORT:-4242}

## ── documentation ────────────────────────────────────────────────────────────
## Per-tool and per-workflow reference, generated from the code that defines them,
## so it cannot drift. Hand-written planning docs are checked by docs-lint instead.
docs:
	$(PY) -m grace_platform.docs.gen_tools
	$(PY) -m grace_platform.docs.gen_workflows

docs-check:
	$(PY) -m grace_platform.docs.gen_tools --check
	$(PY) -m grace_platform.docs.gen_workflows --check

docs-lint:
	$(PY) -m grace_platform.docs.lint_docs

## ── n8n ──────────────────────────────────────────────────────────────────────
n8n-lint:
	$(PY) -m grace_platform.n8n.lint

n8n-diff:
	$(PY) -m grace_platform.n8n.deploy --env $(or $(ENV),dev) --diff

n8n-apply:
	$(PY) -m grace_platform.n8n.deploy --env $(or $(ENV),dev) --apply

## ── database ────────────────────────────────────────────────────────────────
## Local Postgres for development. NOT the hosted instance unattended operation will
## need — see the Vagaro plan's hosting gate. Port 5434, because this machine already
## runs a native Postgres on 5432.
db-up:
	@command -v docker >/dev/null 2>&1 || { echo "  ✗ docker is not installed — see https://docs.docker.com/engine/install/"; exit 1; }
	docker compose up -d
	@printf "  waiting for postgres"; \
	 for i in $$(seq 1 30); do \
	   docker exec grace-postgres pg_isready -U grace -d grace >/dev/null 2>&1 && { echo " ✓"; exit 0; }; \
	   printf "."; sleep 1; \
	 done; echo " ✗ timed out"; exit 1

db-down:
	docker compose down

db-migrate:
	$(PY) -m grace_db.migrate

db-seed:
	$(PY) -m grace_db.seeds

## What Grace is allowed to say, from a file a non-developer can edit.
## Only entries marked approved reach a caller.
kb-apply:
	$(PY) -m grace_db.kb_apply platform/knowledge/palmleaf.yaml

db-psql:
	docker exec -it grace-postgres psql -U grace -d grace

## Satisfies the availability freshness gate so the booking path can be tested without
## Vagaro. The timestamp it writes STALES AFTER 30 MINUTES — re-run before each test
## session, or checkAvailability answers "I'm having trouble reaching the schedule".
db-devfixture:
	docker exec -i grace-postgres psql -U grace -d grace -v ON_ERROR_STOP=1 \
	  < platform/postgres/dev-fixtures/mirror-freshness.sql
	@echo "  ✓ mirror fixture applied — availability answerable for the next 30 minutes"

## ── the tool server ─────────────────────────────────────────────────────────
## What Vapi calls. Point GRACE_TOOLS_URL at this through a tunnel to use it.
api-run:
	.venv/bin/uvicorn grace_api.main:app --host 0.0.0.0 --port $(or $(PORT),8080)

## ── customer messaging ───────────────────────────────────────────────────────
## Drains queued SMS/email. Runs happily with no credentials — it reports what it would
## have sent and leaves the rows queued, so a missing key never becomes a broken promise.
messenger:
	$(PY) -m grace_workers.messenger

## ── Vagaro ───────────────────────────────────────────────────────────────────
## READ-ONLY probe of what the API can actually do. Run it the day the activation
## email lands; its output sets the capability flags. Never writes to Vagaro.
vagaro-discover:
	$(PY) -m grace_platform.vagaro.discovery

## ── RingCentral ──────────────────────────────────────────────────────────────
## READ-ONLY. Snapshots the live account into platform/ringcentral/snapshot/ and
## reports drift against what is committed. No write path exists in this phase —
## the pre-Grace state of a real business phone line is the rollback reference.
rc-snapshot:
	$(PY) -m grace_platform.ringcentral.snapshot
