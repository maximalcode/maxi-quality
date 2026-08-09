/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * The two convention rules that key on FILE NAME need a file whose name they
 * match: mutation-requires-authz-java includes *Service.java and *Handler.java,
 * exactly as the C# and TypeScript twins do.
 *
 * Never compiled — Semgrep only parses it.
 */
package dev.maximalcode.semgrepsample;

import java.util.UUID;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.server.ResponseStatusException;

public class UserService {

    private Authz authz;
    private UserRepository users;

    // --- mutation-requires-authz-java: MUST FIRE ---------------------------
    public void deleteUser(UUID id) {
        users.delete(id);
    }

    public User updateUser(UUID id, String name) {
        return users.rename(id, name);
    }

    // NEGATIVE CONTROL 1 — the explicit gate call. Must stay SILENT.
    public void revokeAccess(UUID id) {
        authz.require("user:write");
        users.revoke(id);
    }

    // NEGATIVE CONTROL 2 — the Spring idiom. @PreAuthorize IS the authorisation
    // check in a Spring codebase, and a rule that does not know that fires on
    // every correctly-secured service in the repo. Must stay SILENT.
    @PreAuthorize("hasAuthority('user:write')")
    public void createUser(String name) {
        users.create(name);
    }

    // NEGATIVE CONTROL 3 — a READ is not a mutation. Must stay SILENT.
    public User getUser(UUID id) {
        return users.find(id);
    }

    // --- no-permission-denied-for-invisible-resource-java: MUST FIRE -------
    public User loadOrForbid(UUID id) {
        User found = users.find(id);
        if (found == null) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "not allowed");
        }
        return found;
    }

    public User loadOrDeny(UUID id) {
        User found = users.find(id);
        if (found == null) {
            throw new AccessDeniedException("not allowed");
        }
        return found;
    }

    // NEGATIVE CONTROL — 404 is the correct answer, and must stay SILENT.
    public User loadOrNotFound(UUID id) {
        User found = users.find(id);
        if (found == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "no such user");
        }
        return found;
    }
}
