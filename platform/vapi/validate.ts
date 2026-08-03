/**
 * T1 static gate (doc 08 §9.1). Validates every local Vapi artefact OFFLINE, against the
 * Vapi OpenAPI spec plus our own invariants. No network calls to Vapi, no cost, <1s.
 *
 * This is the tier that would have caught the defects the 2026-08-03 verification pass
 * found — `server.secret`, `analysisPlan.structuredDataSchema`, a truncated
 * `serverMessages` — before they ever reached a deploy.
 *
 *   pnpm platform:vapi:validate
 *
 * The spec is cached at platform/vapi/.vapi-openapi.json (gitignored). Refresh with
 * --refresh; CI passes --refresh so it always checks against current reality.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { HAND_AUTHORED_TOOLS, TOOL_REGISTRY } from '@grace/contracts';

const HERE = import.meta.dirname;
const SPEC_URL = 'https://api.vapi.ai/api-json';
const SPEC_CACHE = join(HERE, '.vapi-openapi.json');

const problems: string[] = [];
const warnings: string[] = [];
function fail(m: string): void {
  problems.push(m);
}
function warn(m: string): void {
  warnings.push(m);
}

function readJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, 'utf8')) as Record<string, unknown>;
}

async function loadSpec(refresh: boolean): Promise<Record<string, unknown> | null> {
  if (!refresh && existsSync(SPEC_CACHE)) return readJson(SPEC_CACHE);
  try {
    const res = await fetch(SPEC_URL);
    if (!res.ok) throw new Error(`HTTP ${String(res.status)}`);
    const spec = (await res.json()) as Record<string, unknown>;
    mkdirSync(HERE, { recursive: true });
    writeFileSync(SPEC_CACHE, JSON.stringify(spec), 'utf8');
    return spec;
  } catch (err) {
    warn(`could not fetch the Vapi OpenAPI spec (${String(err)}) — schema checks skipped`);
    return existsSync(SPEC_CACHE) ? readJson(SPEC_CACHE) : null;
  }
}

/** Collects the allowed property names for a schema, following one level of allOf/$ref. */
function propsOf(spec: Record<string, unknown>, schemaName: string): Set<string> {
  const schemas = ((spec['components'] as Record<string, unknown> | undefined)?.['schemas'] ??
    {}) as Record<string, { properties?: Record<string, unknown> }>;
  return new Set(Object.keys(schemas[schemaName]?.properties ?? {}));
}

function deprecatedProps(spec: Record<string, unknown>, schemaName: string): Set<string> {
  const schemas = ((spec['components'] as Record<string, unknown> | undefined)?.['schemas'] ??
    {}) as Record<string, { properties?: Record<string, { deprecated?: boolean }> }>;
  const props = schemas[schemaName]?.properties ?? {};
  return new Set(Object.entries(props).filter(([, v]) => v.deprecated).map(([k]) => k));
}

async function main(): Promise<void> {
  const spec = await loadSpec(process.argv.includes('--refresh'));

  // ── grace.json ───────────────────────────────────────────────────────────────
  const assistantPath = join(HERE, 'assistants', 'grace.json');
  const assistant = readJson(assistantPath);

  if (spec) {
    const allowed = propsOf(spec, 'CreateAssistantDTO');
    const deprecated = deprecatedProps(spec, 'CreateAssistantDTO');
    if (allowed.size === 0) warn('CreateAssistantDTO not found in spec — key check skipped');

    for (const key of Object.keys(assistant)) {
      if (allowed.size > 0 && !allowed.has(key)) {
        fail(`grace.json: "${key}" is not a property of CreateAssistantDTO`);
      }
      if (deprecated.has(key)) {
        fail(`grace.json: "${key}" is DEPRECATED in the current Vapi API`);
      }
    }

    const server = assistant['server'] as Record<string, unknown> | undefined;
    if (server) {
      const serverProps = propsOf(spec, 'Server');
      for (const key of Object.keys(server)) {
        if (serverProps.size > 0 && !serverProps.has(key)) {
          fail(`grace.json: server.${key} is not a property of Server (did you mean credentialId?)`);
        }
      }
    }
  }

  // ── I7: the greeting must be injected, never inlined ─────────────────────────
  const firstMessage = String(assistant['firstMessage'] ?? '');
  if (!firstMessage.includes('injected from prompts/first-message.txt')) {
    fail('I7: grace.json must inject firstMessage from prompts/first-message.txt, never inline it');
  }
  const greeting = readFileSync(join(HERE, 'prompts', 'first-message.txt'), 'utf8');
  if (!/may be recorded/i.test(greeting)) {
    fail('I7: prompts/first-message.txt is missing the recording disclosure ("may be recorded")');
  }
  if (!/virtual assistant|AI assistant/i.test(greeting)) {
    fail('I7: prompts/first-message.txt is missing the AI disclosure');
  }

  // ── serverMessages must include end-of-call-report ───────────────────────────
  const serverMessages = (assistant['serverMessages'] ?? []) as string[];
  if (!serverMessages.includes('end-of-call-report')) {
    fail(
      'serverMessages omits "end-of-call-report" — setting this field REPLACES the defaults, so the ' +
        'call-summary/QA/redaction pipeline would silently never run (doc 08 §3.2)',
    );
  }
  if (!serverMessages.includes('transfer-destination-request')) {
    fail('serverMessages omits "transfer-destination-request" — transfers cannot resolve a destination');
  }
  for (const streaming of ['conversation-update', 'transcript', 'speech-update', 'model-output']) {
    if (serverMessages.includes(streaming)) {
      fail(
        `serverMessages includes "${streaming}" — that streams raw caller utterances before redaction ` +
          `(I5/I6 risk, doc 08 §3.2). Remove it.`,
      );
    }
  }

  // ── analysisPlan must be gone ────────────────────────────────────────────────
  if ('analysisPlan' in assistant) {
    fail('grace.json uses analysisPlan, which is deprecated in full. Use artifactPlan.structuredOutputIds');
  }

  // ── tools ────────────────────────────────────────────────────────────────────
  for (const t of TOOL_REGISTRY) {
    const p = join(HERE, 'tools', `${t.name}.json`);
    if (!existsSync(p)) {
      fail(`tools/${t.name}.json is missing — run pnpm platform:vapi:generate`);
      continue;
    }
    const tool = readJson(p);
    const server = tool['server'] as Record<string, unknown> | undefined;
    if (!server?.['url']) fail(`tools/${t.name}.json: server.url is missing`);
    if (server && 'secret' in server) {
      fail(`tools/${t.name}.json: server.secret does not exist in the Vapi API — use credentialId`);
    }
    if (tool['async'] !== t.async) {
      fail(`tools/${t.name}.json: async flag disagrees with the registry`);
    }
    // Async tools never deliver a result to the model, so they need a spoken filler —
    // unless the prompt guarantees the very next tool speaks (flagEscalation → transfer).
    // `as const` narrows each entry to its literal type, so the optional flag is only
    // present on the entries that set it — hence the `in` guard rather than `t.x`.
    const ackedByNextTool = 'ackedByNextTool' in t && t.ackedByNextTool === true;
    if (t.async && !ackedByNextTool && !Array.isArray(tool['messages'])) {
      fail(
        `tools/${t.name}.json is async but has no request-start message — the caller would hear ` +
          `silence, because an async result never reaches the model (doc 08 §4.2)`,
      );
    }
    // Write tools must not retry: a retried booking is a real duplicate.
    if (t.write && server && 'backoffPlan' in server) {
      fail(`tools/${t.name}.json is a write tool and must not carry a backoffPlan (doc 08 §4.1)`);
    }
  }

  // ── hand-authored tools (Vapi tool types, not function tools) ────────────────
  const EXPECTED_TYPE: Record<string, string> = {
    transferToHuman: 'transferCall',
    endCall: 'endCall',
  };
  for (const name of HAND_AUTHORED_TOOLS) {
    const p = join(HERE, 'tools', `${name}.json`);
    if (!existsSync(p)) {
      fail(`tools/${name}.json is missing (hand-authored, not generated)`);
      continue;
    }
    const tool = readJson(p);
    if (tool['type'] !== EXPECTED_TYPE[name]) {
      fail(`tools/${name}.json must be type "${String(EXPECTED_TYPE[name])}", got "${String(tool['type'])}"`);
    }
    // Neither type accepts parameters — that is precisely why flagEscalation exists.
    if ('function' in tool) {
      fail(
        `tools/${name}.json has a "function" property. Its DTO has none, so the model cannot pass ` +
          `arguments to it (doc 08 §7.1)`,
      );
    }
    if (name === 'transferToHuman') {
      if (!Array.isArray(tool['destinations']) || (tool['destinations'] as unknown[]).length > 0) {
        fail(`tools/transferToHuman.json: destinations must be [] so Vapi asks our server for it`);
      }
    }
  }

  // endCallFunctionEnabled was removed from the API; hanging up is a tool now.
  if ('endCallFunctionEnabled' in assistant) {
    fail('grace.json: endCallFunctionEnabled no longer exists — register tools/endCall.json instead');
  }

  // ── structured outputs ───────────────────────────────────────────────────────
  const so = readJson(join(HERE, 'structured-outputs', 'call-outcome.json'));
  const soProps = ((so['schema'] as Record<string, unknown>)['properties'] ?? {}) as Record<
    string,
    { type?: string; enum?: unknown[] }
  >;
  for (const [key, def] of Object.entries(soProps)) {
    // Free-text in a structured output is a PHI route: an LLM summarising a transcript
    // that may contain health disclosures, written to a persisted column (I6).
    if (def.type === 'string' && !def.enum && !/Ref$|^provider/.test(key)) {
      warn(`structured-output "${key}" is free text — prefer a closed enum or boolean (I6)`);
    }
  }

  // ── report ───────────────────────────────────────────────────────────────────
  for (const w of warnings) console.warn(`  ⚠ ${w}`);
  if (problems.length > 0) {
    console.error(`\n✗ ${String(problems.length)} validation problem(s):\n`);
    for (const p of problems) console.error(`    ${p}`);
    console.error('');
    process.exit(1);
  }
  console.log(
    `✓ grace.json, ${String(TOOL_REGISTRY.length)} generated tools, ${String(HAND_AUTHORED_TOOLS.length)} hand-authored tool(s) and 1 structured output validated`,
  );
}

await main();
