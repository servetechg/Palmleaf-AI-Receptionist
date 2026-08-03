// Dev-only tool server. Exposes the same two routes as Core API will (`/vapi/tools`,
// `/webhooks/vapi/events`) with the same envelope shape, so switching to the real Core API later
// is a one-line env var change. Validates arguments with the REAL zod schemas from
// @grace/contracts — this is what proves the generated JSON Schema and the zod schema agree
// under a live model, months before Core API exists.
//
// Without this, every one of the 13 tools returns nothing on a web call and nothing about the
// prompt, the medical gate, the PCI refusal, or the generated schemas can be validated. See
// doc 19 §B4.
//
// TODO(build step B4): implement — node:http server, fixtures.ts, clock.ts, fault injection via
// GRACE_MOCK_LATENCY_MS / GRACE_MOCK_FAIL / GRACE_MOCK_TIMEOUT.

export {};
