package dev.maximalcode.sample;

import java.util.Arrays;

/**
 * TIER 2 — Error Prone's ON_BY_DEFAULT ERROR checks. These are the ones that
 * fail a build without any severity escalation at all, so they prove Error Prone
 * is LOADED. If this file goes quiet, the {@code -Xplugin:ErrorProne} arg or the
 * annotationProcessorPath is gone and every other tier is meaningless.
 */
public final class ErrorProneErrors {

    private ErrorProneErrors() {}

    /** ArrayEquals — reference equality on arrays, never what the author meant. */
    static boolean sameContents(int[] left, int[] right) {
        return left.equals(right);
    }

    /** SelfAssignment — assigning a field to itself. */
    static String describe(String label) {
        label = label;
        return label;
    }

    /** ReturnValueIgnored — Arrays.asList has no side effect to keep. */
    static void pointless(String first, String second) {
        Arrays.asList(first, second);
    }
}
