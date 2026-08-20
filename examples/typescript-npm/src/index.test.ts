import { describe, expect, it } from 'vitest';

import { isExpired } from './index.js';

const at = (iso: string): Date => new Date(iso);
const clock = { now: () => at('2026-01-01T00:00:00Z') };

describe('isExpired', () => {
  it('is expired at exactly the deadline', () => {
    expect(isExpired(at('2026-01-01T00:00:00Z'), clock)).toBe(true);
  });

  it('is not expired before it', () => {
    expect(isExpired(at('2026-01-02T00:00:00Z'), clock)).toBe(false);
  });
});
