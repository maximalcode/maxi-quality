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
