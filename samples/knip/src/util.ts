export interface UsedShape {
  id: string;
  label: string;
}

export interface UnusedShape {
  ghost: number;
}

export function usedHelper(id: string): UsedShape {
  return { id, label: `item-${id}` };
}

export function unusedExport(input: string): string {
  return input.trim().toUpperCase();
}
