"""Legacy-compatible file API routing."""


def register_legacy_routes(app, service):
    routes = {"/file/<file_token>": ("GET", service.serve_file)}

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
