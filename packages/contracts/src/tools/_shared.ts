import { z } from 'zod';

/**
 * Shared primitives for tool schemas.
 *
 * Every `.describe()` here is read by the model on every turn — it is prompt real estate,
 * not documentation (doc 02 §4, doc 08 §4.3). Write for a new receptionist, not an API consumer.
 */

/** Local calendar date, `YYYY-MM-DD`. Never a timestamp — the caller speaks in local days. */
export const LocalDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, 'must be YYYY-MM-DD')
  .describe('Local date in YYYY-MM-DD. Today or later. Never guess a year the caller did not say.');

/** ISO-8601 instant, always UTC on the wire; rendered to America/Chicago at the edge. */
export const Instant = z.string().datetime().describe('ISO-8601 UTC timestamp');

/**
 * Short, human-safe public id the model can echo back without garbling it.
 * Doc 06 §5.1: `'h' + base32Crockford(...)`, e.g. `hold-7K2`. Case-insensitive on input
 * because ASR will not preserve case.
 */
export const PublicSlotId = z
  .string()
  .regex(/^hold-[0-9A-HJKMNP-TV-Z]{3,6}$/i)
  .describe('Slot id exactly as checkAvailability returned it, e.g. hold-7K2. Never invent one.');

export const BookingRef = z
  .string()
  .regex(/^bk-[0-9A-HJKMNP-TV-Z]{4,8}$/i)
  .describe('Booking reference exactly as it was given to you, e.g. bk-3QR9.');

/** E.164. The caller's own number arrives from caller ID; never ask them to recite it back. */
export const PhoneE164 = z
  .string()
  .regex(/^\+[1-9]\d{7,14}$/)
  .describe('Phone number in E.164 format, e.g. +18475550123');

export const TimePreference = z
  .enum(['morning', 'afternoon', 'evening', 'any'])
  .describe("Rough time of day the caller asked for. Use 'any' if they did not say.");

/**
 * Reasons Grace may escalate. Closed enum, never free text — this value is persisted and
 * an LLM-authored free-text field summarising a transcript is a PHI route (I6, doc 08 §3.4).
 */
export const EscalationReason = z
  .enum([
    'asked_for_person',
    'frustrated',
    'complaint',
    'refund',
    'gift_certificate',
    'medical',
    'recording_objection',
    'no_tool',
    'repeated_failure',
  ])
  .describe('Why you are handing off. Pick the closest match.');

export const Urgency = z
  .enum(['normal', 'high'])
  .describe("Use 'high' only if the caller is upset or the matter is time-critical.");

/**
 * Every write tool returns this. The router turns `spoken` into the Vapi `result` string
 * (doc 04 §5.1) and keeps `data` server-side for logging and the events webhook.
 */
export const ToolAck = z.object({
  spoken: z.string().min(1),
  data: z.record(z.unknown()).optional(),
});
export type ToolAck = z.infer<typeof ToolAck>;
