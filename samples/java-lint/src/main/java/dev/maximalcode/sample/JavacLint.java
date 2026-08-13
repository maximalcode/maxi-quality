package dev.maximalcode.sample;

import java.util.ArrayList;
import java.util.List;

/**
 * TIER 1 — javac's own {@code -Xlint:all}. Error Prone can be loaded and working
 * while the compiler's own lint set is off, and nothing about the build output
 * says so. These findings come from javac rather than from any plugin, so they
 * are what proves the {@code -Xlint:all,-processing,-serial} arg survived.
 *
 * <p>The two exclusions are baited from the other side in
 * {@code samples/java-clean}: that fixture runs annotation processors and would
 * fire {@code [processing]} if the exclusion were dropped.
 */
public final class JavacLint {

    private JavacLint() {}

    /** rawtypes — a raw List, which is what -Xlint:rawtypes exists for. */
    static List rawList() {
        return new ArrayList();
    }

    /** cast — a redundant cast javac can see through. */
    static String redundantCast(String value) {
        return (String) value;
    }
}
