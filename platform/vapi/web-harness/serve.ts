/**
 * Serves the web harness over http (the Vapi web SDK needs a real origin, not file://)
 * and generates harness-config.js from .lock.json + VAPI_PUBLIC_KEY, so the assistant id
 * is never hand-copied and never committed.
 *
 *   pnpm platform:vapi:harness
 */
import { createServer } from 'node:http';
import { existsSync, readFileSync } from 'node:fs';
import { extname, join } from 'node:path';

const HERE = import.meta.dirname;
const PORT = Number(process.env['GRACE_HARNESS_PORT'] ?? 4243);

const lockPath = join(HERE, '..', '.lock.json');
if (!existsSync(lockPath)) {
  console.error('✗ platform/vapi/.lock.json not found — run: pnpm platform:vapi:deploy --env dev --apply');
  process.exit(1);
}
const lock = JSON.parse(readFileSync(lockPath, 'utf8')) as { assistantId: string; env: string };
const publicKey = process.env['VAPI_PUBLIC_KEY'] ?? '';

if (!publicKey) {
  console.error('✗ VAPI_PUBLIC_KEY is not set. It is the PUBLIC key (browser-safe), not the private one.');
  process.exit(1);
}
if (lock.env !== 'dev') {
  console.error(`✗ .lock.json targets "${lock.env}". The harness only ever points at dev.`);
  process.exit(1);
}

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
};

createServer((req, res) => {
  const url = (req.url ?? '/').split('?')[0] ?? '/';

  if (url === '/harness-config.js') {
    const body = `export const PUBLIC_KEY = ${JSON.stringify(publicKey)};\nexport const ASSISTANT_ID = ${JSON.stringify(lock.assistantId)};\n`;
    res.writeHead(200, { 'Content-Type': MIME['.js'] ?? 'text/javascript' });
    res.end(body);
    return;
  }

  const file = join(HERE, url === '/' ? 'index.html' : url.replace(/^\/+/, ''));
  if (!file.startsWith(HERE) || !existsSync(file)) {
    res.writeHead(404).end('not found');
    return;
  }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] ?? 'application/octet-stream' });
  res.end(readFileSync(file));
}).listen(PORT, () => {
  console.log(`\n  Grace web harness  →  http://localhost:${String(PORT)}`);
  console.log(`    assistant  ${lock.assistantId} (${lock.env})`);
  console.log(`\n  Make sure the mock server and your tunnel are running, and that the`);
  console.log(`  assistant was deployed with the tunnel URL.\n`);
});
