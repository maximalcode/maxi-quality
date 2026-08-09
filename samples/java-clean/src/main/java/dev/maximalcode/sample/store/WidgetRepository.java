package dev.maximalcode.sample.store;

import dev.maximalcode.sample.domain.Widget;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** JdbcClient with bound parameters throughout — never a concatenated statement. */
@Repository
public class WidgetRepository {

    private final JdbcClient jdbc;

    public WidgetRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<Widget> findById(UUID id) {
        return jdbc.sql("SELECT id, name, price, created_at FROM widget WHERE id = :id")
                .param("id", id)
                .query(WidgetRepository::map)
                .optional();
    }

    public List<Widget> findByName(String name) {
        return jdbc.sql("SELECT id, name, price, created_at FROM widget WHERE name = :name")
                .param("name", name)
                .query(WidgetRepository::map)
                .list();
    }

    public void insert(Widget widget) {
        jdbc.sql(
                        "INSERT INTO widget (id, name, price, created_at) VALUES (:id, :name, :price, :createdAt)")
                .param("id", widget.id())
                .param("name", widget.name())
                .param("price", widget.price())
                .param("createdAt", widget.createdAt())
                .update();
    }

    private static Widget map(java.sql.ResultSet rs, int rowNum) throws java.sql.SQLException {
        return new Widget(
                UUID.fromString(rs.getString("id")),
                rs.getString("name"),
                new BigDecimal(rs.getString("price")),
                Instant.ofEpochMilli(rs.getTimestamp("created_at").getTime()));
    }
}
