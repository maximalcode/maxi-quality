namespace Sample.ParseErrors;

// THE CONTROL. Ordinary C# that semgrep parses fine, carrying exactly one
// planted violation (`debug-print-left-behind-dotnet`).
//
// Its job is to prove the scan was REAL. Without it, "1 unparsed file, gate
// clean" is indistinguishable from "semgrep fell over and reported nothing" —
// and a clean gate over a scan that never happened is the failure this whole
// repo is organised around.
public static class Reporter
{
    public static void Report(string message)
    {
        Console.WriteLine(message);
    }
}
