# Rust, single binary crate

```bash
"$BASELINE"/scripts/adopt.sh .    # writes rustfmt.toml + deny.toml, appends [lints]
cargo generate-lockfile           # then COMMIT Cargo.lock — CI runs --locked
cargo fmt --check && cargo clippy --all-targets && cargo test
```

**The `[lints]` block lives in your own `Cargo.toml`, and that is the whole
Rust story.** Cargo cannot consume lint configuration from a remote package, so
Rust follows the C# pattern (adopt-time copies, like `Directory.Build.props`),
not the TypeScript one. `adopt.sh` appends the block once, marker-guarded; a
manifest that already has its own `[lints]` gets a skip and a warning, never a
merge attempt. On a workspace root the block arrives as `[workspace.lints]`
and each member opts in with two lines:

```toml
[lints]
workspace = true
```

**The workflow here has a second job, and that is deliberate.** Layer 2 needs
no Rust changes — Gitleaks is language-agnostic and OSV-Scanner reads
`Cargo.lock` natively — so the reusable call covers it. But the lint config
lives in *this* repo's manifest, so the `rust` job runs here too, with the
toolchain and cargo-deny **pinned**: warnings are errors in CI
(`RUSTFLAGS=-Dwarnings`), so an analyzer upgrade that adds lints is a breaking
change, and a floating `stable` would ship one unannounced.

`rustfmt.toml` and `deny.toml` are genuine copies (neither tool has an extend
mechanism) — regenerate them with `adopt.sh`, do not hand-edit. `deny.toml`
ships an **empty licence allowlist**, so the licences check is not in the gate
until you fill in your policy and add `licenses` to the `cargo deny check`
line.
