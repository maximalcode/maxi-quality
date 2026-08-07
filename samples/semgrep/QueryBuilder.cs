// Bait for the "one step away from the sink" half of sql-string-concat and
// command-injection — see issue #20 and the rule comments in
// semgrep/security/. Every case here is silent under the sink-anchored rules
// and must fire under the builder/indirect ones.
//
// It is a separate file from Bad.cs on purpose: appending to Bad.cs would shift
// every line number below the insertion point in samples/expected/semgrep.json,
// and that churn is what hides a real regression in a large diff.
//
// Nothing here is compiled. Semgrep only parses it.
using System;
using System.Data;
using System.Data.SqlClient;
using System.Diagnostics;

public static class QueryBuilder
{
    // --- sql-string-concat-builder-dotnet ---------------------------------
    // One fixture per statement branch, rotated across both regex branches
    // (concatenation and interpolation) so neither can go quiet unobserved.

    // branch: `return $SQL;` — interpolation
    public static string ByIdInterpolated(string id)
    {
        return $"SELECT * FROM Users WHERE Id = '{id}'";
    }

    // branch: expression-bodied member — concatenation
    public static string ByIdConcat(string id) => "SELECT * FROM Users WHERE Id = " + id;

    // branch: typed declaration — concatenation. This is the shape that made
    // the gap worth closing: the sink is right there on the next line and the
    // sink-anchored rule sees nothing, because its argument is an identifier.
    public static void RunTyped(IDbConnection conn, string id)
    {
        string sql = "DELETE FROM Users WHERE Id = " + id;
        conn.Execute(sql);
    }

    // branch: `var` declaration — interpolation
    public static void RunVar(IDbConnection conn, string id)
    {
        var sql = $"UPDATE Users SET Active = 0 WHERE Id = '{id}'";
        conn.Execute(sql);
    }

    // branch: assignment to an existing field — concatenation
    private static string _lastQuery = string.Empty;

    public static void Remember(string id)
    {
        _lastQuery = "SELECT * FROM Users WHERE Id = " + id;
    }

    // DUPLICATION CONTROL. `cmd.CommandText = "..." + id` is a sink and
    // sql-string-concat-dotnet already owns it, so the assignment branch above
    // carries a pattern-not for it. Exactly ONE finding must land on this line;
    // two means the exclusion has gone.
    public static void SetCommandText(SqlCommand cmd, string id)
    {
        cmd.CommandText = "SELECT * FROM Users WHERE Id = " + id;
    }

    // DUPLICATION CONTROL for the `^` anchors. The concatenation here is the
    // sink's argument, so sql-string-concat-dotnet owns it; unanchored, the
    // builder rule would report the enclosing `return` a second time.
    public static SqlCommand ReturnSink(string id)
    {
        return new SqlCommand("SELECT * FROM Users WHERE Id = " + id);
    }

    // NEGATIVE CONTROLS. Concatenation is the commonest thing in any codebase,
    // so a builder rule that is not keyed on a SQL keyword is a rule against
    // string building. These must stay silent.
    public static string Greet(string name) => "Hello " + name;

    public static string Paragraph(string body)
    {
        return "<p>" + body + "</p>";
    }

    public static void Parameterised(IDbConnection conn, string id)
    {
        var sql = "SELECT * FROM Users WHERE Id = @id";
        conn.Query(sql, new { id });
    }

    // --- command-injection-indirect-dotnet --------------------------------
    // One fixture per sink branch. The source is the interpolation in every
    // case; unlike SQL there is no keyword to key on, which is why this half is
    // taint rather than a sink-free pattern.

    // branch: Process.Start($EXE, $CMD)
    public static void ArchiveTwoArg(string path)
    {
        var args = $"-czf backup.tgz {path}";
        Process.Start("tar", args);
    }

    // branch: Process.Start($CMD)
    public static void ArchiveOneArg(string path)
    {
        var cmd = $"tar -czf backup.tgz {path}";
        Process.Start(cmd);
    }

    // branch: $PSI.Arguments = $CMD
    public static void ArchiveViaPsi(string path)
    {
        var args = $"-czf backup.tgz {path}";
        var psi = new ProcessStartInfo("tar");
        psi.Arguments = args;
    }

    // DUPLICATION CONTROL. Inline interpolation at the sink belongs to
    // command-injection-dotnet, and the sink's metavariable-regex keeps this
    // rule off it. Exactly ONE finding on this line.
    public static void ArchiveInline(string path)
    {
        Process.Start("tar", $"-czf backup.tgz {path}");
    }

    // KNOWN GAP, kept visible on purpose. Semgrep OSS taint is intraprocedural,
    // so the helper form is NOT reachable and this line is silent. If a future
    // Semgrep makes it reachable, this comment is the thing to delete — but the
    // finding then has to be added to samples/expected/semgrep.json in the same
    // change, or the manifest fails.
    private static string BuildArgs(string path) => $"-czf backup.tgz {path}";

    public static void ArchiveViaHelper(string path)
    {
        Process.Start("tar", BuildArgs(path));
    }

    // NEGATIVE CONTROL. ArgumentList passes each argument separately, so no
    // shell ever parses it.
    public static void ArchiveSafe(string path)
    {
        var psi = new ProcessStartInfo("tar");
        psi.ArgumentList.Add("-czf");
        psi.ArgumentList.Add("backup.tgz");
        psi.ArgumentList.Add(path);
        Process.Start(psi);
    }
}
