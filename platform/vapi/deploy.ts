// diff + apply against the Vapi REST API. Diffs `remote` against `deepMerge(remote, local)` — not
// `local` against `remote` — because Vapi materialises every server default and a naive diff would
// never reach zero (doc 19 §A1 point on AC-08.1).
//
//   --diff     print the delta between local JSON and the remote assistant/tools. Default in CI on PRs.
//   --apply    apply. Refuses on a dirty git tree; refuses if first-message.txt fails the I7 check.
//   --env dev|prod
//
// TODO(build step B3): implement once assistants/grace.json and tools/*.json exist.

export {};
