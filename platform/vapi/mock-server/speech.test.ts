import { describe, expect, it } from 'vitest';

import { chicagoDate, speakDate, speakList, speakPrice, speakTime } from './speech.js';

/**
 * These lock the doc 04 §5.2 speech conventions. Every case here is something a caller
 * would actually hear, and several are regressions found by running the mock server.
 */

describe('speakTime', () => {
  it('speaks the hour alone on the hour', () => {
    expect(speakTime(chicagoDate('2026-08-04', 14, 0))).toBe('two');
  });

  it('speaks minutes without "oh" past ten', () => {
    expect(speakTime(chicagoDate('2026-08-04', 14, 15))).toBe('two fifteen');
    expect(speakTime(chicagoDate('2026-08-04', 18, 30))).toBe('six thirty');
    expect(speakTime(chicagoDate('2026-08-04', 17, 45))).toBe('five forty-five');
  });

  it('uses "oh" for single-digit minutes', () => {
    expect(speakTime(chicagoDate('2026-08-04', 9, 5))).toBe('nine oh five');
  });

  it('speaks noon and midnight as twelve, not zero', () => {
    expect(speakTime(chicagoDate('2026-08-04', 12, 0))).toBe('twelve');
    expect(speakTime(chicagoDate('2026-08-04', 0, 30))).toBe('twelve thirty');
  });
});

describe('speakDate', () => {
  // Regression: `new Date('2026-08-04')` is UTC midnight, which is Aug 3 in Chicago.
  // The mock server said "Monday the third" for a Tuesday before chicagoDate existed.
  it('treats a bare YYYY-MM-DD as a Chicago calendar date, not UTC', () => {
    expect(speakDate('2026-08-04')).toBe('Tuesday the fourth');
  });

  it('handles irregular ordinals', () => {
    expect(speakDate('2026-08-01')).toBe('Saturday the first');
    expect(speakDate('2026-08-02')).toBe('Sunday the second');
    expect(speakDate('2026-08-03')).toBe('Monday the third');
    expect(speakDate('2026-08-05')).toBe('Wednesday the fifth');
    expect(speakDate('2026-08-09')).toBe('Sunday the ninth');
    expect(speakDate('2026-08-12')).toBe('Wednesday the twelfth');
  });

  it('handles the twenties and thirties', () => {
    expect(speakDate('2026-08-20')).toBe('Thursday the twentieth');
    expect(speakDate('2026-08-21')).toBe('Friday the twenty-first');
    expect(speakDate('2026-08-23')).toBe('Sunday the twenty-third');
    expect(speakDate('2026-08-31')).toBe('Monday the thirty-first');
  });
});

describe('speakPrice', () => {
  it('speaks a price the way a receptionist says it', () => {
    expect(speakPrice(13500)).toBe('one thirty-five');
    expect(speakPrice(18500)).toBe('one eighty-five');
    expect(speakPrice(15000)).toBe('one fifty');
  });

  // Regression: TENS had no entry for 10, so 11500 came out "one 10-five".
  it('handles teens in the hundreds', () => {
    expect(speakPrice(11500)).toBe('one fifteen');
    expect(speakPrice(11000)).toBe('one ten');
    expect(speakPrice(11900)).toBe('one nineteen');
  });

  it('handles two-digit prices', () => {
    expect(speakPrice(9900)).toBe('ninety-nine');
    expect(speakPrice(4500)).toBe('forty-five');
    expect(speakPrice(800)).toBe('eight');
  });

  it('uses "oh" for a single-digit remainder in the hundreds', () => {
    expect(speakPrice(10500)).toBe('one oh five');
    expect(speakPrice(20000)).toBe('two hundred');
  });

  it('appends cents only when non-zero', () => {
    expect(speakPrice(13550)).toBe('one thirty-five fifty');
    expect(speakPrice(13500)).toBe('one thirty-five');
  });
});

describe('speakList', () => {
  it('never reads more than three options aloud', () => {
    expect(speakList(['a', 'b', 'c', 'd', 'e'])).toBe('a, b, or c');
  });

  it('joins naturally', () => {
    expect(speakList(['a'])).toBe('a');
    expect(speakList(['a', 'b'])).toBe('a or b');
    expect(speakList([])).toBe('');
  });
});
