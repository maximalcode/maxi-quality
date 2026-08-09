package dev.maximalcode.sample;

/**
 * TIER 3 — Error Prone's ON_BY_DEFAULT **WARNING** checks. These gate ONLY
 * because {@code -Werror} is in the compiler args, and that is the whole reason
 * this file is separate from {@link ErrorProneErrors}: drop {@code -Werror} and
 * the errors keep failing the build while these go silent, so a fixture that
 * mixed the two would still look like it was working.
 *
 * <p>Note the corollary, learned the hard way (configs/java/pom-lints.xml): an
 * ERROR-severity finding aborts the compile before javac emits its
 * "warnings found and -Werror specified" summary, so the ablation that proves
 * -Werror is live has to run against warnings ALONE.
 */
public final class ErrorProneWarnings {

    private ErrorProneWarnings() {}

    /** ReferenceEquality — == on boxed values compares identity, not value. */
    static boolean sameLabel(String left, String right) {
        return left == right;
    }

    /** OperatorPrecedence — the grouping the author meant is not the one javac reads. */
    static boolean confusing(boolean a, boolean b, boolean c) {
        return a && b || c;
    }
}
