// Tag-filtered push to the single n8n Cloud instance (doc 19 §A2 point 4):
//   1. GET /api/v1/workflows?tags=managed:git,env:{env}  → name→id map, from this filtered set only
//   2. GET /api/v1/credentials                            → name→id map, resolve __CRED__: placeholders
//   3. Render env (name prefix, webhook path prefix, credential ids, errorWorkflow id)
//   4. Refuse on a naming/tag mismatch or an env:dev/env:prod name collision
//   5. PUT /workflows/{id} with EXACTLY { name, nodes, connections, settings } (additionalProperties: false)
//   6. PUT /workflows/{id}/tags
//   7. POST /workflows/{id}/publish for workflows marked active (NOT the deprecated /activate)
//   8. Re-fetch and assert against activeVersion.nodes/connections, not the draft
//   9. Any env:{env},managed:git workflow with no local file → orphan, fail
//
//   --diff     print the delta. Default in CI on PRs.
//   --apply    apply. Fails hard on any unresolved __CRED__ or __WF__ placeholder.
//   --env dev|prod
//
// TODO(build step B5): implement once the first workflow (WF-12) exists.

export {};
