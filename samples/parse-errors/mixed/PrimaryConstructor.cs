namespace Sample.ParseErrors;

// UNPARSEABLE BY SEMGREP, ON PURPOSE. This is a C# 12 primary constructor —
// `class Name(args)` — and semgrep's C# parser rejects the form:
//
//   Syntax error at line PrimaryConstructor.cs:N: `(int timeoutSeconds)` was unexpected
//
// Measured 2026-08-05 against semgrep 1.145.0 and 1.172.0, the latter being the
// newest release on PyPI. So "upgrade semgrep" is not an available fix, which
// is why scripts/policy.py had to learn the difference between a file it could
// not read and a scan that failed (#43).
//
// This file deliberately contains NO rule violation. If it ever gains one, the
// mixed-directory test stops proving what it claims: that findings still flow
// from the files that DID parse while this one did not.
public sealed class TokenIssuer(int timeoutSeconds)
{
    public int TimeoutSeconds => timeoutSeconds;
}
