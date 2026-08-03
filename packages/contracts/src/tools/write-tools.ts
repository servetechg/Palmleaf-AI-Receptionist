import { z } from 'zod';

import { BookingRef, LocalDate, PublicSlotId, TimePreference, ToolAck } from './_shared.js';

/**
 * Tools 5–7: the booking write path. All idempotent (I3), all emit outbox rows (I8),
 * none carries a `backoffPlan` — a retried booking is a real-world duplicate (doc 08 §4.1).
 */

// ─── 5. createBooking ──────────────────────────────────────────────────────────

export const CreateBookingInput = z
  .object({
    slotId: PublicSlotId,
    firstName: z
      .string()
      .min(1)
      .max(60)
      .describe('Caller first name as they said it. Do not ask for a surname unless they offer one.'),
    // `.optional()`, never `.nullable()` — Vapi rejects the `anyOf` that a constrained
    // nullable renders to. See the note in read-tools.ts.
    lastName: z.string().max(60).optional(),
    /**
     * The medical gate is enforced server-side, not by the prompt alone (I4). The handler
     * rejects the booking if this is not explicitly false, so a model that skips the
     * screening question cannot book.
     */
    medicalScreenPassed: z
      .boolean()
      .describe(
        'Set true ONLY after asking the screening question and hearing a clear no. If they said yes, are unsure, or you did not ask, set false and call flagMedicalHold instead of booking.',
      ),
    notes: z
      .string()
      .max(280)
      .optional()
      .describe(
        'Scheduling preferences only, e.g. "prefers a quieter room". NEVER any health, medical, or diagnostic detail.',
      ),
  })
  .strict();

export const CreateBookingOutput = ToolAck.extend({
  data: z
    .object({
      bookingRef: BookingRef,
      confirmed: z.boolean(),
      depositRequired: z.boolean(),
    })
    .optional(),
});

// ─── 6. rescheduleAppointment ──────────────────────────────────────────────────

export const RescheduleAppointmentInput = z
  .object({
    bookingRef: BookingRef,
    newDate: LocalDate,
    newTimePreference: TimePreference.default('any'),
    /** Set once the caller has heard and accepted any fee the 48h engine returned. */
    feeAcknowledged: z
      .boolean()
      .default(false)
      .describe(
        'Set true only after you have stated the change fee and the caller agreed. Never assume agreement.',
      ),
  })
  .strict();

export const RescheduleAppointmentOutput = ToolAck.extend({
  data: z
    .object({
      bookingRef: BookingRef,
      feeCents: z.number().int().nonnegative(),
      /** Machine-readable reason from the pure 48h engine (doc 01 ADR-0011). */
      feeReason: z.enum(['inside_48h', 'outside_48h', 'waived', 'policy_unapproved']),
      rescheduled: z.boolean(),
    })
    .optional(),
});

// ─── 7. cancelAppointment ──────────────────────────────────────────────────────

export const CancelAppointmentInput = z
  .object({
    bookingRef: BookingRef,
    feeAcknowledged: z
      .boolean()
      .default(false)
      .describe('Set true only after stating the cancellation fee and hearing the caller accept it.'),
  })
  .strict();

export const CancelAppointmentOutput = ToolAck.extend({
  data: z
    .object({
      bookingRef: BookingRef,
      feeCents: z.number().int().nonnegative(),
      feeReason: z.enum(['inside_48h', 'outside_48h', 'waived', 'policy_unapproved']),
      cancelled: z.boolean(),
    })
    .optional(),
});

export type CreateBookingInput = z.infer<typeof CreateBookingInput>;
export type CreateBookingOutput = z.infer<typeof CreateBookingOutput>;
export type RescheduleAppointmentInput = z.infer<typeof RescheduleAppointmentInput>;
export type RescheduleAppointmentOutput = z.infer<typeof RescheduleAppointmentOutput>;
export type CancelAppointmentInput = z.infer<typeof CancelAppointmentInput>;
export type CancelAppointmentOutput = z.infer<typeof CancelAppointmentOutput>;
