/**
 * Dev-only stand-in for Core API (doc 08 §10).
 *
 * Exposes the SAME two routes with the SAME envelope as Core API will, so switching over
 * later is one environment variable. Its real job is not to return plausible strings — it
 * is to **validate every tool call against the real zod schemas from `@grace/contracts`**,
 * which is what proves the JSON Schema we published to Vapi and the schema our handlers
 * expect actually agree, under a live model, months before Core API exists.
 *
 *   pnpm platform:vapi:mock
 *
 * Fault injection, for exercising the deadline fallbacks:
 *   GRACE_MOCK_LATENCY_MS=1200   add latency to every tool
 *   GRACE_MOCK_FAIL=checkAvailability     that tool returns a graceful failure sentence
 *   GRACE_MOCK_TIMEOUT=createBooking      that tool never responds
 *   GRACE_MOCK_NOW=2026-08-04T14:00:00Z   freeze the clock
 *
 * Non-goals: no DB, no Vagaro, no real SMS, no tenant resolution. Never deployed anywhere
 * but a dev tunnel.
 */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';

import {
  getToolSpec,
  parseToolArguments,
  TransferDestinationResponse,
  VapiEventPayload,
  VapiToolCallsPayload,
} from '@grace/contracts';

import { FIXTURES } from './fixtures.js';

const PORT = Number(process.env['GRACE_MOCK_PORT'] ?? 4242);
const LATENCY = Number(process.env['GRACE_MOCK_LATENCY_MS'] ?? 0);
const FAIL_TOOL = process.env['GRACE_MOCK_FAIL'] ?? '';
const TIMEOUT_TOOL = process.env['GRACE_MOCK_TIMEOUT'] ?? '';

/** Proves the `${callId}:${toolCallId}` key shape and the replay-the-stored-response path (I3). */
const idempotency = new Map<string, string>();

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

function log(kind: string, msg: string): void {
  const stamp = new Date().toISOString().slice(11, 23);
  console.log(`${stamp}  ${kind.padEnd(9)} ${msg}`);
}

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

function send(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) });
  res.end(payload);
}

// ── POST /vapi/tools ───────────────────────────────────────────────────────────

async function handleToolCalls(raw: string, res: ServerResponse): Promise<void> {
  const parsed = VapiToolCallsPayload.safeParse(JSON.parse(raw));
  if (!parsed.success) {
    log('ENVELOPE', `✗ ${parsed.error.issues.map((i) => i.path.join('.')).join(', ')}`);
    // Still 200 with a spoken sentence: a 500 gives the model nothing to say.
    send(res, 200, { results: [{ toolCallId: 'unknown', result: "Sorry, could you say that once more?" }] });
    return;
  }

  const msg = parsed.data.message;
  const callId = msg.call?.id ?? parsed.data.call?.id ?? 'unknown-call';
  const results: Array<{ toolCallId: string; name: string; result: string }> = [];

  for (const call of msg.toolCalls) {
    const name = call.function.name;
    const spec = getToolSpec(name);

    if (!spec) {
      log('TOOL', `✗ unknown tool "${name}"`);
      results.push({ toolCallId: call.id, name, result: "I'm not able to do that — let me get someone who can." });
      continue;
    }

    if (TIMEOUT_TOOL === name) {
      log('FAULT', `${name} — simulating a hang (no response)`);
      await sleep(60_000);
      continue;
    }

    const key = `${callId}:${call.id}`;
    const cached = idempotency.get(key);
    if (cached !== undefined) {
      log('IDEMPOT', `${name} replayed for ${key}`);
      results.push({ toolCallId: call.id, name, result: cached });
      continue;
    }

    // THE point of this server: validate with the real schema, not a loose parse.
    const args = parseToolArguments(call.function.arguments);
    const check = spec.input.safeParse(args);
    if (!check.success) {
      const detail = check.error.issues
        .map((i) => `${i.path.join('.') || '(root)'}: ${i.message}`)
        .join('; ');
      log('SCHEMA', `✗ ${name} — ${detail}`);
      console.error(`           args: ${JSON.stringify(args)}`);
      results.push({
        toolCallId: call.id,
        name,
        result: "Sorry, I didn't catch that properly — could you say it again?",
      });
      continue;
    }

    if (FAIL_TOOL === name) {
      log('FAULT', `${name} — simulating failure`);
      results.push({
        toolCallId: call.id,
        name,
        result: "I'm having trouble with that right now. Let me get someone who can help.",
      });
      continue;
    }

    if (LATENCY > 0) await sleep(LATENCY);

    const fn = FIXTURES[name as keyof typeof FIXTURES] as
      | ((a: unknown, c: string) => string)
      | undefined;
    const result = fn ? fn(check.data, callId) : 'ok';

    if (spec.write) idempotency.set(key, result);
    log('TOOL', `✓ ${name} → ${result.slice(0, 80)}`);
    results.push({ toolCallId: call.id, name, result });
  }

  send(res, 200, { results });
}

// ── POST /webhooks/vapi/events ─────────────────────────────────────────────────

/** Whisper text primed by flagEscalation, keyed by call id (doc 08 §7.1). 60s TTL. */
const whispers = new Map<string, { text: string; at: number }>();

function handleEvent(raw: string, res: ServerResponse): void {
  const parsed = VapiEventPayload.safeParse(JSON.parse(raw));
  if (!parsed.success) {
    log('EVENT', '✗ unrecognised event payload');
    send(res, 200, { ok: true });
    return;
  }

  const { type, call } = parsed.data.message;
  const callId = call?.id ?? 'unknown';

  switch (type) {
    case 'transfer-destination-request': {
      const primed = whispers.get(callId);
      const fresh = primed && Date.now() - primed.at < 60_000;
      if (!fresh) {
        // The prompt requires flagEscalation first. If it did not happen, that is a
        // prompt-adherence failure worth seeing, not something to paper over.
        log('WHISPER', `⚠ no primed whisper for ${callId} — model skipped flagEscalation`);
      }
      const destination = TransferDestinationResponse.parse({
        destination: {
          type: 'number',
          number: process.env['GRACE_FRONT_DESK_NUMBER'] ?? '+18475550123',
          callerId: '{{customer.number}}',
          message: 'One moment — connecting you to the front desk.',
          transferPlan: {
            mode: 'warm-transfer-experimental',
            message: fresh ? primed.text : 'Transferring a caller — no context was captured.',
            sipVerb: 'dial',
            dialTimeout: 25,
            fallbackPlan: {
              message:
                "I'm sorry — nobody's picking up right now. Let me take a message and have someone call you back.",
              endCallEnabled: false,
            },
          },
        },
      });
      log('EVENT', `transfer-destination-request → front desk (whisper: ${fresh ? 'primed' : 'MISSING'})`);
      send(res, 200, destination);
      return;
    }

    case 'end-of-call-report': {
      const analysis = parsed.data.message.analysis;
      log('EVENT', `end-of-call-report for ${callId}`);
      if (analysis?.structuredData) {
        log('ANALYSIS', JSON.stringify(analysis.structuredData));
      } else {
        log('ANALYSIS', '⚠ no structuredData — check artifactPlan.structuredOutputIds');
      }
      send(res, 200, { ok: true });
      return;
    }

    default:
      log('EVENT', `${type} for ${callId}`);
      send(res, 200, { ok: true });
  }
}

/** flagEscalation is async, so we capture the whisper here on the tool route. */
export const primeWhisper = (callId: string, text: string): void => {
  whispers.set(callId, { text, at: Date.now() });
};

// ── server ─────────────────────────────────────────────────────────────────────

const server = createServer((req, res) => {
  void (async () => {
    const url = req.url ?? '';
    if (req.method === 'GET' && url === '/healthz') {
      send(res, 200, { ok: true });
      return;
    }
    if (req.method !== 'POST') {
      send(res, 405, { error: 'method not allowed' });
      return;
    }

    const raw = await readBody(req);
    try {
      if (url.startsWith('/vapi/tools')) {
        // Capture escalation context before dispatch so the events route can use it.
        try {
          const peek = JSON.parse(raw) as { message?: { toolCalls?: unknown[]; call?: { id?: string } } };
          const callId = peek.message?.call?.id ?? 'unknown-call';
          for (const tc of peek.message?.toolCalls ?? []) {
            const t = tc as { function?: { name?: string; arguments?: unknown } };
            if (t.function?.name === 'flagEscalation') {
              const a = parseToolArguments(t.function.arguments as never) as { summary?: string };
              if (a.summary) primeWhisper(callId, a.summary);
            }
          }
        } catch {
          /* peek is best-effort */
        }
        await handleToolCalls(raw, res);
        return;
      }
      if (url.startsWith('/webhooks/vapi/events')) {
        handleEvent(raw, res);
        return;
      }
      send(res, 404, { error: 'not found' });
    } catch (err) {
      log('ERROR', String(err));
      send(res, 200, { results: [{ toolCallId: 'unknown', result: 'Sorry — something went wrong.' }] });
    }
  })();
});

server.listen(PORT, () => {
  console.log(`\n  Grace mock tool server  →  http://localhost:${String(PORT)}`);
  console.log(`    POST /vapi.tools           ${LATENCY > 0 ? `(+${String(LATENCY)}ms latency)` : ''}`);
  console.log(`    POST /webhooks/vapi/events`);
  if (FAIL_TOOL) console.log(`    fault: ${FAIL_TOOL} will fail`);
  if (TIMEOUT_TOOL) console.log(`    fault: ${TIMEOUT_TOOL} will hang`);
  if (process.env['GRACE_MOCK_NOW']) console.log(`    clock frozen at ${process.env['GRACE_MOCK_NOW']}`);
  console.log('');
});
