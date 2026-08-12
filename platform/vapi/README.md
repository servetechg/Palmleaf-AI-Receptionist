# platform/vapi

Config-as-code for the Vapi assistant "Grace" (ADR-0010). Nothing here is edited by hand except
`prompts/` and `assistants/grace.json`'s non-generated fields — everything under `tools/` is derived
and CI-checked for drift.

**Read [`Docs/plans/19-vapi-n8n-execution-plan.md`](../../Docs/plans/19-vapi-n8n-execution-plan.md)
before touching this directory.** The original spec (03-vapi-layer) contains config verified not to work
against the current Vapi API — Completed/EXECUTED-vapi-n8n-plan §A1 lists every correction.

## Layout

```
assistants/grace.json      the assistant definition, minus tool ids (injected at deploy)
tools/*.json                GENERATED from packages/contracts — DO NOT HAND-EDIT
tools/transferToHuman.json  the one hand-authored exception — a transferCall tool, not generated
prompts/system.md           assembled from sections/ at build time
prompts/sections/           identity, style, grounding, tools, booking, screening, escalation
prompts/first-message.txt   ★ protected file — I7, CI-checked, requires legal-reviewed label
simulations/                Vapi Simulations specs (T2 chat / T3 voice) — replaces deprecated Test Suites
mock-server/                dev-only tool server; same envelope shape as Core API (§B4)
web-harness/                @vapi-ai/web test page — our only test channel until a number exists
generate-tools.ts           zod (packages/contracts) → JSON Schema → tools/*.json
deploy.ts                   diff + apply against the Vapi REST API
```

## Status

Populated in build steps **B3** (assistant, prompts, generate/deploy) and **B4** (mock server, web
harness) of Completed/EXECUTED-vapi-n8n-plan. `assistants/grace.json` is not written until 03-vapi-layer's rewrite (Completed/EXECUTED-vapi-n8n-plan §A1) lands,
so that the checked-in config matches the verified API — not the six defects Completed/EXECUTED-vapi-n8n-plan found in the
original spec (dead `server.secret`, invalid `analysisPlan` fields, a `serverMessages` list that
silently drops the end-of-call report, etc.).
