package dev.maximalcode.sample;

import static org.assertj.core.api.Assertions.assertThat;

import dev.maximalcode.sample.domain.Widget;
import dev.maximalcode.sample.store.WidgetRepository;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabaseBuilder;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabaseType;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.UUID;

import javax.sql.DataSource;

/**
 * Testcontainers-SHAPED rather than Testcontainers-backed: a real
 * {@link DataSource}, a schema created before the assertion, and a fixed
 * {@link Clock} instead of an ambient one — the structure a real integration
 * test has, without pulling a Docker daemon into this repo's own CI.
 *
 * <p>What is asserted here is that the BASELINE stays silent on test code of
 * this shape, not that the query works. A test source set the analyzer never
 * opens is the commonest way a Java gate half-runs, so this file exists mostly
 * to be compiled.
 */
class WidgetRepositoryTest {

    private static final Clock FIXED =
            Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);

    private WidgetRepository widgets;

    @BeforeEach
    void setUp() {
        DataSource dataSource = new EmbeddedDatabaseBuilder()
                .setType(EmbeddedDatabaseType.H2)
                .generateUniqueName(true)
                .build();
        JdbcClient jdbc = JdbcClient.create(dataSource);
        jdbc.sql(
                        "CREATE TABLE widget (id VARCHAR PRIMARY KEY, name VARCHAR, price VARCHAR, created_at TIMESTAMP)")
                .update();
        widgets = new WidgetRepository(jdbc);
    }

    @Test
    void roundTripsAWidget() {
        Widget widget =
                new Widget(UUID.randomUUID(), "bolt", new BigDecimal("1.25"), FIXED.instant());

        widgets.insert(widget);

        assertThat(widgets.findById(widget.id())).contains(widget);
    }
}
