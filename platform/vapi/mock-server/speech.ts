/**
 * Spoken-English formatters (doc 04 §5.2).
 *
 * These move into `@grace/formatters` unchanged when Core API lands — the phrasing work is
 * not throwaway. All pure functions, all unit-testable.
 *
 * Timezone rule: a bare `YYYY-MM-DD` from the model means a **Chicago** calendar date, not
 * UTC. Parsing it with `new Date('2026-08-04')` yields UTC midnight, which renders as the
 * *previous* day in Chicago — an off-by-one that would have Grace confidently say the
 * wrong weekday. Always go through `chicagoDate()`.
 */

const TZ = 'America/Chicago';

const UNITS = [
  'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
  'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
  'seventeen', 'eighteen', 'nineteen',
];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];

/** 0–99 in words. `hyphen` joins tens and units the way prices read: "thirty-five". */
function underHundred(n: number, hyphen: boolean): string {
  if (n < 20) return UNITS[n] ?? String(n);
  const t = TENS[Math.floor(n / 10)] ?? '';
  const u = n % 10;
  if (u === 0) return t;
  return hyphen ? `${t}-${UNITS[u] ?? ''}` : `${t} ${UNITS[u] ?? ''}`;
}

/**
 * Builds a Date for a Chicago wall-clock time, accounting for CST/CDT automatically by
 * measuring the zone's actual offset on that date rather than hardcoding one.
 */
export function chicagoDate(ymd: string, hour = 12, minute = 0): Date {
  const [y, m, d] = ymd.split('-').map(Number);
  const guess = Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1, hour, minute);
  // Render the guess in Chicago and measure how far off it landed, then correct.
  const shown = new Date(
    new Date(guess).toLocaleString('en-US', { timeZone: TZ }),
  ).getTime();
  const utcShown = new Date(new Date(guess).toLocaleString('en-US', { timeZone: 'UTC' })).getTime();
  return new Date(guess + (utcShown - shown));
}

/** "2:15 PM" → "two fifteen". Never "14:15". */
export function speakTime(iso: string | Date): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: TZ,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).formatToParts(typeof iso === 'string' ? new Date(iso) : iso);

  const hour = Number(parts.find((p) => p.type === 'hour')?.value ?? '0');
  const minute = Number(parts.find((p) => p.type === 'minute')?.value ?? '0');

  const h = UNITS[hour] ?? String(hour);
  if (minute === 0) return h;
  if (minute < 10) return `${h} oh ${UNITS[minute] ?? String(minute)}`;
  // Hyphenated, matching speakPrice — TTS renders both identically, so pick one and
  // be consistent rather than having two conventions in the same sentence.
  return `${h} ${underHundred(minute, true)}`;
}

const ORDINAL_IRREGULAR: Record<number, string> = {
  1: 'first', 2: 'second', 3: 'third', 5: 'fifth', 8: 'eighth', 9: 'ninth', 12: 'twelfth',
  20: 'twentieth', 30: 'thirtieth',
};

function ordinal(n: number): string {
  if (ORDINAL_IRREGULAR[n]) return ORDINAL_IRREGULAR[n];
  if (n < 20) return `${UNITS[n] ?? String(n)}th`;
  const t = Math.floor(n / 10) * 10;
  const u = n % 10;
  if (u === 0) return ORDINAL_IRREGULAR[t] ?? `${TENS[t / 10] ?? ''}th`;
  return `${TENS[t / 10] ?? ''}-${ORDINAL_IRREGULAR[u] ?? `${UNITS[u] ?? ''}th`}`;
}

/** "2026-08-04" → "Tuesday the fourth". Accepts a bare date or an instant. */
export function speakDate(input: string | Date): string {
  const d =
    typeof input === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(input)
      ? chicagoDate(input)
      : new Date(input);
  const weekday = new Intl.DateTimeFormat('en-US', { timeZone: TZ, weekday: 'long' }).format(d);
  const day = Number(new Intl.DateTimeFormat('en-US', { timeZone: TZ, day: 'numeric' }).format(d));
  return `${weekday} the ${ordinal(day)}`;
}

/** 13500 → "one thirty-five". 11500 → "one fifteen". 9900 → "ninety-nine". */
export function speakPrice(cents: number): string {
  const dollars = Math.floor(cents / 100);
  const rem = cents % 100;

  let spoken: string;
  if (dollars < 100) {
    spoken = underHundred(dollars, true);
  } else {
    const hundreds = Math.floor(dollars / 100);
    const rest = dollars % 100;
    const h = UNITS[hundreds] ?? String(hundreds);
    if (rest === 0) spoken = `${h} hundred`;
    else if (rest < 10) spoken = `${h} oh ${UNITS[rest] ?? String(rest)}`;
    // "one thirty-five", not "one hundred and thirty-five" — how people say a price.
    else spoken = `${h} ${underHundred(rest, true)}`;
  }

  return rem === 0 ? spoken : `${spoken} ${underHundred(rem, true)}`;
}

/** Joins at most three options the way a person would say them. */
export function speakList(items: string[]): string {
  const three = items.slice(0, 3);
  if (three.length === 0) return '';
  if (three.length === 1) return three[0] ?? '';
  if (three.length === 2) return `${three[0] ?? ''} or ${three[1] ?? ''}`;
  return `${three[0] ?? ''}, ${three[1] ?? ''}, or ${three[2] ?? ''}`;
}
