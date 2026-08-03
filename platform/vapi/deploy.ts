/**
 * Vapi config-as-code deploy (doc 08 §8).
 *
 *   pnpm platform:vapi:deploy --env dev --diff     show drift, change nothing (default)
 *   pnpm platform:vapi:deploy --env dev --apply    upsert tools, outputs, assistant
 *
 * Order matters: tools and structured outputs must exist before the assistant can
 * reference their ids.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { HAND_AUTHORED_TOOLS, TOOL_REGISTRY } from '@grace/contracts';

import { computeDrift, type Json } from './lib/drift.js';
import { toolIdentity, VapiClient, type VapiEntity } from './lib/vapi-client.js';

const HERE = import.meta.dirname;
const LOCK_PATH = join(HERE, '.lock.json');

interface Lock {
  env: string;
  assistantId: string;
  toolIds: Record<string, string>;
  structuredOutputIds: Record<string, string>;
  lastAppliedSha: string;
  lastAppliedAt: string;
}

// ── argument parsing ───────────────────────────────────────────────────────────

const argv = process.argv.slice(2);
const apply = argv.includes('--apply');
const env = (argv[argv.indexOf('--env') + 1] ?? 'dev') as 'dev' | 'prod';
if (!['dev', 'prod'].includes(env)) {
  console.error(`✗ --env must be dev or prod, got "${env}"`);
  process.exit(1);
}

// ── environment substitution ───────────────────────────────────────────────────

/** Replaces `${VAR}` placeholders. Missing required vars fail loudly, never silently. */
function substitute(input: string, required: string[]): string {
  const missing: string[] = [];
  const out = input.replace(/\$\{([A-Z0-9_]+)\}/g, (_m, name: string) => {
    const v = process.env[name];
    if (v === undefined || v === '') {
      if (required.includes(name)) missing.push(name);
      return '';
    }
    return v;
  });
  if (missing.length > 0) {
    console.error(`✗ missing required environment variable(s): ${missing.join(', ')}`);
    process.exit(1);
  }
  return out;
}

/** Drops keys whose value became empty after substitution (e.g. an unset credentialId). */
function pruneEmpty(value: Json): Json {
  if (Array.isArray(value)) return value.map(pruneEmpty);
  if (value && typeof value === 'object') {
    const out: Record<string, Json> = {};
    for (const [k, v] of Object.entries(value)) {
      if (v === '' || v === null) continue;
      out[k] = pruneEmpty(v);
    }
    return out;
  }
  return value;
}

function loadJson(path: string, required: string[] = []): Json {
  return pruneEmpty(JSON.parse(substitute(readFileSync(path, 'utf8'), required)) as Json);
}

// ── guard rails (doc 08 §8.1) ──────────────────────────────────────────────────

function gitClean(): boolean {
  try {
    return execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim() === '';
  } catch {
    return true; // not a git repo — do not block
  }
}

function gitSha(): string {
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  } catch {
    return 'unknown';
  }
}

function assertGuardRails(): void {
  if (!apply) return;

  if (env === 'prod' && !gitClean()) {
    console.error('✗ refusing to --apply to prod with a dirty git tree (AC-08.8)');
    process.exit(1);
  }

  const assistantRaw = readFileSync(join(HERE, 'assistants', 'grace.json'), 'utf8');
  if (!assistantRaw.includes('injected from prompts/first-message.txt')) {
    console.error('✗ I7: grace.json must inject firstMessage, never inline it');
    process.exit(1);
  }
  const greeting = readFileSync(join(HERE, 'prompts', 'first-message.txt'), 'utf8');
  if (!/may be recorded/i.test(greeting) || !/virtual assistant|AI assistant/i.test(greeting)) {
    console.error('✗ I7: first-message.txt is missing the recording or AI disclosure');
    process.exit(1);
  }
}

// ── build the desired assistant body ───────────────────────────────────────────

function buildAssistantBody(toolIds: string[], structuredOutputIds: string[]): Json {
  const assistant = loadJson(join(HERE, 'assistants', 'grace.json'), ['GRACE_EVENTS_URL']) as Record<
    string,
    Json
  >;

  assistant['firstMessage'] = readFileSync(join(HERE, 'prompts', 'first-message.txt'), 'utf8').trim();

  const model = assistant['model'] as Record<string, Json>;
  model['messages'] = [
    { role: 'system', content: readFileSync(join(HERE, 'prompts', 'system.md'), 'utf8').trim() },
  ];
  model['toolIds'] = [...toolIds].sort();

  const artifact = assistant['artifactPlan'] as Record<string, Json>;
  artifact['structuredOutputIds'] = [...structuredOutputIds].sort();

  // Dev talks to a tunnel; prod to the real host. Both come from env, never committed.
  if (env === 'dev') assistant['name'] = 'Grace — PalmLeaf [dev]';

  return assistant;
}

function localTools(): Map<string, Json> {
  const dir = join(HERE, 'tools');
  const wanted = new Set<string>([
    ...TOOL_REGISTRY.map((t) => `${t.name}.json`),
    ...HAND_AUTHORED_TOOLS.map((n) => `${n}.json`),
  ]);
  const out = new Map<string, Json>();
  for (const file of readdirSync(dir).filter((f) => wanted.has(f))) {
    const tool = loadJson(join(dir, file), file === 'transferToHuman.json' || file === 'endCall.json' ? [] : ['GRACE_TOOLS_URL']);
    out.set(toolIdentity(tool as Record<string, unknown>), tool);
  }
  return out;
}

function localStructuredOutputs(): Map<string, Json> {
  const dir = join(HERE, 'structured-outputs');
  const out = new Map<string, Json>();
  if (!existsSync(dir)) return out;
  for (const file of readdirSync(dir).filter((f) => f.endsWith('.json'))) {
    const so = loadJson(join(dir, file)) as Record<string, Json>;
    out.set(String(so['name']), so);
  }
  return out;
}

// ── main ───────────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  assertGuardRails();

  const client = new VapiClient(process.env['VAPI_API_KEY'] ?? '');
  const mode = apply ? 'APPLY' : 'DIFF';
  console.log(`\nVapi deploy — env=${env} mode=${mode}\n`);

  // 1. tools ────────────────────────────────────────────────────────────────────
  const remoteTools = await client.listTools();
  const remoteByName = new Map(remoteTools.map((t) => [toolIdentity(t), t]));
  const toolIds: Record<string, string> = {};
  let changes = 0;

  for (const [name, local] of localTools()) {
    const remote = remoteByName.get(name);
    if (!remote) {
      if (apply) {
        const created = await client.createTool(local);
        toolIds[name] = created.id;
        console.log(`  + tool ${name} → ${created.id}`);
      } else {
        console.log(`  + tool ${name} (would create)`);
      }
      changes++;
      continue;
    }

    toolIds[name] = remote.id;
    const drift = computeDrift(remote as unknown as Json, local);
    if (drift.length === 0) {
      console.log(`  = tool ${name}`);
      continue;
    }
    changes++;
    console.log(`  ~ tool ${name}`);
    for (const d of drift) {
      console.log(`      ${d.forbidden ? '⛔' : '·'} ${d.path}`);
    }
    if (apply) await client.updateTool(remote.id, local);
  }

  // 2. structured outputs ───────────────────────────────────────────────────────
  const soRaw = await client.listStructuredOutputs();
  const soList = Array.isArray(soRaw) ? soRaw : (soRaw.results ?? []);
  const soByName = new Map(soList.map((s: VapiEntity) => [String(s['name']), s]));
  const structuredOutputIds: Record<string, string> = {};

  for (const [name, local] of localStructuredOutputs()) {
    const remote = soByName.get(name);
    if (!remote) {
      if (apply) {
        const created = await client.createStructuredOutput(local);
        structuredOutputIds[name] = created.id;
        console.log(`  + structured-output ${name} → ${created.id}`);
      } else {
        console.log(`  + structured-output ${name} (would create)`);
      }
      changes++;
      continue;
    }
    structuredOutputIds[name] = remote.id;
    const drift = computeDrift(remote as unknown as Json, local);
    if (drift.length > 0) {
      changes++;
      console.log(`  ~ structured-output ${name}`);
      if (apply) await client.updateStructuredOutput(remote.id, local);
    } else {
      console.log(`  = structured-output ${name}`);
    }
  }

  // 3. assistant ────────────────────────────────────────────────────────────────
  const desired = buildAssistantBody(Object.values(toolIds), Object.values(structuredOutputIds));
  const wantedName = (desired as Record<string, Json>)['name'] as string;
  const remoteAssistants = await client.listAssistants();
  const remoteAssistant = remoteAssistants.find((a) => a.name === wantedName);

  let assistantId = remoteAssistant?.id ?? '';
  let forbiddenDrift = 0;

  if (!remoteAssistant) {
    if (apply) {
      const created = await client.createAssistant(desired);
      assistantId = created.id;
      console.log(`  + assistant "${wantedName}" → ${created.id}`);
    } else {
      console.log(`  + assistant "${wantedName}" (would create)`);
    }
    changes++;
  } else {
    const full = await client.getAssistant(remoteAssistant.id);
    const drift = computeDrift(full as unknown as Json, desired);
    if (drift.length === 0) {
      console.log(`  = assistant "${wantedName}"`);
    } else {
      changes++;
      console.log(`  ~ assistant "${wantedName}"`);
      for (const d of drift) {
        if (d.forbidden) forbiddenDrift++;
        const from = JSON.stringify(d.remote)?.slice(0, 70) ?? 'undefined';
        const to = JSON.stringify(d.desired)?.slice(0, 70) ?? 'undefined';
        console.log(`      ${d.forbidden ? '⛔' : '·'} ${d.path}\n          remote:  ${from}\n          desired: ${to}`);
      }
      if (apply) await client.updateAssistant(remoteAssistant.id, desired);
    }
  }

  // 4. lock file ────────────────────────────────────────────────────────────────
  if (apply && assistantId) {
    const lock: Lock = {
      env,
      assistantId,
      toolIds,
      structuredOutputIds,
      lastAppliedSha: gitSha(),
      lastAppliedAt: new Date().toISOString(),
    };
    writeFileSync(LOCK_PATH, `${JSON.stringify(lock, null, 2)}\n`, 'utf8');
    console.log(`\n  wrote .lock.json (assistant ${assistantId})`);
  }

  // 5. verdict ──────────────────────────────────────────────────────────────────
  console.log('');
  if (apply) {
    console.log(`✓ applied — ${String(changes)} change(s)\n`);
    return;
  }
  if (changes === 0) {
    console.log('✓ no drift\n');
    return;
  }
  if (forbiddenDrift > 0) {
    console.error(`✗ ${String(forbiddenDrift)} FORBIDDEN drift path(s) — a compliance-bearing field differs\n`);
    process.exit(1);
  }
  console.log(`⚠ ${String(changes)} pending change(s). Re-run with --apply.\n`);
  // Drift in CI is a failure; locally it is informational.
  if (process.env['CI']) process.exit(1);
}

await main();
