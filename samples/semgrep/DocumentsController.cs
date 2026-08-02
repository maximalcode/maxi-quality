/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Bait for the FRAMEWORK branches of
 * no-permission-denied-for-invisible-resource-dotnet.
 *
 * The rule lists six shapes; UserService.cs baited exactly one of them, the
 * gRPC `throw new RpcException(StatusCode.PermissionDenied, ...)` after an
 * `is null`. The other five — the `== null` spelling, and the three ASP.NET
 * results a controller actually returns — had no fixture at all, so each could
 * have stopped matching without changing a single count.
 *
 * A separate file rather than more methods on UserService, because
 * mutation-requires-authz-dotnet includes only *Service.cs / *Handler.cs, and
 * a controller is where this idiom really lives.
 *
 * This file is never compiled — Semgrep only parses it.
 */

using System;

namespace Maximalcode.SemgrepSample;

public sealed class DocumentsController : ControllerBase
{
    // FLAGGED: the `== null` spelling of the branch UserService.cs covers with
    // `is null`. Two AST shapes, two patterns, and only one had bait.
    public string GetByRpc(string? found)
    {
        if (found == null)
        {
            throw new RpcException(StatusCode.PermissionDenied, "Forbidden");
        }

        return found;
    }

    // FLAGGED: Forbid() after a not-found check, both null spellings.
    public IActionResult GetForbidIsNull(string? found)
    {
        if (found is null)
        {
            return Forbid();
        }

        return Ok(found);
    }

    public IActionResult GetForbidEqNull(string? found)
    {
        if (found == null)
        {
            return Forbid();
        }

        return Ok(found);
    }

    // FLAGGED: the raw status-code form.
    public IActionResult GetStatus403(string? found)
    {
        if (found is null)
        {
            return StatusCode(403, "Forbidden");
        }

        return Ok(found);
    }

    // FLAGGED: Unauthorized() — a 401, and just as much of an oracle, which is
    // why the rule lists it.
    public IActionResult GetUnauthorized(string? found)
    {
        if (found == null)
        {
            return Unauthorized();
        }

        return Ok(found);
    }

    // NEGATIVE CONTROL. Returning NotFound() is the fix the message asks for and
    // must NOT fire, or the rule flags every null check in every controller and
    // gets switched off within a week.
    public IActionResult GetNotFound(string? found)
    {
        if (found is null)
        {
            return NotFound();
        }

        return Ok(found);
    }
}

// Minimal stand-ins so the file parses without ASP.NET Core.
public interface IActionResult
{
}

public abstract class ControllerBase
{
    protected IActionResult Forbid() => throw new NotImplementedException();

    protected IActionResult Unauthorized() => throw new NotImplementedException();

    protected IActionResult NotFound() => throw new NotImplementedException();

    protected IActionResult Ok(object? value) => throw new NotImplementedException();

    protected IActionResult StatusCode(int code, object? value) =>
        throw new NotImplementedException();
}
