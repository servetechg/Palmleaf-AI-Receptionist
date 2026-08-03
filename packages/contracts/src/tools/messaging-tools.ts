import { z } from 'zod';

import { BookingRef, ToolAck } from './_shared.js';

/**
 * Tools 8–10: async messaging. Vapi marks async tools resolved immediately and never
 * delivers the response to the model (doc 08 §4.2) — so the caller-facing acknowledgement
 * MUST come from the tool's `request-start` message, never from `result`.
 *
 * All three are gated on GATE-09 (A2P 10DLC). Until the campaign is verified the handler
 * falls back to email and says so; it never silently drops the message.
 */

const SendResult = ToolAck.extend({
  data: z
    .object({
      queued: z.boolean(),
      channel: z.enum(['sms', 'email', 'none']),
      /** Set when 10DLC is unverified and SMS was substituted or suppressed. */
      degradedReason: z.enum(['10dlc_pending', 'opted_out', 'no_contact_method']).nullable(),
    })
    .optional(),
});

// ─── 8. sendIntakeForm ─────────────────────────────────────────────────────────

export const SendIntakeFormInput = z
  .object({
    bookingRef: BookingRef,
  })
  .strict();

export const SendIntakeFormOutput = SendResult;

// ─── 9. sendDepositLink ────────────────────────────────────────────────────────

export const SendDepositLinkInput = z
  .object({
    bookingRef: BookingRef,
  })
  .strict();

export const SendDepositLinkOutput = SendResult;

// ─── 10. sendBookingConfirmation ───────────────────────────────────────────────

export const SendBookingConfirmationInput = z
  .object({
    bookingRef: BookingRef,
  })
  .strict();

export const SendBookingConfirmationOutput = SendResult;

export type SendIntakeFormInput = z.infer<typeof SendIntakeFormInput>;
export type SendIntakeFormOutput = z.infer<typeof SendIntakeFormOutput>;
export type SendDepositLinkInput = z.infer<typeof SendDepositLinkInput>;
export type SendDepositLinkOutput = z.infer<typeof SendDepositLinkOutput>;
export type SendBookingConfirmationInput = z.infer<typeof SendBookingConfirmationInput>;
export type SendBookingConfirmationOutput = z.infer<typeof SendBookingConfirmationOutput>;
