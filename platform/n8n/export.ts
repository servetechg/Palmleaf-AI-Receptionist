// Pulls workflows from the n8n instance, normalises them for deterministic diffs, writes
// ./workflows/*.json. Strips id/versionId/createdAt/updatedAt/meta.instanceId; keeps node id and
// webhookId (doc 19 §A2 point 3 — stripping webhookId silently changes the production webhook URL).
// Uses `?excludePinnedData=true` instead of hand-stripping pinData.
//
// TODO(build step B5): implement.

export {};
