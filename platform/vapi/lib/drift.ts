/**
 * Merge-based drift detection (doc 08 §8.1).
 *
 * A naive `local` vs `remote` diff is permanently red: Vapi materialises every server
 * default and adds new ones over time. Instead we compare `remote` against
 * `deepMerge(remote, local)` — so drift is non-empty **iff a key we actually declare has a
 * different value remotely**. Keys the server adds and we don't declare are invisible.
 */

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

const VOLATILE = new Set([
  'id',
  'orgId',
  'createdAt',
  'updatedAt',
  'isServerUrlSecretSet',
  'credentialId', // env-injected, instance-specific — masked, not compared
]);

/** Paths whose array order is server-assigned and meaningless. */
const SORT_ARRAYS_AT = new Set(['toolIds', 'structuredOutputIds', 'serverMessages']);

/**
 * Any drift here is a hard failure, never a warning: these are the fields that carry
 * compliance or routing meaning (doc 08 §8.1).
 */
export const FORBIDDEN_DRIFT = [
  'firstMessage',
  'serverMessages',
  'server.url',
  'model.messages.0.content',
  'compliancePlan.hipaaEnabled',
  'compliancePlan.pciEnabled',
  'artifactPlan.transcriptPlan.enabled',
];

export function isObject(v: unknown): v is Record<string, Json> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** `local` overlays `remote`. Arrays are replaced wholesale, never merged element-wise. */
export function deepMerge(remote: Json, local: Json): Json {
  if (!isObject(remote) || !isObject(local)) return local;
  const out: Record<string, Json> = { ...remote };
  for (const [k, v] of Object.entries(local)) {
    const prev = out[k];
    out[k] = isObject(prev) && isObject(v) ? deepMerge(prev, v) : v;
  }
  return out;
}

/** Strips volatile keys, sorts unordered arrays, and canonicalises for comparison. */
export function normalise(value: Json, key = ''): Json {
  if (Array.isArray(value)) {
    const items = value.map((v) => normalise(v));
    if (SORT_ARRAYS_AT.has(key)) {
      return [...items].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    }
    return items;
  }
  if (isObject(value)) {
    const out: Record<string, Json> = {};
    for (const k of Object.keys(value).sort()) {
      if (VOLATILE.has(k)) continue;
      const v = value[k];
      if (v === undefined || v === null) continue; // null ≡ absent
      out[k] = normalise(v, k);
    }
    return out;
  }
  if (typeof value === 'string') return value.trimEnd();
  return value;
}

export interface DriftEntry {
  path: string;
  remote: Json | undefined;
  desired: Json | undefined;
  forbidden: boolean;
}

function isForbidden(path: string): boolean {
  return FORBIDDEN_DRIFT.some((f) => path === f || path.startsWith(`${f}.`));
}

/** Reports only paths present in `desired` — i.e. paths we declare. */
export function diff(remote: Json, desired: Json, base = ''): DriftEntry[] {
  const out: DriftEntry[] = [];

  if (isObject(remote) && isObject(desired)) {
    for (const k of Object.keys(desired)) {
      out.push(...diff(remote[k] ?? null, desired[k] ?? null, base ? `${base}.${k}` : k));
    }
    return out;
  }

  if (JSON.stringify(remote) !== JSON.stringify(desired)) {
    out.push({
      path: base,
      remote: remote === null ? undefined : remote,
      desired: desired === null ? undefined : desired,
      forbidden: isForbidden(base),
    });
  }
  return out;
}

export function computeDrift(remoteRaw: Json, localRaw: Json): DriftEntry[] {
  const remote = normalise(remoteRaw);
  const desired = normalise(deepMerge(remoteRaw, localRaw));
  return diff(remote, desired);
}
