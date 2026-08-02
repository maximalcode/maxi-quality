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
 */

namespace Maximalcode.Sample.Clean;

internal sealed class UserService
{
    // 1. Read by CacheKey below, so it is state rather than dead weight.
    private readonly string _cacheKey = "users:all";

    public string CacheKey => _cacheKey;

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
