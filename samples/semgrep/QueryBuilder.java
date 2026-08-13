/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * The away-from-the-sink half of two conventions, and the duplication controls
 * that keep each line to ONE rule id. Same job as QueryBuilder.cs and
 * query-builder.ts; see samples/semgrep/README.md.
 *
 * Never compiled — Semgrep only parses it.
 */
package dev.maximalcode.semgrepsample;

public final class QueryBuilder {

    private QueryBuilder() {}

    // --- sql-string-concat-builder-java: MUST FIRE -------------------------
    // The dynamic WHERE clause, which is how this bug is actually written in
    // Java. No sink pattern can see it: the sink receives a variable.
    public static String usersMatching(String name) {
        StringBuilder sqlBuilder = new StringBuilder("SELECT * FROM users WHERE 1=1");
        sqlBuilder.append(" AND name = '").append(name).append("'");
        return sqlBuilder.toString();
    }

    // NEGATIVE CONTROL — appending a PLACEHOLDER is the fix the message asks
    // for, and must stay SILENT. Without this the rule is "any append on a
    // variable with sql in its name", which is a rule against StringBuilder.
    public static String usersMatchingSafe() {
        StringBuilder sqlBuilder = new StringBuilder("SELECT * FROM users WHERE 1=1");
        sqlBuilder.append(" AND name = ?");
        return sqlBuilder.toString();
    }

    // --- command-injection-indirect-java: MUST FIRE ------------------------
    // Bound to a local one line above the sink, which silences every pattern
    // rule. Taint crosses the binding.
    public static Process archive(String path) throws Exception {
        String cmd = "tar -czf backup.tgz " + path;
        return Runtime.getRuntime().exec(cmd);
    }

    // DUPLICATION CONTROL. The inline form belongs to command-injection-java
    // and must be reported EXACTLY ONCE — the taint rule's sink is restricted
    // to a bare identifier so it cannot claim this line too. A second finding
    // here means that restriction is gone, and the manifest fails the same way
    // a missing finding does.
    public static Process archiveInline(String path) throws Exception {
        return Runtime.getRuntime().exec("tar -czf backup.tgz " + path);
    }

    // THE KNOWN GAP, and it is expected to stay SILENT. Semgrep OSS taint is
    // intraprocedural: it crosses a local binding, not a function call. This
    // sits with the working bait rather than in a -clean fixture because it is
    // not clean code — it is a documented limit, and the day a semgrep release
    // closes it the manifest is what says so.
    public static Process archiveViaHelper(String path) throws Exception {
        return Runtime.getRuntime().exec(buildCommand(path));
    }

    private static String buildCommand(String path) {
        return "tar -czf backup.tgz " + path;
    }
}
