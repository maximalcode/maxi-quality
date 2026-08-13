package dev.maximalcode.sample.domain;

import java.util.UUID;

public class WidgetNotFoundException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public WidgetNotFoundException(UUID id) {
        super("no widget with id " + id);
    }
}
