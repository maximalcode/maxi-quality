// Proof for #56 item 4 — the test-path IDE1006 relaxation.
//
// This file lives under tests/ ON PURPOSE: the `[{tests,**/tests}/**.cs]`
// section in the .editorconfig only matches on path, and this is the path.
// Consumer A measured 333 IDE1006 hits in its test fixtures, every one the
// field shape below.
//
// MUST BE SILENT. The same field one directory up — or in samples/dotnet's
// Naming.cs, which is the positive control — is an IDE1006 error. If this
// file starts failing, the tests glob regressed; fix the config, do not
// rename the field.

namespace Maximalcode.Sample.Tests.Fixtures;

internal sealed class FixtureNaming
{
    // The un-prefixed `private readonly` fixture field, read so that only the
    // naming rule could possibly object to it.
    private readonly string connection = "Host=localhost;Database=app";

    public string Connection => connection;
}
