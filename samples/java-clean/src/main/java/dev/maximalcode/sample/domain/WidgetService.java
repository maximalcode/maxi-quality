package dev.maximalcode.sample.domain;

import dev.maximalcode.sample.store.WidgetRepository;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.Clock;
import java.util.List;
import java.util.UUID;

/**
 * The clock is INJECTED, which is what {@code no-ambient-clock} asks for, and
 * every mutation carries an authorisation annotation, which is what
 * {@code mutation-requires-authz} asks for. Both are Layer 2 conventions rather
 * than Layer 1 checks; the negative control has to satisfy the whole baseline,
 * not just the half that compiles.
 */
@Service
public class WidgetService {

    private final WidgetRepository widgets;
    private final Clock clock;

    public WidgetService(WidgetRepository widgets, Clock clock) {
        this.widgets = widgets;
        this.clock = clock;
    }

    public Widget get(UUID id) {
        return widgets.findById(id).orElseThrow(() -> new WidgetNotFoundException(id));
    }

    public List<Widget> byName(String name) {
        return widgets.findByName(name);
    }

    @PreAuthorize("hasAuthority('widget:write')")
    public Widget createWidget(String name, BigDecimal price) {
        Widget widget = new Widget(UUID.randomUUID(), name, price, clock.instant());
        widgets.insert(widget);
        return widget;
    }
}
