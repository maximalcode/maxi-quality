package dev.maximalcode.sample.domain;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/**
 * A record, because that is what a modern consumer writes. Money is
 * {@link BigDecimal} and the timestamp arrives from the caller rather than from
 * an ambient clock — both are conventions this baseline enforces elsewhere, and
 * the negative control has to be written the way the rules ask.
 */
public record Widget(UUID id, String name, BigDecimal price, Instant createdAt) {

    public Widget {
        if (name.isBlank()) {
            throw new IllegalArgumentException("name must not be blank");
        }
    }
}
