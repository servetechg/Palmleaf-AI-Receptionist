/**
 * Canned tool responses for local development.
 *
 * Each returns a SPOKEN SENTENCE — the same contract Core API will honour (doc 04 §5.1):
 * numbers in spoken form, at most three options, machine data only as an echo-able token.
 *
 * The clock is frozen via GRACE_MOCK_NOW so "Tuesday the fourth" is reproducible across
 * runs, which is what makes voice simulations deterministic.
 */
import type {
  CancelAppointmentInput,
  CheckAvailabilityInput,
  CreateBookingInput,
  GetBusinessInfoInput,
  GetServicesAndPricingInput,
  LookupCustomerInput,
  RescheduleAppointmentInput,
  TakeMessageInput,
} from '@grace/contracts';

import { chicagoDate, speakDate, speakList, speakPrice, speakTime } from './speech.js';

export function now(): Date {
  const override = process.env['GRACE_MOCK_NOW'];
  return override ? new Date(override) : new Date();
}

// ── seed data ──────────────────────────────────────────────────────────────────

const SERVICES = [
  { serviceCode: 'massage_60', name: '60-minute massage', durationMinutes: 60, priceCents: 13500, memberPriceCents: 11500, depositRequired: false },
  { serviceCode: 'massage_90', name: '90-minute massage', durationMinutes: 90, priceCents: 18500, memberPriceCents: 16000, depositRequired: true },
  { serviceCode: 'deep_tissue_60', name: '60-minute deep tissue', durationMinutes: 60, priceCents: 15000, memberPriceCents: 13000, depositRequired: false },
];

const PROVIDERS = [
  { id: 'prv_maria', name: 'Maria' },
  { id: 'prv_james', name: 'James' },
];

const BUSINESS_INFO: Record<GetBusinessInfoInput['topic'], string> = {
  hours: 'We are open Monday through Saturday, nine in the morning until seven in the evening, and closed Sundays.',
  location: 'We are on Dundee Road in Buffalo Grove, just past the Town Center, with parking right out front.',
  parking: 'There is free parking directly in front of the building.',
  contact: 'The best way is right here on this line, or by text to the same number.',
  services_overview: 'We offer therapeutic massage, deep tissue, acupuncture, and cryotherapy.',
  policies: 'Changes and cancellations are free up to forty-eight hours before your appointment.',
  memberships: 'Members get a reduced rate on every service and priority booking.',
};

/** Stable pseudo-random so the same call id yields the same slots. */
function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

const SLOT_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
function slotId(seed: string): string {
  const h = hash(seed);
  let out = '';
  for (let i = 0; i < 3; i++) out += SLOT_ALPHABET[(h >> (i * 5)) % SLOT_ALPHABET.length] ?? '0';
  return `hold-${out}`;
}

/** In-memory bookings so createBooking → cancel/reschedule behaves coherently in one session. */
const bookings = new Map<string, { ref: string; startsAt: string; provider: string; service: string }>();

export function reset(): void {
  bookings.clear();
}

// ── handlers ───────────────────────────────────────────────────────────────────

export const FIXTURES = {
  getBusinessInfo: (args: GetBusinessInfoInput): string => {
    return BUSINESS_INFO[args.topic];
  },

  lookupCustomer: (args: LookupCustomerInput): string => {
    // Even digits → a known member, so both branches are reachable deterministically.
    const known = hash(args.phone) % 2 === 0;
    return known
      ? 'That number matches Jordan, who has been in four times and is a member.'
      : 'I do not see that number on file yet.';
  },

  getServicesAndPricing: (args: GetServicesAndPricingInput): string => {
    const q = args.query.toLowerCase();
    const matches = SERVICES.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        q.split(/\s+/).some((w) => w.length > 3 && s.name.toLowerCase().includes(w)),
    );
    const picked = (matches.length > 0 ? matches : SERVICES).slice(0, 3);
    const phrases = picked.map((s) => {
      const cents = args.isMember ? s.memberPriceCents : s.priceCents;
      return `the ${s.name} at ${speakPrice(cents)}`;
    });
    return `We have ${speakList(phrases)}.`;
  },

  checkAvailability: (args: CheckAvailabilityInput, callId: string): string => {
    const startHour = args.timePreference === 'morning' ? 9 : args.timePreference === 'evening' ? 17 : 13;

    const slots = [0, 1, 2].map((i) => {
      // chicagoDate, not setHours — the model's date is a Chicago calendar date and the
      // process timezone must not leak into it.
      const d = chicagoDate(args.preferredDate, startHour + i, i === 1 ? 30 : 15);
      const provider = PROVIDERS[i % PROVIDERS.length];
      return {
        id: slotId(`${callId}:${args.preferredDate}:${String(i)}`),
        startsAt: d.toISOString(),
        provider: provider?.name ?? 'Maria',
      };
    });

    const wanted = args.providerPreference?.toLowerCase();
    const filtered = wanted ? slots.filter((s) => s.provider.toLowerCase() === wanted) : slots;
    const offer = (filtered.length > 0 ? filtered : slots).slice(0, 3);

    if (offer.length === 0) {
      return `I don't have anything on ${speakDate(args.preferredDate)}. Would another day work?`;
    }

    const phrases = offer.map((s) => `${speakTime(s.startsAt)} with ${s.provider}`);
    const prefix =
      wanted && filtered.length === 0
        ? `${String(args.providerPreference)} isn't available then, but I have `
        : `I have `;
    return `${prefix}${speakList(phrases)} on ${speakDate(args.preferredDate)}. Which works?`;
  },

  createBooking: (args: CreateBookingInput, callId: string): string => {
    // Server-side medical gate: the prompt is not the only thing enforcing this (I4).
    if (!args.medicalScreenPassed) {
      return "Before I book, I'd like one of our team to go over a couple of health questions with you.";
    }
    const ref = `bk-${slotId(`${callId}:${args.slotId}`).slice(5)}9`;
    const startsAt = new Date(now().getTime() + 86_400_000).toISOString();
    bookings.set(ref.toLowerCase(), { ref, startsAt, provider: 'Maria', service: '60-minute massage' });
    return `You're all set, ${args.firstName} — ${speakDate(startsAt)} at ${speakTime(startsAt)} with Maria. I'll text you a confirmation.`;
  },

  rescheduleAppointment: (args: RescheduleAppointmentInput): string => {
    const b = bookings.get(args.bookingRef.toLowerCase());
    if (!b) return "I can't find that appointment — let me get someone who can look it up properly.";
    const startsAt = new Date(`${args.newDate}T18:30:00-05:00`).toISOString();
    return `Done — I've moved you to ${speakDate(startsAt)} at ${speakTime(startsAt)}. There's no charge for that change.`;
  },

  cancelAppointment: (args: CancelAppointmentInput): string => {
    const b = bookings.get(args.bookingRef.toLowerCase());
    if (!b) return "I can't find that appointment — let me get someone who can look it up properly.";
    bookings.delete(args.bookingRef.toLowerCase());
    return `That's cancelled for you. Since it's more than forty-eight hours away, there's no charge.`;
  },

  // Async tools: Vapi never delivers these to the model, so the string is for logs only.
  sendIntakeForm: (): string => 'intake form queued',
  sendDepositLink: (): string => 'deposit link queued',
  sendBookingConfirmation: (): string => 'confirmation queued',

  takeMessage: (args: TakeMessageInput): string => {
    return `Got it — I've passed that to the team and someone will call you back about ${args.subject.toLowerCase()}.`;
  },

  flagMedicalHold: (): string => {
    return "Thanks for telling me — I'd like one of our team to go over that with you before we book.";
  },

  flagEscalation: (): string => 'escalation logged',
} as const;
