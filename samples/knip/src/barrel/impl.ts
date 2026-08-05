export function fetchThing(key: string): string {
  return `fetched:${key}`;
}

export function storeThing(key: string, value: string): string {
  return `stored:${key}=${value}`;
}
