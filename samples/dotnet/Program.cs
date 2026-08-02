/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * This file is the test suite for configs/dotnet. Every member below is a
 * planted bug that the baseline must catch. If `dotnet build` ever succeeds
 * here, the config regressed — fix the config, not this file.
 *
 * Planted findings and the diagnostic that must fire:
 *   1. unused private field           IDE0052 / S1144
 *   2. culture-insensitive comparison CA1304 / CA1311 / CA1862 / CA1310
 *   3. un-disposed IDisposable        CA2000
 *   4. unreachable (dead) code        CS0162
 *   5. unused local variable          CS0219 / IDE0059
 */

namespace Maximalcode.Sample;

internal sealed class UserService
{
    // 1. Assigned in the initializer, never read again. Either a forgotten
    //    feature or dead weight — both worth failing a build over.
    private readonly string _unusedCacheKey = "users:all";

    // 2. ToLower() uses the current culture. In Turkish, 'I'.ToLower() is 'ı',
    //    so this authorisation check silently changes behaviour by locale.
    public static bool IsAdmin(string role) => role.ToLower() == "admin";

    // 2b. StartsWith with no StringComparison — same class of bug.
    public static bool IsInternal(string email) => email.StartsWith("internal@");

    // 3. The StreamReader is never disposed; the file handle leaks. On an
    //    exception path it leaks even in the happy case.
    public static int CountLines(string path)
    {
        StreamReader reader = new(path);
        int count = 0;
        while (reader.ReadLine() is not null)
        {
            count++;
        }

        return count;
    }

    // 4. Dead code after an unconditional return.
    public static string Classify(int value)
    {
        if (value > 0)
        {
            return "positive";
        }

        return "non-positive";
        return "unreachable";
    }
}

internal static class Program
{
    public static void Main()
    {
        // 5. Assigned and never used.
        int unusedTotal = 42;

        Console.WriteLine(UserService.IsAdmin("Admin"));
    }
}
