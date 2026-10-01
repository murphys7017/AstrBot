"""Legacy-compatible subagent API routing."""


def register_legacy_routes(app, service):
    routes = [
        ("/subagent/config", ("GET", service.get_config)),
        ("/subagent/config", ("POST", service.update_config)),
        ("/subagent/available-tools", ("GET", service.get_available_tools)),
    ]

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
