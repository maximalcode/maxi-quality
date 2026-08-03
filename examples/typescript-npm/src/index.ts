export interface Clock {
  now: () => Date;
}

export function isExpired(at: Date, clock: Clock): boolean {
  return at.getTime() <= clock.now().getTime();
}
