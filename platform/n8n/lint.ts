/**
 * Structural lint for committed workflow JSON (doc 09 §8). Runs on every PR — it catches
 * the failure modes that are otherwise only discovered by a caller hearing silence, or by
 * a workflow that deploys green and throws on its first execution.
 *
 *   pnpm platform:n8n:lint
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const DIR = join(import.meta.dirname, 'workflows');

/** WF-00 is the global error handler; it cannot point its errorWorkflow at itself. */
const ERROR_HANDLER = 'WF-00';

interface Node {
  name: string;
  type: string;
  parameters?: Record<string, unknown>;
  credentials?: Record<string, { id?: string; name?: string }>;
  [k: string]: unknown;
}
interface Workflow {
  name: string;
  nodes: Node[];
  connections: Record<string, { main?: Array<Array<{ node: string }>> }>;
  settings?: Record<string, unknown>;
  [k: string]: unknown;
}

/** Node parameters are `unknown`; coerce only real primitives, never [object Object]. */
function str(v: unknown, fallback = ''): string {
  return typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'
    ? String(v)
    : fallback;
}

const problems: string[] = [];
function bad(file: string, rule: number, msg: string): void {
  problems.push(`${file}  [rule ${String(rule)}]  ${msg}`);
}

const SECRET_PATTERNS = [
  /\bsk_[A-Za-z0-9]{10,}/,
  /\bwhsec_[A-Za-z0-9]{10,}/,
  /\bxoxb-[A-Za-z0-9-]{10,}/,
  /\bAC[0-9a-f]{32}\b/,
  /\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}/,
  /Bearer\s+[A-Za-z0-9._-]{20,}/,
];

const WEBHOOK_TYPES = new Set([
  'n8n-nodes-base.webhook',
  'n8n-nodes-base.slackTrigger',
]);

function isWait(n: Node): boolean {
  return n.type === 'n8n-nodes-base.wait';
}
function isRespond(n: Node): boolean {
  return n.type === 'n8n-nodes-base.respondToWebhook';
}

/** Every path out of a webhook trigger must terminate in a Respond-to-Webhook node. */
function everyPathResponds(wf: Workflow, start: string): boolean {
  const seen = new Set<string>();
  const byName = new Map(wf.nodes.map((n) => [n.name, n]));

  const walk = (name: string): boolean => {
    if (seen.has(name)) return true; // a cycle cannot introduce a dead end
    seen.add(name);
    const node = byName.get(name);
    if (!node) return false;
    if (isRespond(node)) return true;

    const branches = wf.connections[name]?.main ?? [];
    const next = branches.flat().map((c) => c.node);
    if (next.length === 0) return false; // terminal, and not a respond node
    return next.every(walk);
  };

  return walk(start);
}

function lintFile(file: string): void {
  const raw = readFileSync(join(DIR, file), 'utf8');
  const wf = JSON.parse(raw) as Workflow;
  const isErrorHandler = file.startsWith(ERROR_HANDLER);

  // 3. no hardcoded secrets
  for (const re of SECRET_PATTERNS) {
    if (re.test(raw)) bad(file, 3, `contains something matching ${String(re)}`);
  }
  // 4. no localhost / tunnel URLs
  if (/localhost|127\.0\.0\.1|ngrok|trycloudflare/.test(raw)) {
    bad(file, 4, 'references localhost or a dev tunnel URL');
  }
  // 7. filename ↔ name, and no env prefix committed
  const expected = file.replace(/\.json$/, '');
  if (!expected.startsWith(wf.name.split(' ')[0] ?? '')) {
    bad(file, 7, `workflow name "${wf.name}" does not match filename`);
  }
  if (/^\[(dev|prod)\]/.test(wf.name)) {
    bad(file, 7, 'committed name carries an env prefix; it is applied at deploy time');
  }
  // 8. no pinData
  if ('pinData' in wf) bad(file, 8, 'contains pinData');

  // 6. errorWorkflow set, except on the handler itself
  const settings = wf.settings ?? {};
  if (!isErrorHandler && typeof settings['errorWorkflow'] !== 'string') {
    bad(file, 6, 'settings.errorWorkflow is not set');
  }
  // 11. errorWorkflow must be a placeholder, never a raw id
  const ew = settings['errorWorkflow'];
  if (typeof ew === 'string' && !ew.startsWith('__WF__:')) {
    bad(file, 11, `settings.errorWorkflow "${ew}" must be a __WF__:<alias> placeholder`);
  }
  // 12. executionTimeout kills waiting executions (n8n#15123)
  const hasWait = wf.nodes.some(isWait);
  if (hasWait && 'executionTimeout' in settings) {
    bad(file, 12, 'has a Wait node and settings.executionTimeout, which would kill it mid-wait');
  }

  for (const node of wf.nodes) {
    // 10. credentials must be resolvable placeholders, never raw ids
    for (const [type, cred] of Object.entries(node.credentials ?? {})) {
      if (!cred.id || !/^__CRED__:[a-z0-9-]+$/.test(cred.id)) {
        bad(
          file,
          10,
          `node "${node.name}" credential ${type}.id must be __CRED__:<alias>, got ${String(cred.id)} ` +
            `(n8n resolves credentials strictly by id — a name here deploys green and throws at runtime)`,
        );
      }
    }
    // 5. HTTP nodes need a timeout
    if (node.type === 'n8n-nodes-base.httpRequest') {
      const opts = (node.parameters?.['options'] ?? {}) as Record<string, unknown>;
      if (typeof opts['timeout'] !== 'number') {
        bad(file, 5, `HTTP node "${node.name}" has no timeout`);
      }
    }
    // 13. sub-65s waits are not durable across a restart
    if (isWait(node)) {
      const p = node.parameters ?? {};
      const unit = str(p['unit'], 'seconds');
      const amount = Number(p['amount'] ?? 0);
      const seconds = unit === 'minutes' ? amount * 60 : unit === 'hours' ? amount * 3600 : amount;
      if (seconds > 0 && seconds < 65) {
        bad(file, 13, `Wait node "${node.name}" is ${String(seconds)}s; under 65s it is lost on restart`);
      }
    }
    // 15. crons must pin the timezone
    if (node.type === 'n8n-nodes-base.scheduleTrigger') {
      const tz = str(node.parameters?.['timezone']);
      if (tz !== 'America/Chicago') {
        bad(file, 15, `schedule node "${node.name}" must set timezone America/Chicago, got "${tz}"`);
      }
    }
    // 1 + 9 + 14. webhook triggers
    if (WEBHOOK_TYPES.has(node.type)) {
      const p = node.parameters ?? {};
      if (node.type === 'n8n-nodes-base.webhook') {
        if (str(p['httpMethod']) !== 'POST') {
          bad(file, 1, `webhook "${node.name}" must be POST`);
        }
        if (str(p['responseMode']) !== 'responseNode') {
          bad(file, 1, `webhook "${node.name}" must use responseMode "responseNode"`);
        }
        const path = str(p['path']);
        if (!path.startsWith('{{ENV}}/')) {
          bad(file, 9, `webhook "${node.name}" path must start with {{ENV}}/, got "${path}"`);
        }
        // 14. signature verification requires the exact bytes
        const opts = (p['options'] ?? {}) as Record<string, unknown>;
        if (opts['rawBody'] !== true) {
          bad(file, 14, `webhook "${node.name}" must enable Raw Body (signatures cover exact bytes)`);
        }
        // 2. every path must terminate in a respond node
        if (!everyPathResponds(wf, node.name)) {
          bad(file, 2, `not every path from "${node.name}" reaches a Respond to Webhook node`);
        }
      }
    }
  }
}

function main(): void {
  const files = readdirSync(DIR).filter((f) => f.endsWith('.json'));
  if (files.length === 0) {
    console.log('  (no workflows yet)');
    return;
  }
  for (const f of files) lintFile(f);

  if (problems.length > 0) {
    console.error(`\n✗ ${String(problems.length)} lint problem(s):\n`);
    for (const p of problems) console.error(`    ${p}`);
    console.error('');
    process.exit(1);
  }
  console.log(`✓ ${String(files.length)} workflow(s) pass all 15 lint rules`);
}

main();
