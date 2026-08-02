// Proof for #25 — the test-project relaxation.
//
// Two-sided assertion, and both sides matter:
//
//   WAIVED  (must be SILENT)  S1199, CA1822, S2325 — real test idioms
//   NOT WAIVED (must FIRE)    unread private state — a dead fixture is a defect
//
// A relaxation that quietly swallowed the second group would be buying quiet
// with coverage, which is the thing this whole repo exists to not do.

namespace Maximalcode.Sample.Tests;

internal sealed class TestIdioms
{
    // MUST FIRE. An unread private field is a dead fixture — the most common
    // way a test stops testing anything without anyone noticing. Deliberately
    // NOT in the NoWarn list, and this line is what proves that.
    private readonly string _deadFixture = "nothing ever reads me";

    // MUST BE SILENT — CA1822 and S2325 both want this marked `static` because
    // it touches no instance state. Nearly every test method looks like this.
    public void ExpiredInviteIsRejected()
    {
        // MUST BE SILENT — S1199 flags the bare nested block. Arrange/act/assert
        // written with real braces is a deliberate, readable style.
        {
            var expiry = "2020-01-01";
            AssertNotEmpty(expiry);
        }
    }

    // Also silent under CA1822/S2325 for the same reason.
    public void AssertNotEmpty(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            throw new InvalidOperationException("expected a value");
        }
    }
}
