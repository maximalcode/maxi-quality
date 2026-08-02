/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Bait for mutation-requires-authz-dotnet and
 * no-permission-denied-for-invisible-resource-dotnet. The former only applies to
 * files matching *Service.cs / *Handler.cs — hence the filename.
 *
 * This file is never compiled — Semgrep only parses it.
 */

using System;
using System.Threading.Tasks;

namespace Maximalcode.SemgrepSample;

public interface IAuthz
{
    void Require(string permission);

    void Authorize(string permission);

    Task RequireAsync(string permission);

    Task AuthorizeAsync(string permission);
}

public interface IUserRepo
{
    Task DeleteAsync(string id);

    Task UpdateAsync(string id, string name);

    Task<string?> FindAsync(string id);
}

public sealed class UserService
{
    private readonly IAuthz _authz;
    private readonly IUserRepo _repo;

    public UserService(IAuthz authz, IUserRepo repo)
    {
        _authz = authz;
        _repo = repo;
    }

    // FLAGGED (mutation-requires-authz-dotnet): mutation with no authz gate.
    public Task DeleteUser(string id)
    {
        return _repo.DeleteAsync(id);
    }

    // FLAGGED: same.
    public Task UpdateUser(string id, string name)
    {
        return _repo.UpdateAsync(id, name);
    }

    // NOT flagged: gated correctly. Proves the rule is not just matching on name.
    public Task CreateUser(string name)
    {
        _authz.Require("user.create");
        return _repo.UpdateAsync("new", name);
    }

    // The other three exemptions. The rule offers four escape hatches and only
    // Require had a fixture, so three of them could have stopped matching with
    // CI green — and the "no rule change needed" call for a consuming project
    // rested specifically on AuthorizeAsync still matching.
    //
    // These are NEGATIVE controls: each method name matches the mutation regex,
    // so if its exemption breaks the file gains a finding it is not supposed to
    // have and the manifest reports it as UNEXPECTED. No extra assertion is
    // needed — the existing one IS the test.
    public Task UpdateProfile(string id, string name)
    {
        _authz.Authorize("user.update");
        return _repo.UpdateAsync(id, name);
    }

    public async Task RemoveUser(string id)
    {
        await _authz.RequireAsync("user.delete");
        await _repo.DeleteAsync(id);
    }

    public async Task GrantRole(string id, string role)
    {
        await _authz.AuthorizeAsync("user.grant");
        await _repo.UpdateAsync(id, role);
    }

    // FLAGGED (no-permission-denied-for-invisible-resource-dotnet):
    // 403 after a not-found check leaks that the user exists.
    public string GetUser(string? found)
    {
        if (found is null)
        {
            throw new RpcException(StatusCode.PermissionDenied, "Forbidden");
        }

        return found;
    }
}

// Minimal stand-ins so the file parses without the gRPC package.
public enum StatusCode
{
    PermissionDenied,
    NotFound,
}

public sealed class RpcException : Exception
{
    public RpcException(StatusCode code, string message)
        : base(message) => Code = code;

    public StatusCode Code { get; }
}
