/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Layer 2 sample: bait for the semgrep/ ruleset. Deliberately kept OUT of the
 * samples/dotnet project so that adding Semgrep bait here never changes the
 * analyzer sample's expected error count.
 *
 * This file is never compiled — Semgrep only parses it.
 */

using System;
using System.Data;
using System.Data.SqlClient;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Threading.Tasks;

namespace Maximalcode.SemgrepSample;

// --- no-float-for-money ----------------------------------------------------
public sealed class Invoice
{
    public double TotalAmount { get; set; }

    public float DiscountAmount { get; set; }

    // NOT flagged: decimal is the right type.
    public decimal NetTotal { get; set; }
}

public static class Billing
{
    // --- hardcoded-secret-dotnet -------------------------------------------
    private const string ApiToken = "ghp_A1b2C3d4E5f6G7h8I9j0";
    // A URL is exempt, but NOT when it carries userinfo — see bad.ts.
    private const string ConnectionString = "postgres://admin:hunter2is@db.internal:5432/prod";

    // Negative controls for #17 — these must stay SILENT.
    private const string TokenEndpoint = "https://oauth2.googleapis.com/token";
    private const string TokenNone = "none";

    // --- todo-without-issue ------------------------------------------------
    // TODO: switch this over to the new pricing service
    // TODO(#918): this one is fine — it has an issue and must NOT be flagged

    // --- no-ambient-clock (cross-language proof rule, C# side) -------------
    public static bool IsExpired(DateTime expiresAt) => expiresAt < DateTime.UtcNow;

    // --- no-float-for-money (parameter) ------------------------------------
    public static double ApplyTax(double amount) => amount * 1.19;

    // --- weak-crypto -------------------------------------------------------
    public static byte[] Fingerprint(byte[] body)
    {
        using MD5 hasher = MD5.Create();
        return hasher.ComputeHash(body);
    }

    // --- sql-string-concat-dotnet ------------------------------------------
    public static SqlCommand FindUser(string id)
    {
        return new SqlCommand($"SELECT * FROM Users WHERE Id = '{id}'");
    }

    // The CONCATENATION form of the same constructor. Interpolation had bait;
    // concatenation did not, and they are separate patterns.
    public static SqlCommand FindUserConcat(string id)
    {
        return new SqlCommand("SELECT * FROM Users WHERE Id = " + id);
    }

    // The Dapper / CommandText group: five entry points advertised by the rule,
    // and not one of them had a fixture. Both regex branches are exercised
    // across them — concatenation and interpolation are matched by different
    // expressions over raw source text, so covering one says nothing about the
    // other.
    public static void QueryUsers(IDbConnection conn, string id)
    {
        conn.Query("SELECT * FROM Users WHERE Id = " + id);
    }

    public static Task QueryUsersAsync(IDbConnection conn, string id)
    {
        return conn.QueryAsync($"SELECT * FROM Users WHERE Id = '{id}'");
    }

    public static void DeleteUser(IDbConnection conn, string id)
    {
        conn.Execute("DELETE FROM Users WHERE Id = " + id);
    }

    public static Task DeleteUserAsync(IDbConnection conn, string id)
    {
        return conn.ExecuteAsync($"DELETE FROM Users WHERE Id = '{id}'");
    }

    public static void SetCommandText(SqlCommand cmd, string id)
    {
        cmd.CommandText = "SELECT * FROM Users WHERE Id = " + id;
    }

    // NEGATIVE CONTROL for the Dapper group. A parameterised call must NOT
    // fire, or the rule is "any Query call" and gets switched off.
    public static void QueryUsersSafe(IDbConnection conn, string id)
    {
        conn.Query("SELECT * FROM Users WHERE Id = @id", new { id });
    }

    // --- command-injection-dotnet -----------------------------------------
    public static void Archive(string path)
    {
        Process.Start($"tar -czf backup.tgz {path}");
    }

    // --- sync-over-async ---------------------------------------------------
    public static string LoadBlocking(Task<string> work)
    {
        return work.GetAwaiter().GetResult();
    }

    // --- catch-and-swallow-dotnet -----------------------------------------
    public static void TryFlush(Action flush)
    {
        try
        {
            flush();
        }
        catch (Exception ex)
        {
        }
    }

    // The other two branches. `catch { }`, `catch (T e) { }` and `catch (T) { }`
    // are three separate AST shapes and the rule spells out all three — but
    // only the bound form had bait, and the bare form was "covered" solely by
    // the negative control below, which proves the escape hatch works and
    // nothing about the branch still matching.
    public static void TryFlushBare(Action flush)
    {
        try
        {
            flush();
        }
        catch
        {
        }
    }

    public static void TryFlushTyped(Action flush)
    {
        try
        {
            flush();
        }
        catch (InvalidOperationException)
        {
        }
    }

    // NEGATIVE CONTROL for catch-and-swallow-dotnet. This one must NOT fire.
    // See the matching note in bad.ts — the comment escape hatch the message
    // promises did not work until 2026-07-31. Kept in the BAD sample so the
    // existing finding assertion doubles as the regression test.
    public static void TryDispose(IDisposable resource)
    {
        try
        {
            resource.Dispose();
        }
        catch
        {
            // Disposal failures are not actionable here; the object is going away regardless.
        }
    }

    // The exception-filter form. C# lets a catch carry a `when (...)` clause
    // between the type and the block, and that clause is source text the
    // `pattern-not-regex` has to step over — until 2026-08-02 it did not, so a
    // FILTERED catch could not be cleared by the comment the message asks for
    // even though an unfiltered one could. The same bug as 2026-07-31, one
    // syntax further along, and found the same way: measuring against
    // Consumer A.
    //
    // Both halves are planted, per the lesson above the bare form: a negative
    // control on its own proves the escape hatch works and nothing about
    // whether the branch still matches. This one must FIRE.
    public static void TryFlushFiltered(Action flush)
    {
        try
        {
            flush();
        }
        catch (InvalidOperationException e) when (e.Message.Length > 0)
        {
        }
    }

    // NEGATIVE CONTROL for the filter form. This one must NOT fire.
    public static void TryDisposeFiltered(IDisposable resource)
    {
        try
        {
            resource.Dispose();
        }
        catch (InvalidOperationException e) when (e.Message.Length > 0)
        {
            // Disposal races on a shared handle are expected; the object is going away regardless.
        }
    }

    // --- debug-print-left-behind-dotnet -----------------------------------
    public static void Trace(string message)
    {
        Debug.WriteLine(message);
    }
}
