/**
 * Rolls a stream of latency samples up into the four numbers a dashboard shows.
 *
 * This is the "well-covered file" half of the patch-coverage fixture: every
 * function below is exercised by the suite the committed reports were produced
 * from, apart from the two guard lines README.md names.
 */

export interface Sample {
  readonly ms: number;
  readonly ok: boolean;
}

export interface Rollup {
  readonly count: number;
  readonly mean: number;
  readonly p95: number;
  readonly errorRate: number;
}

export function sum(values: readonly number[]): number {
  let total = 0;
  for (const value of values) {
    total += value;
  }
  return total;
}

export function mean(values: readonly number[]): number {
  if (values.length === 0) {
    return 0;
  }
  return sum(values) / values.length;
}

export function percentile(values: readonly number[], p: number): number {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length) - 1;
  const index = Math.min(Math.max(rank, 0), sorted.length - 1);
  return sorted[index];
}

export function errorRate(samples: readonly Sample[]): number {
  if (samples.length === 0) {
    return 0;
  }
  const failed = samples.filter((sample) => !sample.ok).length;
  return failed / samples.length;
}

export function slowest(samples: readonly Sample[], limit: number): Sample[] {
  const ordered = [...samples].sort((a, b) => b.ms - a.ms);
  return ordered.slice(0, limit);
}

/**
 * Added by the fixture change: computes the median absolute deviation.
 */
export function medianAbsoluteDeviation(values: readonly number[]): number {
  const middle = percentile(values, 50);
  const spread = values.map((value) => Math.abs(value - middle));
  return percentile(spread, 50);
}

export function rollup(samples: readonly Sample[]): Rollup {
  const durations = samples.map((sample) => sample.ms);
  return {
    count: samples.length,
    mean: mean(durations),
    p95: percentile(durations, 95),
    errorRate: errorRate(samples),
  };
}
