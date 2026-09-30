"""Legacy-compatible t2i API routing."""


def register_legacy_routes(app, service):
    routes = [
        ("/t2i/templates", ("GET", service.list_templates)),
        ("/t2i/templates/active", ("GET", service.get_active_template)),
        ("/t2i/templates/create", ("POST", service.create_template)),
        ("/t2i/templates/reset_default", ("POST", service.reset_default_template)),
        ("/t2i/templates/set_active", ("POST", service.set_active_template)),
        (
            "/t2i/templates/<name>",
            [
                ("GET", service.get_template),
                ("PUT", service.update_template),
                ("DELETE", service.delete_template),
            ],
        ),
    ]

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
