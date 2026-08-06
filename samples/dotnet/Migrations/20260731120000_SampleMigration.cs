// Proof for #24 — an EF Core migration scaffold, in the shape and location EF
// actually generates them (`Migrations/<timestamp>_Name.cs`, NOT `*.Designer.cs`).
//
// This file is the ONE sample in the repo that must NOT produce a finding.
// Everything below is a deliberate style violation:
//
//   * two unnecessary usings          -> IDE0005, escalated to error in [*.cs]
//   * block-scoped namespace          -> IDE0161, via csharp_style_namespace_declarations
//   * constant array as argument      -> CA1861, silenced here by #56
//
// CA1861 is a PERFORMANCE id, not style, so the section's category-Style line
// never covered it — Consumer A measured 28× CA1861 (plus 2× CA1859), all
// inside EF scaffolds, and every future `dotnet ef migrations add` would
// regenerate the violation. Both ids are silenced in the section; only CA1861
// is baited here. CA1859 is NOT baited on purpose: measured 2026-08-06, the
// interface-return shape does not fire it even forced to `warning` without
// EF's own types in play, and pulling in Microsoft.EntityFrameworkCore to
// prove a severity line is the dependency this file already refuses above.
//
// If the `[**/Migrations/*.cs]` section in the .editorconfig regresses, this
// file grows findings, the manifest diff fails, and CI goes red. That is the
// test.
//
// It does not inherit from EF's `Migration` base type on purpose — pulling in
// Microsoft.EntityFrameworkCore just to prove a path glob would add a NuGet
// dependency to a project whose whole point is having almost none. The
// editorconfig matches on the path, not the base type.

using System;
using System.Text;

namespace Maximalcode.Sample.Migrations
{
    internal static class SampleMigration
    {
        internal const string Up =
            "ALTER TABLE issues ADD COLUMN archived boolean NOT NULL DEFAULT false;";

        internal const string Down =
            "ALTER TABLE issues DROP COLUMN archived;";

        // CA1861 bait — a constant array as an argument, the shape EF puts in
        // every scaffolded Index/PrimaryKey call. MUST BE SILENT here. The
        // callee takes string[] (not params) on purpose: a params overload
        // would fire Sonar's S3878 instead, which is NOT waived here — the
        // bait has to isolate the rule it is baiting.
        internal static string ColumnList() =>
            Quote(new[] { "archived", "updated_at" });

        private static string Quote(string[] columns) =>
            string.Join(", ", columns);
    }
}
