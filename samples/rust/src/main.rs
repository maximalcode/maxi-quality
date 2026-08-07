//! Deliberately BAD Rust — the Layer 1 fixture (#58). Every construct below
//! baits a specific lint, and CI asserts the exact finding set against
//! samples/expected/clippy.json. If this file stops failing, the config
//! regressed: fix the config, never the sample (CLAUDE.md §5).
//!
//! The extra spaces before the brace on `main` are the FORMATTING bait —
//! `cargo fmt --check` must reject this file. Do not format it.

fn main()    {
    let total: u64 = 5_000_000_000;

    // pedantic: cast_possible_truncation — a u64 stuffed into a u32 silently
    // drops the high bits; this value does not fit.
    let truncated = total as u32;
    println!("{truncated}");

    // nursery pick: or_fun_call — the fallback String is allocated even when
    // the Some path is taken; unwrap_or_else is the lazy form.
    let name = std::env::args().next().unwrap_or("fallback".to_string());
    println!("{name}");

    // nursery pick: collection_is_never_read — filled and never read, dead
    // logic wearing live syntax.
    let mut audit_log = Vec::new();
    audit_log.push("started");

    // rust lint at forbid: unsafe_code — this is the one that is a hard
    // error even locally, not a warning CI escalates.
    let raw = &total as *const u64;
    unsafe {
        println!("{}", *raw);
    }

    println!("{}", styled());
}

// clippy::all (style): needless_return — proves the base group fires, not
// just pedantic and the curated picks.
fn styled() -> u64 {
    return 7;
}
