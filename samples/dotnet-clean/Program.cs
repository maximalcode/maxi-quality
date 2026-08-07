/*
 * DELIBERATELY CLEAN CODE — `dotnet build` MUST SUCCEED, 0 errors, 0 warnings.
 *
 * This file is the negative control for configs/dotnet. Every member is the
 * correct counterpart of a planted bug in ../dotnet/Program.cs, written the way
 * the baseline wants it. Until this file existed, "clean C# passes with zero
 * findings" was asserted in the docs and never tested.
 *
 * If this file starts FAILING, the baseline has become over-strict — fix the
 * config. Do not add #pragma warning disable or NoWarn entries here; a
 * suppression would defeat the entire point of the fixture.
 *
 * Counterpart map (bad Program.cs finding -> the fix below):
 *   1. unused private field           -> the field is actually read
 *   2. culture-insensitive comparison -> explicit StringComparison.Ordinal
 *   3. un-disposed IDisposable        -> `using` declaration
 *   4. unreachable code               -> removed
 *   5. unused local                   -> the value is used
 *
 * Since #56 it is also the negative control for three RELAXATIONS, which a
 * clean fixture is the only way to prove — a relaxation regressing shows up as
 * this file failing, not as a bad sample passing:
 *   6. PascalCase private const / static readonly -> silent (narrower naming
 *      rules; the underscore rule must no longer catch them)
 *   7. sealed single-ctor domain exception        -> silent (RCS1194 = none)
 */

namespace Maximalcode.Sample.Clean;

// 7. The exception shape Consumer A measured 55 of: sealed, one constructor
//    that says what it needs, nothing else. RCS1194 wants three more ctors;
//    the baseline now says no. Public because Sonar's S3871 (rightly) insists
//    exception types be visible to their catchers.
public sealed class MissingRoleException : Exception
{
    public MissingRoleException(string role)
        : base($"required role is missing: {role}")
    {
    }
}

internal sealed class UserService
{
    // 6. PascalCase by .NET convention for const and static readonly — the
    //    narrower naming rules added by #56 must leave both alone. Before
    //    that change, each of these was an IDE1006 error.
    private const string CachePrefix = "users:";

    private static readonly TimeSpan CacheTtl = TimeSpan.FromMinutes(5);

    // 1. Read by CacheKey below, so it is state rather than dead weight.
    private readonly string _cacheKey = CachePrefix + "all";

    public string CacheKey => _cacheKey;

    // 6 (cont.) Both fields are read, so IDE0052/S4487 stay out of the way and
    // the only rule these could trip is the naming rule under test.
    public static double CacheSeconds => CacheTtl.TotalSeconds;

    // 7 (cont.) The exception is thrown on a real path, so the type is live
    //    code rather than fixture furniture.
    public static string RequireRole(string? role) =>
        role ?? throw new MissingRoleException("admin");

    // 2. Ordinal comparison. Locale can no longer change an authorisation
    //    decision — the Turkish dotless-i problem cannot occur here.
    public static bool IsAdmin(string role) =>
        string.Equals(role, "admin", StringComparison.OrdinalIgnoreCase);

    // 2b. Same fix for the prefix check.
    public static bool IsInternal(string email) =>
        email.StartsWith("internal@", StringComparison.Ordinal);

    // 3. `using` declaration — the reader is disposed on every path, including
    //    exceptions.
    public static int CountLines(string path)
    {
        using StreamReader reader = new(path);
        int count = 0;
        while (reader.ReadLine() is not null)
        {
            count++;
        }

        return count;
    }

    // 4. Every branch returns; there is no code after the final return.
    public static string Classify(int value) => value > 0 ? "positive" : "non-positive";
}

internal static class Program
{
    public static void Main()
    {
        // 5. Declared and used.
        UserService service = new();
        int lines = 0;

        if (UserService.IsAdmin("Admin"))
        {
            lines = service.CacheKey.Length;
        }

        Console.WriteLine(UserService.Classify(lines));
    }
}
