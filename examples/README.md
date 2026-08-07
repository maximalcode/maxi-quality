# `examples/` — copyable consumer repos

Each directory is a complete, minimal repo of one shape. Copy the one that
matches yours rather than assembling snippets, then run `adopt.sh` against it to
get the files that cannot be consumed remotely.

| Example | Shape | Shows |
|---|---|---|
| [`typescript-npm/`](typescript-npm/) | one TS package, npm | the 3-line `eslint.config.mjs`, the `tsconfig.json`, the lint script that makes `no-console` count |
| [`dotnet/`](dotnet/) | one C# project | how little a consumer writes — `Directory.Build.props` does it all, no `.csproj` changes |
| [`python-uv/`](python-uv/) | one Python package, uv | the `extend-` prefixes, which are load-bearing |
| [`rust-cli/`](rust-cli/) | one Rust binary crate | the `[lints]` block in the consumer's own `Cargo.toml`, and the pinned-toolchain `rust` job beside the reusable call |
| [`mixed-monorepo/`](mixed-monorepo/) | TS + C# side by side | pinning `languages:`, and a `.maxi-quality.yml` that disables and downgrades |
| [`legacy-ratchet/`](legacy-ratchet/) | an existing repo nobody has linted | `changed-only` + `languages: none` — **start here if the repo is not new** |

**These are not fixtures.** `samples/` holds deliberately broken code that the
baseline must reject; everything here is the correct thing to copy. CI asserts
each example scans clean, is detected as the language it claims, and — where one
carries a `.maxi-quality.yml` — that the policy actually resolves. A documented
example that would not work is a worse bug than no example.

Full walkthrough: [`../docs/ADOPTION.md`](../docs/ADOPTION.md).
