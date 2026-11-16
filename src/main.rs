//! Idiomatic modern Rust — the other half of the claim (#58). This fixture
//! must pass the ENTIRE gate at 0 errors / 0 warnings: fmt, clippy with
//! pedantic and the curated picks, cargo-deny, and `cargo test`. If the
//! baseline flags this file, the baseline is over-strict — fix the config,
//! do not add #[allow] here.

fn greet(name: &str) -> String {
    format!("hello, {name}")
}

fn main() {
    let name = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "world".to_string());
    println!("{}", greet(&name));
}

#[cfg(test)]
mod tests {
    use super::greet;

    #[test]
    fn greets_by_name() {
        assert_eq!(greet("maxi"), "hello, maxi");
    }
}
