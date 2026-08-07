import ms from 'ms';
import get from 'lodash/get.js';
import { usedHelper } from './util.js';
import { fetchThing } from './barrel/index.js';

export async function main(): Promise<void> {
  const timeout = ms('2s');
  const value: unknown = get({ a: 1 }, 'a');
  console.log(usedHelper('order'), timeout, value);
  console.log(fetchThing('x'));
  const lazy = await import('./lazy.js');
  lazy.onDemand();
}
