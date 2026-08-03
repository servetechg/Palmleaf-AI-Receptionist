/**
 * Generates platform/vapi/tools/*.json from the zod registry in @grace/contracts.
 *
 * Runs in CI. If a generated file differs from what is committed, CI fails — the tool
 * schema published to Vapi and the schema the handler validates against cannot drift
 * (doc 02 §4, doc 08 §2).
 *
 *   pnpm platform:vapi:generate           write files
 *   pnpm platform:vapi:generate --check   exit 1 if anything would change (CI / T1)
 */
import { createHash } from 'node:crypto';
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { HAND_AUTHORED_TOOLS, TOOL_REGISTRY, type ToolSpec } from '@grace/contracts';
import { zodToJsonSchema } from 'zod-to-json-schema';

const TOOLS_DIR = join(import.meta.dirname, 'tools');

/** Env placeholders, substituted by deploy.ts. Never a literal URL in a committed file. */
const TOOLS_URL = '${GRACE_TOOLS_URL}';
const TOOLS_CREDENTIAL_ID = '${VAPI_TOOLS_CREDENTIAL_ID}';

/** Read tools may be retried; write tools may not — a retried booking is a real duplicate. */
const READ_BACKOFF = {
  type: 'fixed',
  maxRetries: 1,
  baseDelaySeconds: 1,
  excludedStatusCodes: [400, 401, 409, 422],
} as const;

/**
 * Vapi requires every tool parameter to carry a plain `type`. It rejects `anyOf` with
 * `400 function.parameters.properties.X.type must be one of …` — verified against the live
 * API on 2026-08-03, after `.nullable().max(60)` rendered as `anyOf` and broke a deploy.
 *
 * Catching it here turns a deploy-time 400 into an offline failure with a fix instruction.
 */
function assertVapiCompatible(toolName: string, parameters: unknown): void {
  const walk = (node: unknown, path: string): void => {
    if (Array.isArray(node)) {
      node.forEach((n, i) => { walk(n, `${path}[${String(i)}]`); });
      return;
    }
    if (!node || typeof node !== 'object') return;
    const obj = node as Record<string, unknown>;

    for (const combinator of ['anyOf', 'oneOf', 'allOf'] as const) {
      if (combinator in obj) {
        throw new Error(
          `${toolName}: parameter "${path}" renders as \`${combinator}\`, which Vapi rejects.\n` +
            `    Cause: a nullable field with a constraint, e.g. .max(60).nullable().\n` +
            `    Fix:   use .optional() instead of .nullable() on tool INPUT schemas.`,
        );
      }
    }
    // Vapi: "const must be an object" — it does not accept a scalar const.
    if ('const' in obj && (typeof obj['const'] !== 'object' || obj['const'] === null)) {
      throw new Error(
        `${toolName}: parameter "${path}" emits a scalar \`const\`, which Vapi rejects.\n` +
          `    Cause: z.literal(...) on a tool INPUT schema.\n` +
          `    Fix:   use the plain type (z.boolean(), z.string()) and enforce the value in the handler.`,
      );
    }
    if ('$ref' in obj) {
      throw new Error(`${toolName}: parameter "${path}" contains a $ref; Vapi cannot resolve them.`);
    }
    for (const [k, v] of Object.entries(obj)) walk(v, path ? `${path}.${k}` : k);
  };
  walk(parameters, '');
}

function buildToolJson(spec: ToolSpec): Record<string, unknown> {
  const parameters = zodToJsonSchema(spec.input as Parameters<typeof zodToJsonSchema>[0], {
    target: 'jsonSchema7',
    // Inline everything: Vapi has no $ref resolver for tool parameters.
    $refStrategy: 'none',
  });
  // zodToJsonSchema emits a $schema key; Vapi rejects unknown keys on some paths.
  delete (parameters as Record<string, unknown>)['$schema'];
  assertVapiCompatible(spec.name, parameters);

  const messages: Array<Record<string, unknown>> = [];
  if (spec.requestStart) {
    messages.push({
      type: 'request-start',
      content: spec.requestStart,
      // Async tools never deliver a result to the model, so the filler IS the answer.
      blocking: spec.async,
    });
  }
  if (spec.requestFailed) {
    messages.push({ type: 'request-failed', content: spec.requestFailed });
  }

  const server: Record<string, unknown> = {
    url: TOOLS_URL,
    credentialId: TOOLS_CREDENTIAL_ID,
    timeoutSeconds: 10,
  };
  if (!spec.write) server['backoffPlan'] = READ_BACKOFF;

  return {
    type: 'function',
    async: spec.async,
    function: {
      name: spec.name,
      description: spec.description,
      parameters,
    },
    server,
    ...(messages.length > 0 ? { messages } : {}),
  };
}

/** Deterministic output: sorted keys, trailing newline. Byte-identical across runs. */
function stableStringify(value: unknown): string {
  const sortDeep = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sortDeep);
    if (v && typeof v === 'object') {
      return Object.fromEntries(
        Object.entries(v as Record<string, unknown>)
          .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
          .map(([k, val]) => [k, sortDeep(val)]),
      );
    }
    return v;
  };
  return `${JSON.stringify(sortDeep(value), null, 2)}\n`;
}

function main(): void {
  const check = process.argv.includes('--check');
  mkdirSync(TOOLS_DIR, { recursive: true });

  const generated = new Map<string, string>();
  for (const spec of TOOL_REGISTRY) {
    generated.set(`${spec.name}.json`, stableStringify(buildToolJson(spec)));
  }

  // Files we must never touch or report as stale.
  const protectedFiles = new Set([
    'README.md',
    ...HAND_AUTHORED_TOOLS.map((n) => `${n}.json`),
  ]);

  const onDisk = readdirSync(TOOLS_DIR).filter((f) => !protectedFiles.has(f));
  const problems: string[] = [];

  for (const [file, content] of generated) {
    const path = join(TOOLS_DIR, file);
    let existing: string | null = null;
    try {
      existing = readFileSync(path, 'utf8');
    } catch {
      /* new file */
    }
    if (existing === content) continue;

    if (check) {
      problems.push(existing === null ? `missing: ${file}` : `stale:   ${file}`);
    } else {
      writeFileSync(path, content, 'utf8');
      console.log(`${existing === null ? 'created' : 'updated'}  tools/${file}`);
    }
  }

  // A tool removed from the registry must not linger in Vapi.
  for (const file of onDisk) {
    if (generated.has(file)) continue;
    if (check) problems.push(`orphan:  ${file} (no registry entry)`);
    else {
      rmSync(join(TOOLS_DIR, file));
      console.log(`removed  tools/${file}`);
    }
  }

  if (check && problems.length > 0) {
    console.error('\n✗ generated tool JSON is out of date:\n');
    for (const p of problems) console.error(`    ${p}`);
    console.error('\n  Run: pnpm platform:vapi:generate  and commit the result.\n');
    process.exit(1);
  }

  const digest = createHash('sha256')
    .update([...generated.entries()].sort().map(([k, v]) => k + v).join(''))
    .digest('hex')
    .slice(0, 12);
  console.log(
    check
      ? `✓ ${String(generated.size)} tool schemas up to date (${digest})`
      : `✓ wrote ${String(generated.size)} tool schemas (${digest})`,
  );
}

main();
