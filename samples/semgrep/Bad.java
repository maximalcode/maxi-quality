/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Layer 2 sample: bait for the semgrep/ ruleset. Deliberately kept OUT of the
 * samples/java project so that adding Semgrep bait here never changes the
 * analyzer sample's expected finding count.
 *
 * This file is never compiled — Semgrep only parses it. It does not even sit in
 * a Maven source root, which is why it can carry imports that resolve to
 * nothing.
 *
 * WHAT IS NOT HERE, AND WHY. Three conventions are covered by Error Prone
 * instead, measured 2026-08-09 rather than assumed, so a Semgrep rule for them
 * would be a second finding on one line rather than more coverage:
 *
 *   catch-and-swallow          -> [EmptyCatch], on by default
 *   new Date()                 -> [JavaUtilDate], on by default
 *   LocalDate/LocalDateTime.now() -> [JavaTimeDefaultTimeZone], on by default
 *
 * The ambient-clock rule below is scoped to exactly the two shapes Error Prone
 * does NOT reach — Instant.now() is zone-independent so JavaTimeDefaultTimeZone
 * allows it, and System.currentTimeMillis() has no check at all.
 */
package dev.maximalcode.semgrepsample;

import java.math.BigDecimal;
import java.security.MessageDigest;
import java.sql.Connection;
import java.time.Instant;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import javax.crypto.Cipher;
import org.springframework.jdbc.core.simple.JdbcClient;
import reactor.core.publisher.Mono;

public final class Bad {

    private Bad() {}

    // --- no-float-for-money-java -------------------------------------------
    public static class Invoice {
        double totalAmount;
        float discountAmount;

        // NOT flagged: BigDecimal is the right type.
        BigDecimal netTotal;
    }

    // --- hardcoded-secret-java ---------------------------------------------
    private static final String API_TOKEN = "ghp_A1b2C3d4E5f6G7h8I9j0";
    // A URL is exempt, but NOT when it carries userinfo — same pair as Bad.cs.
    private static final String CONNECTION_STRING = "postgres://admin:hunter2is@db.internal:5432/prod";

    // Negative controls for #17 — these must stay SILENT.
    private static final String TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token";
    private static final String TOKEN_NONE = "none";

    // --- todo-without-issue -------------------------------------------------
    // TODO: switch this over to the new pricing service
    // TODO(#918): this one is fine — it has an issue and must NOT be flagged

    // --- no-ambient-clock-java ----------------------------------------------
    public static boolean isExpired(Instant expiresAt) {
        return expiresAt.isBefore(Instant.now());
    }

    public static long stamp() {
        return System.currentTimeMillis();
    }

    // --- no-float-for-money-java (parameter) --------------------------------
    public static double applyTax(double amount) {
        return amount * 1.19;
    }

    // --- weak-crypto-java ---------------------------------------------------
    public static MessageDigest fingerprint() throws Exception {
        return MessageDigest.getInstance("MD5");
    }

    // Case-insensitivity and the real DES spellings, the same evasions the
    // TypeScript rule was caught missing.
    public static MessageDigest fingerprintUpper() throws Exception {
        return MessageDigest.getInstance("SHA-1");
    }

    public static Cipher legacyCipher() throws Exception {
        return Cipher.getInstance("DESede/CBC/PKCS5Padding");
    }

    // NEGATIVE CONTROL for weak-crypto-java — must stay silent.
    public static MessageDigest strongFingerprint() throws Exception {
        return MessageDigest.getInstance("SHA-256");
    }

    // --- sql-string-concat-java ---------------------------------------------
    public static void findUser(JdbcClient jdbc, String id) {
        jdbc.sql("SELECT * FROM users WHERE id = " + id).query();
    }

    public static void findUserTemplate(org.springframework.jdbc.core.JdbcTemplate t, String id) {
        t.query("SELECT * FROM users WHERE id = " + id, (rs, n) -> null);
    }

    public static void deleteUser(org.springframework.jdbc.core.JdbcTemplate t, String id) {
        t.update("DELETE FROM users WHERE id = " + id);
    }

    public static void executeRaw(Connection conn, String id) throws Exception {
        conn.createStatement().executeQuery("SELECT * FROM users WHERE id = " + id);
    }

    // NEGATIVE CONTROL for the SQL group. A bound parameter must NOT fire, or
    // the rule is "any query call" and gets switched off.
    public static void findUserSafe(JdbcClient jdbc, String id) {
        jdbc.sql("SELECT * FROM users WHERE id = :id").param("id", id).query();
    }

    // --- command-injection-java ---------------------------------------------
    public static Process archive(String path) throws Exception {
        return Runtime.getRuntime().exec("tar -czf backup.tgz " + path);
    }

    public static Process archiveBuilder(String path) throws Exception {
        return new ProcessBuilder("sh", "-c", "tar -czf backup.tgz " + path).start();
    }

    // NEGATIVE CONTROL: an argument array is the fix the message asks for.
    public static Process archiveSafe(String path) throws Exception {
        return new ProcessBuilder("tar", "-czf", "backup.tgz", path).start();
    }

    // --- sync-over-async-java -----------------------------------------------
    // The receiver names are load-bearing: join()/get() are guarded by a name
    // heuristic because Optional.get() and Map.get() are everywhere. Both
    // branches of that guard are baited.
    public static String loadBlocking(CompletableFuture<String> resultFuture) {
        return resultFuture.join();
    }

    public static String loadBlockingGet(CompletableFuture<String> resultFuture) throws Exception {
        return resultFuture.get();
    }

    // The Reactor branch, which carries NO name guard — block() exists on Mono
    // and Flux and essentially nowhere else. Named `m` on purpose, so this
    // fixture fails if somebody "tidies up" by folding the two branches back
    // into one name-guarded pattern.
    public static String loadBlockingReactive(Mono<String> m) {
        return m.block();
    }

    // NEGATIVE CONTROL — Optional.get() is not blocking on anything, and is
    // why the name guard exists at all. Must stay SILENT.
    public static String unwrap(Optional<String> maybe) {
        return maybe.get();
    }

    // --- debug-print-left-behind-java ---------------------------------------
    public static void trace(String message) {
        System.out.println(message);
    }

    public static void traceErr(String message) {
        System.err.println(message);
    }

    public static void traceStack(Exception e) {
        e.printStackTrace();
    }
}
