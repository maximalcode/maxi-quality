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

**The workflow here is the same six lines as every other example**, and that is
the point of #70. It used to carry a second, hand-stamped `rust` job, on the
argument that the toolchain bump belonged in this repo's own diff — but a job
`adopt.sh` writes into your repo only moves when someone re-runs `adopt.sh`,
which is the copy-paste-drift this baseline exists to remove. The toolchain and
cargo-deny are pinned in the reusable workflow now, and `rust-version` is the
input if you need to hold one back. Warnings are still errors in CI only
(`RUSTFLAGS=-Dwarnings`), so an analyzer upgrade that adds lints stays a
breaking change rather than a Tuesday.

**`Cargo.lock` is committed here because the gate requires it.** Everything runs
`--locked`, which cannot run without a lockfile, so detection stops the run for
a crate that has none rather than reporting "no Rust here" and going green. The
gate itself is `cargo fmt --check`, `cargo clippy` and `cargo deny` — not your
tests, the same split as the TypeScript and Python jobs.

`rustfmt.toml` and `deny.toml` are genuine copies (neither tool has an extend
mechanism) — regenerate them with `adopt.sh`, do not hand-edit. `deny.toml`
ships an **empty licence allowlist**, so the licences check is not in the gate
until you fill in your policy and add `licenses` to the `cargo deny check`
line.
