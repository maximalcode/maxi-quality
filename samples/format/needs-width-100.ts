// THE ABLATION FOR `printWidth: 100`.
//
// This file is Prettier-clean under configs/typescript/prettier.config.mjs and
// Prettier-DIRTY under Prettier's own defaults, and the only setting that
// separates the two verdicts is printWidth.
//
// The call below is 96 characters wide. At our 100 it stays on one line; at
// Prettier's default 80 it is broken across four. So a CI step that runs this
// file twice — once with our config, once with none — and requires the two
// answers to differ proves the setting is load-bearing, which `bad-format.ts`
// on its own cannot do: Prettier's defaults reject that one too.
//
// If you edit this file, keep the long line between 81 and 100 characters or
// the ablation stops separating anything.

export function describe(name: string, port: number, secure: boolean): string {
  return formatEndpointDescription(name, port, secure, 'the ablation depends on this width');
}

function formatEndpointDescription(
  name: string,
  port: number,
  secure: boolean,
  note: string,
): string {
  return `${name}:${String(port)} ${secure ? 'https' : 'http'} — ${note}`;
}
