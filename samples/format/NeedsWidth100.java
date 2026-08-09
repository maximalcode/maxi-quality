package dev.maximalcode.sample;

/**
 * THE WIDTH ABLATION for the Java formatter (CONCEPT §4a), and the only setting
 * in the spotless block that is not a tool default.
 *
 * <p>palantir-java-format ships the PALANTIR style, which wraps at 120.
 * configs/java/pom-lints.xml asks for AOSP, which wraps at 100 — the width
 * configs/editorconfig already declares for every language, so the formatter
 * and the editor agree instead of fighting.
 *
 * <p>This file is formatted correctly under AOSP and INCORRECTLY under the
 * default, because the call below joins onto a single 101-120 character line at
 * 120 columns. Delete <style>AOSP</style> and the check flips. If the line ever
 * drifts under 101 characters the ablation silently stops separating anything,
 * which is why ci.yml asserts BOTH verdicts rather than just the passing one.
 *
 * <p>Never compiled by any gate — it is copied into a fixture project for the
 * ablation and nowhere else.
 */
public final class NeedsWidth100 {

    private NeedsWidth100() {}

    static String describe(String alpha, String bravo, String charlie, String delta) {
        return String.join(
                "-", alpha.trim(), bravo.trim(), charlie.trim(), delta.trim(), "a-suffix-here");
    }
}
