# @grace/contracts

Zod input/output schema for each of Grace's 13 Vapi tools. Zero runtime dependency except `zod`
(and `zod-to-json-schema`, used only by `platform/vapi/generate-tools.ts` to derive the JSON Schema
Vapi sees — never imported from a schema file itself).

**Rules** (doc 02 §4, doc 19 Part A1):
- Every input schema is `.strict()` — an unexpected field from the model is a loud validation error.
- Every field has `.describe()` — that text is prompt real estate the model reads verbatim.
- This package imports nothing from `@grace/*`. Enforced by `eslint.config.js`.

## Layout

```
src/
├── tools/       one file per tool: <Name>Input, <Name>Output, z.infer types
├── errors/      shared error taxonomy (doc 04 §7) — used by platform/vapi/mock-server too
└── index.ts     barrel export
```

## Status

Schemas for all 13 tools land in build step **B2** — see
[`Docs/plans/19-vapi-n8n-execution-plan.md`](../../Docs/plans/19-vapi-n8n-execution-plan.md).
Only `checkAvailability` has a fully-specified shape in the docs today (doc 02 §4); the rest are
authored from the tool table in doc 08/19 §A1.
