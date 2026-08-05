namespace Sample.Format;

// THE ABLATION FOR `insert_final_newline = true`.
//
// This file is deliberately saved WITHOUT a trailing newline. `dotnet format
// whitespace` does not care by default; it is configs/editorconfig that turns
// the missing newline into a FINALNEWLINE error. Measured 2026-08-05.
//
// So the C# format step runs this file twice — once with the shipped
// .editorconfig staged beside it and once without — and requires the two
// verdicts to DIFFER. That is what proves the config drives the gate rather
// than the tool's own defaults.
//
// If your editor adds a trailing newline on save, this fixture stops proving
// anything and CI will say so.

public static class MissingFinalNewline
{
    public static int Add(int a, int b)
    {
        return a + b;
    }
}