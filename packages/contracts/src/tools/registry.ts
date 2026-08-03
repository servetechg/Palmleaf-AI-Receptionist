import type { z } from 'zod';

import {
  CheckAvailabilityInput,
  CheckAvailabilityOutput,
  GetBusinessInfoInput,
  GetBusinessInfoOutput,
  GetServicesAndPricingInput,
  GetServicesAndPricingOutput,
  LookupCustomerInput,
  LookupCustomerOutput,
} from './read-tools.js';
import {
  CancelAppointmentInput,
  CancelAppointmentOutput,
  CreateBookingInput,
  CreateBookingOutput,
  RescheduleAppointmentInput,
  RescheduleAppointmentOutput,
} from './write-tools.js';
import {
  SendBookingConfirmationInput,
  SendBookingConfirmationOutput,
  SendDepositLinkInput,
  SendDepositLinkOutput,
  SendIntakeFormInput,
  SendIntakeFormOutput,
} from './messaging-tools.js';
import {
  FlagEscalationInput,
  FlagEscalationOutput,
  FlagMedicalHoldInput,
  FlagMedicalHoldOutput,
  TakeMessageInput,
  TakeMessageOutput,
} from './escalation-tools.js';

/**
 * THE registry. One entry per function tool; everything downstream derives from it —
 * `generate-tools.ts`, the mock server's dispatch table, and eventually Core API's router.
 * Adding a tool means adding a row here and nothing else.
 *
 * `transferToHuman` is absent by design: it is a `transferCall` tool with no parameters
 * and no zod source (doc 08 §7.1). It lives only as hand-authored JSON.
 */

export interface ToolSpec {
  /** Tool name as the model sees it. */
  readonly name: string;
  /**
   * Read by the model on every turn — prompt real estate. Written as an instruction to a
   * new receptionist, including what NOT to do with the tool (doc 08 §4.3).
   */
  readonly description: string;
  readonly input: z.ZodTypeAny;
  readonly output: z.ZodTypeAny;
  /**
   * p95 latency TARGET in ms, from doc 08 §4. NOT a deadline — the deadline is
   * GRACE_TOOL_DEADLINE_MS. Racing a handler against this fires the fallback on ~5% of
   * healthy calls (doc 01 ADR-0012, doc 08 §12 correction 12). `null` for async tools.
   */
  readonly budgetMs: number | null;
  /** Vapi `async: true` — resolved immediately, response never reaches the model. */
  readonly async: boolean;
  /** Writes state; must be idempotent on `${callId}:${toolCallId}` (I3). */
  readonly write: boolean;
  /** Spoken while the tool runs. Required for async tools — their result is never spoken. */
  readonly requestStart?: string;
  /** Spoken if the tool errors. Must never invent a fact (GROUNDING rule). */
  readonly requestFailed?: string;
  /**
   * Async tool that deliberately says nothing, because the tool the prompt requires
   * immediately after it does the speaking. Without this escape hatch the validator would
   * force a filler phrase and the caller would hear two acknowledgements in a row.
   */
  readonly ackedByNextTool?: true;
}

export const TOOL_REGISTRY = [
  {
    name: 'getBusinessInfo',
    description:
      'Answer a factual question about the business — hours, address, parking, how to reach us, what we offer, policies, or memberships. Call this instead of answering from memory; you do not know these facts. If the tool says it has no approved answer, do not improvise — escalate.',
    input: GetBusinessInfoInput,
    output: GetBusinessInfoOutput,
    budgetMs: 150,
    async: false,
    write: false,
  },
  {
    name: 'lookupCustomer',
    description:
      "Look up the caller by the number they are calling from, so you can greet them by name and know if they are a member. Call this early. It tells you IF they are a member but NOT what members pay — always call getServicesAndPricing for any price.",
    input: LookupCustomerInput,
    output: LookupCustomerOutput,
    budgetMs: 250,
    async: false,
    write: false,
  },
  {
    name: 'getServicesAndPricing',
    description:
      'Get services, durations and prices. Call this before stating ANY price or service length. Never quote a price this tool did not return, and never estimate or say "usually about". If it reports the catalogue is unapproved, say you will have someone confirm the price and escalate.',
    input: GetServicesAndPricingInput,
    output: GetServicesAndPricingOutput,
    budgetMs: 200,
    async: false,
    write: false,
    requestFailed: "I'm having trouble pulling up our pricing right now.",
  },
  {
    name: 'checkAvailability',
    description:
      "Find open appointment times. Call this whenever the caller asks about availability, mentions a day or time they'd like, or after they choose a service. NEVER guess or state a time this tool did not return. If the caller says something vague like 'sometime next week', pick the first date of that range and call this — you can call it again for other days.",
    input: CheckAvailabilityInput,
    output: CheckAvailabilityOutput,
    budgetMs: 400,
    async: false,
    write: false,
    requestStart: 'Let me check the schedule.',
    requestFailed: "I'm having trouble reaching the schedule right now.",
  },
  {
    name: 'createBooking',
    description:
      'Book the appointment. Call this only after the caller has chosen a specific time you offered AND you have asked the medical screening question. Pass the slot id exactly as checkAvailability gave it. If they disclosed anything medical, do not call this — call flagMedicalHold and escalate.',
    input: CreateBookingInput,
    output: CreateBookingOutput,
    budgetMs: 600,
    async: false,
    write: true,
    requestStart: 'Let me get that booked for you.',
    requestFailed: "I'm having trouble completing that booking.",
  },
  {
    name: 'rescheduleAppointment',
    description:
      'Move an existing appointment to a new day or time. The tool decides whether a change fee applies — you do not. State the fee it returns, in full, before confirming, and only set feeAcknowledged once the caller has agreed.',
    input: RescheduleAppointmentInput,
    output: RescheduleAppointmentOutput,
    budgetMs: 700,
    async: false,
    write: true,
    requestStart: 'Let me look at that for you.',
    requestFailed: "I'm having trouble changing that appointment.",
  },
  {
    name: 'cancelAppointment',
    description:
      'Cancel an existing appointment. The tool decides whether a cancellation fee applies — you do not, and you must never waive one. State the fee it returns before confirming. If the caller disputes it, escalate rather than arguing.',
    input: CancelAppointmentInput,
    output: CancelAppointmentOutput,
    budgetMs: 600,
    async: false,
    write: true,
    requestStart: 'Let me pull that up.',
    requestFailed: "I'm having trouble cancelling that appointment.",
  },
  {
    name: 'sendIntakeForm',
    description:
      'Text the caller their intake form after booking. Call this once, right after a successful booking. Do not read the link aloud.',
    input: SendIntakeFormInput,
    output: SendIntakeFormOutput,
    budgetMs: null,
    async: true,
    write: true,
    requestStart: "I'm texting your intake form over now.",
  },
  {
    name: 'sendDepositLink',
    description:
      'Text a secure payment link for the deposit. Use this whenever money needs collecting — never take card details by voice. Do not read the link aloud.',
    input: SendDepositLinkInput,
    output: SendDepositLinkOutput,
    budgetMs: null,
    async: true,
    write: true,
    requestStart: "I'm sending a secure payment link to your phone now.",
  },
  {
    name: 'sendBookingConfirmation',
    description:
      'Text the booking confirmation. Call this after booking, rescheduling, or cancelling so the caller has it in writing.',
    input: SendBookingConfirmationInput,
    output: SendBookingConfirmationOutput,
    budgetMs: null,
    async: true,
    write: true,
    requestStart: "I'm sending your confirmation by text.",
  },
  {
    name: 'takeMessage',
    description:
      'Take a message for the team when nobody can be reached or the caller prefers a callback. Capture their name, callback number, and a one-line subject. Never record health or medical detail.',
    input: TakeMessageInput,
    output: TakeMessageOutput,
    budgetMs: 300,
    async: false,
    write: true,
    requestStart: 'Let me take that down.',
  },
  {
    name: 'flagMedicalHold',
    description:
      'Call this the instant a caller mentions surgery, an injury, a condition, medication, pregnancy, or any treatment — even in passing. It blocks the booking so a qualified person can follow up. Do NOT ask what the condition is, do NOT repeat it back, and do NOT record it anywhere. After calling this, escalate.',
    input: FlagMedicalHoldInput,
    output: FlagMedicalHoldOutput,
    budgetMs: 300,
    async: false,
    write: true,
  },
  {
    name: 'flagEscalation',
    description:
      'Call this IMMEDIATELY BEFORE transferToHuman, every single time. It creates the staff task and gives the person picking up the context they need — without it they answer blind. Summarise in one sentence, and never put medical or health detail in the summary; say "a health matter" instead.',
    input: FlagEscalationInput,
    output: FlagEscalationOutput,
    budgetMs: null,
    async: true,
    write: true,
    // Silent on purpose: transferToHuman fires immediately after and speaks
    // "Of course — let me get someone for you." Two acknowledgements would be worse.
    ackedByNextTool: true,
  },
] as const satisfies readonly ToolSpec[];

export type ToolName = (typeof TOOL_REGISTRY)[number]['name'];

export const TOOL_NAMES: readonly ToolName[] = TOOL_REGISTRY.map((t) => t.name);

export function getToolSpec(name: string): ToolSpec | undefined {
  return TOOL_REGISTRY.find((t) => t.name === name);
}

/**
 * Tools that exist in Vapi but have no zod source, so `generate-tools.ts` must not
 * produce them and the drift check must not treat them as orphans. Both are Vapi tool
 * *types* rather than function tools, so neither takes parameters.
 *
 * `endCall` used to be the assistant flag `endCallFunctionEnabled`. That property no
 * longer exists on `CreateAssistantDTO` — verified 2026-08-03 — and hanging up is now an
 * explicit `type: "endCall"` tool.
 */
export const HAND_AUTHORED_TOOLS = ['transferToHuman', 'endCall'] as const;

/** Total tools registered in Vapi: 13 generated + 2 hand-authored. */
export const TOTAL_TOOL_COUNT = TOOL_REGISTRY.length + HAND_AUTHORED_TOOLS.length;
