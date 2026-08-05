import ms from 'ms';

export function formatDelay(input: string): string {
  const parsed = ms(input);
  return `${parsed}ms`;
}
