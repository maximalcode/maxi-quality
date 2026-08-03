// PROVES: "module"/"moduleResolution": "nodenext".
//
// Node's ESM resolver does not extension-guess. An extensionless relative import
// type-checks under a bundler resolution and throws ERR_MODULE_NOT_FOUND when
// Node runs it — the compiler settings are the only thing standing between the
// two.
//
// MUST PRODUCE: TS2835 — samples/expected/tsc.json holds the line.
import { WIDGET_KIND } from './types';

export const kind: string = WIDGET_KIND;
