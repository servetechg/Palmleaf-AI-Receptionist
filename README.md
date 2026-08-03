# palmleaf-grace

Grace — the AI receptionist for PalmLeaf Massage & Wellness.

**Start here:** [`Docs/plans/00-INDEX.md`](Docs/plans/00-INDEX.md).

## Current phase

Active work is scoped to the **Vapi conversation layer** and the **n8n orchestration layer** only —
see [`Docs/plans/19-vapi-n8n-execution-plan.md`](Docs/plans/19-vapi-n8n-execution-plan.md). Full
platform build order (Core API, Postgres, workers) resumes from
[`Docs/plans/15-implementation-roadmap.md`](Docs/plans/15-implementation-roadmap.md) once Vagaro,
RingCentral, Stripe and Google access unblock.

`Docs/plans/08-vapi-layer.md` and `09-n8n-layer.md` contain config verified **not** to work against
the current Vapi and n8n APIs. Do not implement them as written — read doc 19 first.

## Layout

```
packages/contracts/   zod schemas for the 13 Vapi tools — zero deps but zod
platform/vapi/        Vapi assistant config-as-code (ADR-0010)
platform/n8n/         n8n workflow config-as-code (ADR-0010)
```

## Setup

```bash
corepack enable --install-directory ~/.local/bin pnpm   # if `pnpm` isn't already on PATH
pnpm install
```

MCP setup (Vapi + n8n authoring access) is in doc 19 §Step 0.
