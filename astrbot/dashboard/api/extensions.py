"""Legacy-compatible command API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/commands": ("GET", service.get_commands),
        "/commands/conflicts": ("GET", service.get_conflicts),
        "/commands/toggle": ("POST", service.toggle_command),
        "/commands/rename": ("POST", service.rename_command),
        "/commands/permission": ("POST", service.update_permission),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
