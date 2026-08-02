// Proof for #24 — an EF Core migration scaffold, in the shape and location EF
// actually generates them (`Migrations/<timestamp>_Name.cs`, NOT `*.Designer.cs`).
//
// This file is the ONE sample in the repo that must NOT produce a finding.
// Everything below is a deliberate style violation:
//
//   * two unnecessary usings          -> IDE0005, escalated to error in [*.cs]
//   * block-scoped namespace          -> IDE0161, via csharp_style_namespace_declarations
//
// If the `[**/Migrations/*.cs]` section in the .editorconfig regresses, the
// sample's error count moves off 13 and CI fails. That is the test.
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
    }
}
