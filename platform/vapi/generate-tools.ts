// Reads every tool schema from @grace/contracts, converts input/output zod schemas to JSON Schema
// via zod-to-json-schema, and writes platform/vapi/tools/*.json.
//
// Runs in CI (doc 02 §2 "invariants" stage): if a generated file differs from what is committed,
// CI fails — the tool schema and the handler cannot drift (doc 08/19 §2, §A1).
//
// TODO(build step B3): implement once @grace/contracts has all 13 tool schemas (step B2) and
// doc 08's rewrite (doc 19 §A1) has settled the tool JSON shape — server.url/credentialId split,
// backoffPlan on read tools only, transferToHuman excluded (hand-authored, see tools/README).

export {};
