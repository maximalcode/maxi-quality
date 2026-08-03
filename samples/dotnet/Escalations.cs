/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Bait for the `IDE00xx` severity escalations in
 * configs/dotnet/dotnet.editorconfig, and for `<Nullable>enable</Nullable>` in
 * configs/dotnet/Directory.Build.props (#8).
 *
 * Six IDE rules are escalated to `error` there. Two were already proven by
 * Program.cs — IDE0051 and IDE0059 — and the remaining four had no fixture at
 * all, so each could have been deleted with every job green. Three of them are
 * baited here. The fourth is measured and does not work; see below.
 *
 * `Nullable` is in the same position and worse: it is the single
 * highest-value C# analyzer setting the baseline ships, and nothing exercised
 * it. The MSBuild snapshot proves it is SET; this file proves it does something.
 *
 * Planted findings and the diagnostic that must fire:
 *   1. unnecessary using directive     IDE0005
 *   2. private member written, unread  IDE0052
 *   3. unused parameter                IDE0060
 *   4. null literal, non-nullable type CS8625  (+ CA1805, an honest overlap)
 *
 * IDE0035 (unreachable code) IS NOT BAITED, and not for want of trying.
 * Measured 2026-08-03 on .NET SDK 10: real unreachable code produces CS0162 and
 * no IDE0035 at all. With TreatWarningsAsErrors the build fails either way, so
 * the escalation is redundant rather than load-bearing. It is kept — this was
 * one SDK on one runner, and a severity line costs nothing — but it is NOT
 * covered, and saying so is the point of this paragraph.
 */

using System.Text;

namespace Maximalcode.Sample;

internal sealed class Escalations
{
    // 2. Assigned in the constructor and never read anywhere. Distinct from
    //    Program.cs's IDE0051 case, which is a member that is never touched at
    //    all — this one looks live until you follow it.
    private readonly int _neverRead;

    // 4. `null` into a non-nullable string. Without <Nullable>enable</Nullable>
    //    this compiles silently and every caller of Compute() below inherits a
    //    NullReferenceException that the type system said could not happen.
    private readonly string _label = null;

    public Escalations(int seed) => _neverRead = seed;

    // 3. `factor` is never used — a signature that lies about what it needs.
    public int Compute(int factor) => _label.Length;
}
