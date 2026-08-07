/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Bait for the three `dotnet_naming_rule` blocks in
 * configs/dotnet/dotnet.editorconfig, which shipped enforcing NOTHING until
 * 2026-08-03 (#8).
 *
 * They were not merely unbaited — they were switched off.
 * `dotnet_naming_rule.<rule>.severity` drives the IDE experience; the build
 * reads the diagnostic's own severity, and `dotnet_diagnostic.IDE1006.severity`
 * was never set. Measured: this exact file built clean before that one line
 * was added.
 *
 * Two of the three violations are ALSO caught by analyzers that happen to
 * overlap — which is why the gap was easy to miss and why the third case
 * matters most: a private field named `Count` was caught by nothing at all.
 *
 * EVERY TYPE HERE IS `internal` ON PURPOSE. CA1715 (interface prefix) and
 * CA1707 (underscores) only apply to externally visible identifiers, so making
 * these public would let a CA rule mask the IDE1006 this file exists to prove —
 * the same fixture-tests-the-wrong-thing trap that samples/typescript-strict
 * documents for tsc flags.
 *
 * Planted findings and the diagnostic that must fire:
 *   1. interface without the I prefix     IDE1006 (interfaces_start_with_i) + S101
 *   2. type not PascalCase                IDE1006 (types_are_pascal_case)    + S101
 *   3. private field without _camelCase   IDE1006 (private_fields_are_camel_underscore)
 *
 * Sonar's S101 covers both TYPE cases and neither field case — it suggests
 * `IRunner` and `Mywidget` respectively. So of the three conventions, exactly
 * one is ours alone, and it is the third.
 */

namespace Maximalcode.Sample;

// 1. `interfaces_start_with_i` — a rename in a consumer's codebase is cheap;
//    finding out the convention was never enforced after 300 files is not.
internal interface Runner
{
    void Go();
}

// 2. `types_are_pascal_case`. Sonar's S101 covers both this and the interface
//    above, and both overlaps are recorded in the manifest — an overlap is
//    worth knowing about, not hiding.
internal sealed class my_widget : Runner
{
    // 3. `private_fields_are_camel_underscore`. THE CASE THAT PROVES THE RULE
    //    EARNS ITS PLACE: no Roslyn or Sonar analyzer flags a PascalCase
    //    private field, so before the fix this was invisible to every layer
    //    the baseline runs.
    //
    //    Read below as well as written, deliberately — an unread private field
    //    fires IDE0052/S4487 instead and the fixture would prove those rather
    //    than this one.
    private int Count;

    public int Value => Count;

    public void Go() => Count++;
}
