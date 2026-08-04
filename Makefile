# Grace — platform tooling. Everything runs through the project venv.
PY := .venv/bin/python

.PHONY: install check lint typecheck test docs docs-check docs-lint \
        vapi-generate vapi-prompt vapi-build vapi-validate vapi-diff vapi-apply vapi-mock \
        n8n-lint n8n-diff n8n-apply

install:
	uv venv && uv pip install -e ".[dev]"

## The full T1 gate, exactly as CI runs it.
# NOTE: docs-lint is deliberately NOT in `check` yet. It passes on the documents that have
# been rewritten and fails on the ~19 that have not — that is Part C of the restructure, still
# outstanding. Wiring it in now would make `check` permanently red for a reason already
# tracked. Run `make docs-lint` to see the remaining work; add it here when Part C lands.
check: typecheck lint test vapi-build-check vapi-validate n8n-lint docs-check

typecheck:
	$(PY) -m mypy src tests

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

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
