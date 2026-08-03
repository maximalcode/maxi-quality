// The disabled rule's bait. Must NOT be reported.
export function stamp(): Date {
  return new Date();
}

// TODO: not tracked anywhere — the control, and it must STILL fire.
export function other(): number {
  return 1;
}
