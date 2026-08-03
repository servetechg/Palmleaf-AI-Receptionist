/**
 * n8n config-as-code deploy against a single Cloud instance (doc 09 §6.3, ADR-0013).
 *
 *   pnpm platform:n8n:deploy --env dev  --diff     default; changes nothing
 *   pnpm platform:n8n:deploy --env dev  --apply
 *   pnpm platform:n8n:deploy --env prod --apply    CI only
 *
 * Dev and prod share the instance and are separated by tag + name prefix + webhook path
 * prefix + per-environment credentials. Anything not tagged `managed:git` is invisible to
 * this script — including the workflows that were already on the instance.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { N8nClient, type N8nWorkflow } from './lib/n8n-client.js';

const DIR = join(import.meta.dirname, 'workflows');

const argv = process.argv.slice(2);
const apply = argv.includes('--apply');
const env = (argv[argv.indexOf('--env') + 1] ?? 'dev') as 'dev' | 'prod';
if (!['dev', 'prod'].includes(env)) {
  console.error(`✗ --env must be dev or prod, got "${env}"`);
  process.exit(1);
}

/** Alias → credential name, per environment. Mirrors credentials.example.json. */
const CREDENTIAL_NAMES: Record<string, Record<string, string>> = {
  // Only one. n8n holds no third-party credentials — every notification goes through
  // Core API's /internal/notify/*, so 10DLC and opt-out enforcement cannot be bypassed
  // (doc 09 §3.4). Slack is not in scope; if adopted it becomes a Core API channel.
  'core-api': { dev: 'PalmLeaf Core API (dev)', prod: 'PalmLeaf Core API (prod)' },
};

/** Alias → the committed filename prefix of the workflow it refers to. */
const WORKFLOW_ALIASES: Record<string, string> = {
  'wf-00': 'WF-00',
  'wf-12': 'WF-12',
  'wf-18': 'WF-18',
};

const envName = (name: string): string => `[${env}] ${name}`;

interface Local {
  file: string;
  alias: string;
  wf: N8nWorkflow;
}

function loadLocal(): Local[] {
  return readdirSync(DIR)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((file) => ({
      file,
      alias: (file.split('-').slice(0, 2).join('-') || file).toLowerCase(),
      wf: JSON.parse(readFileSync(join(DIR, file), 'utf8')) as N8nWorkflow,
    }));
}

/**
 * Resolves `__CRED__:` and `__WF__:` placeholders and applies the environment prefix.
 *
 * An unresolved placeholder is a HARD FAILURE. n8n will not complain — it accepts the
 * workflow, activates it, and then throws `CredentialNotFoundError` on the first
 * execution, which is the worst possible time to find out (doc 09 §6.2).
 */
/** Aliases this workflow references via __WF__:, i.e. what must be published first. */
function dependenciesOf(local: Local): string[] {
  const refs = JSON.stringify(local.wf).match(/__WF__:([a-z0-9-]+)/g) ?? [];
  return [...new Set(refs.map((r) => r.slice('__WF__:'.length)))];
}

function render(
  local: Local,
  credIds: Map<string, string>,
  workflowIds: Map<string, string>,
): { name: string; nodes: unknown[]; connections: unknown; settings: unknown } {
  const unresolved: string[] = [];

  const walk = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === 'object') {
      return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, walk(x)]));
    }
    if (typeof v !== 'string') return v;

    if (v.startsWith('__CRED__:')) {
      const alias = v.slice('__CRED__:'.length);
      const name = CREDENTIAL_NAMES[alias]?.[env];
      const id = name ? credIds.get(name) : undefined;
      if (!id) {
        unresolved.push(`credential "${alias}" → ${name ?? '(no mapping)'}`);
        return v;
      }
      return id;
    }
    if (v.startsWith('__WF__:')) {
      const alias = v.slice('__WF__:'.length);
      const prefix = WORKFLOW_ALIASES[alias];
      const id = prefix ? workflowIds.get(prefix) : undefined;
      if (!id) {
        unresolved.push(`workflow "${alias}" → ${prefix ?? '(no mapping)'}`);
        return v;
      }
      return id;
    }
    // Webhook paths carry the environment so dev and prod cannot collide.
    return v.replace('{{ENV}}/', `${env}/`);
  };

  const nodes = walk(local.wf.nodes) as unknown[];
  const settings = walk(local.wf.settings ?? {});

  if (unresolved.length > 0) {
    console.error(`\n✗ ${local.file}: unresolved placeholder(s):`);
    for (const u of unresolved) console.error(`    ${u}`);
    console.error(
      `\n  n8n would accept this workflow and then throw on its first execution.\n` +
        `  Create the credential in the n8n UI (see credentials.example.json) and retry.\n`,
    );
    process.exit(1);
  }

  // PUT body must be EXACTLY these four keys — the schema is additionalProperties:false.
  return { name: envName(local.wf.name), nodes, connections: local.wf.connections, settings };
}

async function main(): Promise<void> {
  const client = new N8nClient(process.env['N8N_API_URL'] ?? '', process.env['N8N_API_KEY'] ?? '');
  console.log(`\nn8n deploy — env=${env} mode=${apply ? 'APPLY' : 'DIFF'}\n`);

  const managedTags = ['managed:git', `env:${env}`];

  // Tags must exist before anything can be filtered by them.
  const remoteTags = await client.listTags();
  const tagIds = new Map(remoteTags.map((t) => [t.name, t.id]));
  for (const name of managedTags) {
    if (tagIds.has(name)) continue;
    if (apply) {
      const created = await client.createTag(name);
      tagIds.set(name, created.id);
      console.log(`  + tag ${name}`);
    } else {
      console.log(`  + tag ${name} (would create)`);
    }
  }

  const creds = await client.listCredentials();
  const credIds = new Map(creds.map((c) => [c.name, c.id]));

  const managed = await client.listWorkflows(managedTags);
  const byName = new Map(managed.map((w) => [w.name, w]));
  const workflowIds = new Map<string, string>();
  for (const w of managed) {
    const m = /^\[(?:dev|prod)\]\s+(WF-\d+)/.exec(w.name);
    if (m?.[1] && w.id) workflowIds.set(m[1], w.id);
  }

  const local = loadLocal();
  let changes = 0;

  // n8n refuses to publish a workflow whose sub-workflows are not yet published, so
  // activation has to happen in dependency order — observed 2026-08-03:
  //   'Cannot publish workflow: Node X references workflow Y which is not published.'
  const pendingActivation: Array<{ id: string; label: string; deps: string[] }> = [];

  // Two passes: create everything first so __WF__ cross-references can resolve.
  if (apply) {
    for (const l of local) {
      const target = envName(l.wf.name);
      if (byName.has(target)) continue;
      const placeholder = { name: target, nodes: [], connections: {}, settings: {} };
      const created = await client.createWorkflow(placeholder);
      if (created.id) {
        // Tag IMMEDIATELY. If a later step fails, the partially-created workflow is still
        // inside the managed set — so the next run finds and finishes it instead of
        // creating a second copy and leaving an untagged orphan behind.
        await client.setTags(
          created.id,
          managedTags.map((t) => tagIds.get(t)).filter((x): x is string => Boolean(x)),
        );
        byName.set(target, created);
        const m = /^(WF-\d+)/.exec(l.wf.name);
        if (m?.[1]) workflowIds.set(m[1], created.id);
        console.log(`  + workflow ${target} → ${created.id}`);
        changes++;
      }
    }
  }

  for (const l of local) {
    const target = envName(l.wf.name);
    const remote = byName.get(target);
    const body = render(l, credIds, workflowIds);

    if (!remote?.id) {
      console.log(`  + workflow ${target} (would create)`);
      changes++;
      continue;
    }

    const same =
      JSON.stringify(remote.nodes) === JSON.stringify(body.nodes) &&
      JSON.stringify(remote.connections) === JSON.stringify(body.connections);

    if (same) {
      console.log(`  = workflow ${target}`);
      continue;
    }
    changes++;
    console.log(`  ~ workflow ${target}`);
    if (!apply) continue;

    await client.updateWorkflow(remote.id, body);
    await client.setTags(
      remote.id,
      managedTags.map((t) => tagIds.get(t)).filter((x): x is string => Boolean(x)),
    );
    pendingActivation.push({ id: remote.id, label: target, deps: dependenciesOf(l) });
    console.log(`      updated and tagged`);
  }

  // Activate in dependency order: a referenced sub-workflow must be published first.
  if (apply && pendingActivation.length > 0) {
    const aliasOf = (label: string): string => (/(WF-\d+)/.exec(label)?.[1] ?? '').toLowerCase();
    const done = new Set<string>();
    let queue = [...pendingActivation];

    // Bound on the ORIGINAL length: `queue` shrinks each pass, so comparing against it
    // exits one pass early and silently leaves the last workflow unactivated.
    const maxPasses = queue.length + 1;
    for (let pass = 0; pass < maxPasses && queue.length > 0; pass++) {
      const ready = queue.filter((w) => w.deps.every((d) => done.has(d) || d === aliasOf(w.label)));
      // Nothing became ready: a cycle, or a dependency outside this deploy. Try anyway
      // so the error surfaces from n8n rather than as a silent no-op.
      const batch = ready.length > 0 ? ready : queue;

      for (const w of batch) {
        const route = await client.activate(w.id);
        console.log(`  ▶ activated ${w.label} via /${route}`);
        done.add(aliasOf(w.label));
      }
      queue = queue.filter((w) => !batch.includes(w));
    }
  }

  // A managed workflow with no local file is an orphan — fail rather than silently leave it.
  const localNames = new Set(local.map((l) => envName(l.wf.name)));
  for (const w of managed) {
    if (!localNames.has(w.name)) {
      console.error(`\n✗ orphan: "${w.name}" is tagged managed:git,env:${env} but has no local file`);
      process.exit(1);
    }
  }

  console.log('');
  if (apply) {
    console.log(`✓ applied — ${String(changes)} change(s)\n`);
  } else if (changes === 0) {
    console.log('✓ no drift\n');
  } else {
    console.log(`⚠ ${String(changes)} pending change(s). Re-run with --apply.\n`);
    if (process.env['CI']) process.exit(1);
  }
}

await main();
