import { z } from 'zod';

/**
 * The Vapi ⇄ Core API wire contract. Shared by the mock server today and by Core API
 * later, so both are provably speaking the same protocol (doc 08 §10).
 */

// ─── Inbound: tool calls ───────────────────────────────────────────────────────

export const VapiToolCall = z.object({
  id: z.string(),
  type: z.literal('function').optional(),
  function: z.object({
    name: z.string(),
    /**
     * Vapi sends this as an object, but has historically sent a JSON string. Accept both —
     * a string here is a wire-level surprise, not a caller error, and must not 500.
     */
    arguments: z.union([z.record(z.unknown()), z.string()]),
  }),
});

export const VapiCall = z.object({
  id: z.string(),
  assistantId: z.string().optional(),
  phoneNumberId: z.string().optional(),
  customer: z.object({ number: z.string().optional() }).partial().optional(),
});

export const VapiToolCallsPayload = z.object({
  message: z.object({
    type: z.literal('tool-calls').optional(),
    toolCalls: z.array(VapiToolCall).min(1),
    call: VapiCall.optional(),
  }),
  call: VapiCall.optional(),
});

/**
 * Response envelope. ALWAYS this shape, even on error — an HTTP 500 gives the model
 * nothing to say, which is dead air (doc 04 §5.1 rule 4).
 *
 * `result` is a spoken English sentence, never JSON: numbers in spoken form, at most
 * three options, machine data only as an echo-able token like `hold-7K2`.
 */
export const VapiToolResult = z.object({
  toolCallId: z.string(),
  name: z.string().optional(),
  result: z.string(),
});

export const VapiToolResponse = z.object({
  results: z.array(VapiToolResult),
});

// ─── Inbound: server events (assistant-level webhook) ──────────────────────────

export const VapiServerMessageType = z.enum([
  'end-of-call-report',
  'status-update',
  'hang',
  'tool-calls',
  'transfer-destination-request',
]);

export const VapiEventPayload = z.object({
  message: z.object({
    type: VapiServerMessageType,
    call: VapiCall.optional(),
    endedReason: z.string().optional(),
    analysis: z
      .object({
        summary: z.string().optional(),
        structuredData: z.record(z.unknown()).optional(),
        successEvaluation: z.string().optional(),
      })
      .optional(),
    artifact: z
      .object({
        messages: z.array(z.record(z.unknown())).optional(),
        transcript: z.string().optional(),
        recordingUrl: z.string().optional(),
      })
      .optional(),
  }),
});

// ─── Outbound: transfer destination ────────────────────────────────────────────

export const TransferPlanMode = z.enum([
  'blind-transfer',
  'blind-transfer-add-summary-to-sip-header',
  'warm-transfer-say-message',
  'warm-transfer-say-summary',
  'warm-transfer-twiml',
  'warm-transfer-wait-for-operator-to-speak-first-and-then-say-message',
  'warm-transfer-wait-for-operator-to-speak-first-and-then-say-summary',
  'warm-transfer-experimental',
]);

export const TransferDestinationResponse = z.object({
  destination: z.object({
    type: z.literal('number'),
    number: z.string(),
    /** `'{{customer.number}}'` preserves caller ID on transfer — resolves A-04 by config. */
    callerId: z.string().optional(),
    message: z.string().optional(),
    transferPlan: z
      .object({
        mode: TransferPlanMode,
        message: z.string().optional(),
        sipVerb: z.enum(['refer', 'bye', 'dial']).optional(),
        dialTimeout: z.number().int().positive().optional(),
        fallbackPlan: z
          .object({
            message: z.string(),
            endCallEnabled: z.boolean(),
          })
          .optional(),
      })
      .optional(),
  }),
});

export type VapiToolCall = z.infer<typeof VapiToolCall>;
export type VapiToolCallsPayload = z.infer<typeof VapiToolCallsPayload>;
export type VapiToolResponse = z.infer<typeof VapiToolResponse>;
export type VapiEventPayload = z.infer<typeof VapiEventPayload>;
export type TransferDestinationResponse = z.infer<typeof TransferDestinationResponse>;

/** Normalises the string-or-object `arguments` quirk into a plain object. */
export function parseToolArguments(raw: VapiToolCall['function']['arguments']): unknown {
  if (typeof raw !== 'string') return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}
