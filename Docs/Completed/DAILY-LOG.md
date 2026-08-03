# Daily Log

Technical features and changes shipped, newest first.
Format rules: [DAILY-LOG-GUIDELINES.md](DAILY-LOG-GUIDELINES.md). Full detail: numbered files in this folder.

---

## 3 August 2026

- **Vapi assistant + 15 tools deployed as versioned config**, with drift detection that actually
  converges. Vapi materialises every server default, so a naive local-vs-remote diff is permanently
  red; comparing `remote` against `merge(remote, local)` reports zero drift immediately after apply
  and stays stable when Vapi adds new defaults.

- **Tool contract pipeline built on a single zod registry** — one source generates the 15 tool
  definitions, the prompt's tool table, and the runtime validation. Adding a tool is one row.
  Output is byte-deterministic and CI fails if the committed JSON drifts from the schemas.

- **Offline schema validator that checks every assistant key against the live Vapi OpenAPI.**
  Found four fields that no longer exist (`silenceTimeoutSeconds`, `backchannelingEnabled`,
  `endCallFunctionEnabled`, `backgroundDenoisingEnabled`) and flags any deprecated key. Runs in
  under a second with no API calls.

- **Two Vapi incompatibilities turned from deploy-time 400s into offline failures**: `anyOf`
  (emitted by a constrained `.nullable()`) and scalar `const` (emitted by `z.literal()`) are both
  rejected by Vapi's tool-parameter validator. The generator now fails locally with the fix.

- **Mock tool server + speech engine.** Validates every inbound call against the real zod schemas,
  enforces idempotency on `callId:toolCallId`, supports latency/failure/timeout injection and a
  frozen clock. The spoken-number formatter (times, dates, prices) is covered by 14 tests after it
  produced "Monday the third" for a Tuesday and "one 10-five" for $115.

- **n8n deploy pipeline with three real fixes**: credential placeholders resolved to live IDs
  (n8n resolves strictly by ID, so a name deploys green then throws at first execution),
  dependency-ordered activation (it refuses to publish a workflow whose sub-workflow is unpublished),
  and a version-tolerant activate route after `/publish` returned 405. Three workflows live.

⚠️ **Unproven:** no live call has been placed and no workflow has executed. The assistant points at a
placeholder URL. `export.ts` is a stub, so AC-09.2 is unverified, and the n8n drift comparison is not
normalised — WF-18 re-reports drift on every apply. See [06-pending-and-blocked.md](06-pending-and-blocked.md).
