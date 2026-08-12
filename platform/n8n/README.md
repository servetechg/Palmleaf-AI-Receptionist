# platform/n8n

Config-as-code for the n8n workflows (ADR-0010). Single n8n Cloud instance; dev and prod are the
same instance, separated by tag + name prefix + webhook path prefix + per-env credentials — see
Completed/EXECUTED-vapi-n8n-plan §A2 for the full scheme and the reasoning (ADR-0013 relaxes invariant I9 for this setup).

**Read [`Docs/plans/19-vapi-n8n-execution-plan.md`](../../Docs/plans/19-vapi-n8n-execution-plan.md)
before touching this directory.** The original spec (04-n8n-layer) has a broken credential-normalisation
scheme that deploys green and throws at first execution — Completed/EXECUTED-vapi-n8n-plan §A2 lists every correction.

## Layout

```
workflows/WF-*.json        one file per workflow, env-neutral — env applied at deploy time
credentials.example.json   documents which credentials must exist on the instance, never values
lint.ts                     15 structural rules (§5 of 04-n8n-layer, extended by Completed/EXECUTED-vapi-n8n-plan §A2 point 5)
export.ts                   pull from the instance → normalise → write files (deterministic diffs)
deploy.ts                   tag-filtered push: publish (not activate), activeVersion verification
```

## Status

Populated in build step **B5** of Completed/EXECUTED-vapi-n8n-plan, after WF-00 (global error workflow) through WF-18 are
authored via the n8n MCP server against `[dev]`-tagged workflows.
