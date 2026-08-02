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

    // --- debug-print-left-behind-dotnet -----------------------------------
    public static void Trace(string message)
    {
        Debug.WriteLine(message);
    }
}
