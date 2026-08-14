# `examples/` — copyable consumer repos

Six complete consumer repos, each asserted by CI to scan clean and to gate
correctly. Copy the directory that matches the shape of your repo rather than
assembling snippets, then run `adopt.sh` against it to get the files that cannot
be consumed remotely. If your repo is not new, start with
[`legacy-ratchet/`](legacy-ratchet/).

| Example | Shape | Shows |
|---|---|---|
| [`typescript-npm/`](typescript-npm/) | one TS package, npm | the 3-line `eslint.config.mjs`, the `tsconfig.json`, the lint script that makes `no-console` count, and a **fully adopted** dead-code gate — `knip.json`, `dead-code: require`, `dead-code-exports: true` |
| [`dotnet/`](dotnet/) | one C# project | how little a consumer writes — `Directory.Build.props` does it all, no `.csproj` changes |
| [`python-uv/`](python-uv/) | one Python package, uv | the `extend-` prefixes, which are load-bearing, and `deptry` as a dev dependency with `dead-code: require` |
| [`rust-cli/`](rust-cli/) | one Rust binary crate | the `[lints]` block in the consumer's own `Cargo.toml` — the one thing Cargo forces a copy of, and the only thing |
| [`mixed-monorepo/`](mixed-monorepo/) | TS + C# side by side | pinning `languages:`, and a `.maxi-quality.yml` that disables and downgrades |
| [`legacy-ratchet/`](legacy-ratchet/) | an existing repo nobody has linted | `changed-only` + `languages: none` — **start here if the repo is not new** |

**These are not fixtures.** `samples/` holds deliberately broken code that the
baseline must reject. Everything here is the correct thing to copy. CI asserts
that each example scans clean, is detected as the language it claims, and where
it carries a `.maxi-quality.yml`, that the policy actually resolves.

Full walkthrough: [`../docs/ADOPTION.md`](../docs/ADOPTION.md).
