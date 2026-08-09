package dev.maximalcode.sample;

import org.jspecify.annotations.Nullable;

/**
 * TIER 4 — NullAway. Every finding here disappears if the
 * {@code -Xep:NullAway:ERROR} flag is dropped (NullAway defaults to WARNING) or
 * if {@code AnnotatedPackages} stops matching this package. Both failures are
 * completely silent, which is why they are baited rather than trusted.
 */
public final class NullSafety {

    private NullSafety() {}

    @Nullable
    static String maybeName(boolean present) {
        return present ? "widget" : null;
    }

    /** Dereferences a @Nullable return without checking it. */
    static int nameLength(boolean present) {
        String name = maybeName(present);
        return name.length();
    }

    /** Returns null from a method NullAway treats as non-null. */
    static String alwaysAName() {
        return null;
    }

    /** Passes null into a parameter NullAway treats as non-null. */
    static int lengthOfNothing() {
        return lengthOf(null);
    }

    static int lengthOf(String value) {
        return value.length();
    }
}
