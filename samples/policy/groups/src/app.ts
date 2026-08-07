import { createHash } from 'node:crypto';

// security/ — selected, so this MUST fire.
export function digest(s: string): string {
  return createHash('md5').update(s).digest('hex');
}

// conventions/ — NOT selected, so this must stay silent.
export function stamp(): Date {
  return new Date();
}
