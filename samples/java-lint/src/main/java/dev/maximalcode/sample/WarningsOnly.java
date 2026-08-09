package dev.maximalcode.sample;

/**
 * Error Prone at WARNING severity, alone. Nothing here is an ERROR-severity
 * finding, so this file is what makes the {@code -Werror} ablation in ci.yml
 * mean something: strip {@code -Werror} and this fixture goes GREEN, which is
 * the only way to show that flag is what gates Error Prone's warning tier
 * rather than the ERROR tier doing it silently.
 *
 * <p>It also demonstrates the suppression documented in
 * configs/java/pom-lints.xml from the reporting side: with {@link JavacLint}
 * compiled alongside it, this finding is NOT REPORTED AT ALL, because a javac
 * lint warning ends the compile before Error Prone's pass ever runs.
 */
public final class WarningsOnly {

    private WarningsOnly() {}

    static boolean sameLabel(String left, String right) {
        return left == right;
    }
}
