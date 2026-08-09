package dev.maximalcode.sample.api;

import dev.maximalcode.sample.domain.Widget;
import dev.maximalcode.sample.domain.WidgetService;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.UUID;

@RestController
@RequestMapping("/widgets")
public class WidgetController {

    private final WidgetService service;

    public WidgetController(WidgetService service) {
        this.service = service;
    }

    public record CreateWidgetRequest(String name, BigDecimal price) {}

    @GetMapping("/{id}")
    public Widget byId(@PathVariable UUID id) {
        return service.get(id);
    }

    @PostMapping
    public ResponseEntity<Widget> create(@RequestBody CreateWidgetRequest request) {
        return ResponseEntity.ok(service.createWidget(request.name(), request.price()));
    }
}
