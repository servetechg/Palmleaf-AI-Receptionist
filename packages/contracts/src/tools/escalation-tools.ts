import { z } from 'zod';

import { EscalationReason, PhoneE164, ToolAck, Urgency } from './_shared.js';

/**
 * Tools 12–14: the handoff path.
 *
 * `transferToHuman` is NOT here — it is a Vapi `transferCall` tool with no `function`
 * property and therefore no zod source. It is hand-authored at
 * `platform/vapi/tools/transferToHuman.json` (doc 08 §7.1).
 */

// ─── 12. takeMessage ───────────────────────────────────────────────────────────

export const TakeMessageInput = z
  .object({
    callerName: z.string().min(1).max(80),
    callbackNumber: PhoneE164.describe(
      'Number to call back. Default to the number they are calling from unless they give a different one.',
    ),
    subject: z
      .string()
      .min(1)
      .max(120)
      .describe('One short line: what it is about. NEVER include health or medical detail.'),
    body: z
      .string()
      .max(600)
      .optional()
      .describe('Any extra detail the caller gave. Again: no health or medical detail, ever.'),
  })
  .strict();

export const TakeMessageOutput = ToolAck.extend({
  data: z.object({ taskId: z.string() }).optional(),
});

// ─── 13. flagMedicalHold ───────────────────────────────────────────────────────

/**
 * Invariant I6: this tool records that a disclosure happened. It records NOTHING about
 * what was disclosed. There is deliberately no free-text field — not even an optional one,
 * because an optional field is one a model will eventually fill.
 */
export const FlagMedicalHoldInput = z
  .object({
    // `z.boolean()`, not `z.literal(true)`: a literal renders as a scalar `const`, which
    // Vapi rejects (`const must be an object`). The handler enforces the value instead —
    // which is the right place for it anyway (I4: rules in code, not in a schema hint).
    disclosed: z
      .boolean()
      .describe(
        'Always pass true. Call this the moment a caller mentions surgery, treatment, or any health matter. Do NOT ask what it is, and do NOT describe it anywhere.',
      ),
  })
  .strict();

export const FlagMedicalHoldOutput = ToolAck.extend({
  // Output schemas never reach Vapi, so a literal is safe here.
  data: z.object({ taskId: z.string(), bookingBlocked: z.literal(true) }).optional(),
});

// ─── 14. flagEscalation ────────────────────────────────────────────────────────

/**
 * Required companion to `transferToHuman`. A `transferCall` tool takes no parameters
 * (verified: `CreateTransferCallToolDTO` has no `function` property), and the
 * `transfer-destination-request` webhook payload carries no tool arguments — so this is
 * the ONLY path by which whisper context and the staff_tasks row can be created.
 *
 * The prompt requires calling this immediately before `transferToHuman`.
 */
export const FlagEscalationInput = z
  .object({
    reason: EscalationReason,
    urgency: Urgency.default('normal'),
    summary: z
      .string()
      .min(1)
      .max(200)
      .describe(
        'One sentence of context for the person picking up, e.g. "Caller wants to dispute a late-cancel fee." NEVER include medical, health, or diagnostic detail — say "a health matter" instead.',
      ),
  })
  .strict();

export const FlagEscalationOutput = ToolAck.extend({
  data: z
    .object({
      taskId: z.string(),
      /** Confirms the whisper was cached under call.id for the destination handler. */
      whisperPrimed: z.boolean(),
    })
    .optional(),
});

export type TakeMessageInput = z.infer<typeof TakeMessageInput>;
export type TakeMessageOutput = z.infer<typeof TakeMessageOutput>;
export type FlagMedicalHoldInput = z.infer<typeof FlagMedicalHoldInput>;
export type FlagMedicalHoldOutput = z.infer<typeof FlagMedicalHoldOutput>;
export type FlagEscalationInput = z.infer<typeof FlagEscalationInput>;
export type FlagEscalationOutput = z.infer<typeof FlagEscalationOutput>;
