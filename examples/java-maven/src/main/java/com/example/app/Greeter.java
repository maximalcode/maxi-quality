package com.example.app;

import java.time.Clock;

/**
 * Deliberately unremarkable. An example carrying a violation teaches the
 * violation, so this file exists to be silent under the whole baseline — the
 * clock is injected rather than read from the ambient one, which is what
 * {@code no-ambient-clock-java} asks for.
 */
public final class Greeter {

    private final Clock clock;

    public Greeter(Clock clock) {
        this.clock = clock;
    }

    public String greet(String name) {
        return "Hello, " + name + " (" + clock.instant() + ")";
    }
}
