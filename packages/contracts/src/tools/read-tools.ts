import { z } from 'zod';

import { Instant, LocalDate, PhoneE164, PublicSlotId, TimePreference } from './_shared.js';

/**
 * Tools 1–4: the read path. No side effects, no idempotency key, safe to retry
 * (doc 08 §4 — these are the only tools carrying a `backoffPlan`).
 */

// ─── 1. getBusinessInfo ────────────────────────────────────────────────────────

export const GetBusinessInfoInput = z
  .object({
    topic: z
      .enum(['hours', 'location', 'parking', 'contact', 'services_overview', 'policies', 'memberships'])
      .describe(
        'What the caller asked about. Pick the closest match. If nothing fits, do NOT call this — escalate instead.',
      ),
  })
  .strict();

export const GetBusinessInfoOutput = z.object({
  /** Already phrased for speech. The model paraphrases lightly; it must not add facts. */
  answer: z.string(),
  /** False when no approved entry exists — the model must escalate, never improvise. */
  approved: z.boolean(),
});

// ─── 2. lookupCustomer ─────────────────────────────────────────────────────────

export const LookupCustomerInput = z
  .object({
    phone: PhoneE164.describe(
      "The caller's own number from caller ID. You may NOT look up any other number — asking a caller for someone else's number and querying it is not permitted.",
    ),
  })
  .strict();

export const LookupCustomerOutput = z.object({
  found: z.boolean(),
  firstName: z.string().nullable(),
  isMember: z.boolean(),
  /** Present only when found; used to greet by name. Never a full profile. */
  visitCount: z.number().int().nonnegative().nullable(),
  /** True if any booking is upcoming — lets Grace offer reschedule/cancel without a second lookup. */
  hasUpcomingBooking: z.boolean(),
});

// ─── 3. getServicesAndPricing ──────────────────────────────────────────────────

export const GetServicesAndPricingInput = z
  .object({
    query: z
      .string()
      .min(1)
      .max(120)
      .describe(
        "What the caller asked for, in their words, e.g. '60 minute massage' or 'deep tissue'. Pass it through verbatim.",
      ),
    isMember: z
      .boolean()
      .default(false)
      .describe('Set true only if lookupCustomer already confirmed membership. Never assume.'),
  })
  .strict();

export const GetServicesAndPricingOutput = z.object({
  services: z
    .array(
      z.object({
        serviceCode: z.string(),
        name: z.string(),
        durationMinutes: z.number().int().positive(),
        priceCents: z.number().int().nonnegative(),
        memberPriceCents: z.number().int().nonnegative().nullable(),
        depositRequired: z.boolean(),
      }),
    )
    .max(3),
  /** False when the catalogue is unapproved (GATE-04) — Grace must not quote a price. */
  approved: z.boolean(),
});

// ─── 4. checkAvailability ──────────────────────────────────────────────────────

export const CheckAvailabilityInput = z
  .object({
    serviceCode: z
      .string()
      .min(1)
      .describe('Service code, e.g. massage_60. Call getServicesAndPricing first to get it.'),
    preferredDate: LocalDate,
    timePreference: TimePreference.default('any'),
    // `.optional()`, never `.nullable()` — see the note at the bottom of this file.
    providerPreference: z
      .string()
      .optional()
      .describe('Provider name if the caller asked for someone specific. Omit if they did not.'),
    partySize: z.number().int().min(1).max(4).default(1).describe('Number of people. Almost always 1.'),
  })
  .strict();

export const CheckAvailabilityOutput = z.object({
  slots: z
    .array(
      z.object({
        slotId: PublicSlotId,
        startsAt: Instant,
        providerId: z.string(),
        providerName: z.string(),
        priceCents: z.number().int().nonnegative(),
        holdExpiresAt: Instant,
      }),
    )
    /** Hard cap of 3: the prompt forbids reading more than three options aloud. */
    .max(3),
  alternativesAvailable: z.boolean(),
});

/**
 * ⚠️ Tool INPUT schemas must never use `.nullable()`.
 *
 * `zod-to-json-schema` renders a nullable field with any constraint (`.max()`, `.min()`, …)
 * as `anyOf: [{type:"string",…},{type:"null"}]`, and **Vapi rejects `anyOf` in tool
 * parameters** with `400 function.parameters.properties.X.type must be one of …`.
 * Verified against the live API on 2026-08-03.
 *
 * Use `.optional()` instead. It is also the better LLM affordance: the model omits the
 * field rather than reasoning about whether to send an explicit null.
 * `generate-tools.ts` enforces this statically so it can never reach a deploy again.
 *
 * OUTPUT schemas are unaffected — they never leave our process.
 */
export type GetBusinessInfoInput = z.infer<typeof GetBusinessInfoInput>;
export type GetBusinessInfoOutput = z.infer<typeof GetBusinessInfoOutput>;
export type LookupCustomerInput = z.infer<typeof LookupCustomerInput>;
export type LookupCustomerOutput = z.infer<typeof LookupCustomerOutput>;
export type GetServicesAndPricingInput = z.infer<typeof GetServicesAndPricingInput>;
export type GetServicesAndPricingOutput = z.infer<typeof GetServicesAndPricingOutput>;
export type CheckAvailabilityInput = z.infer<typeof CheckAvailabilityInput>;
export type CheckAvailabilityOutput = z.infer<typeof CheckAvailabilityOutput>;
