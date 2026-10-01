"""Legacy-compatible api_key API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/apikey/list": ("GET", service.list_api_keys),
        "/apikey/create": ("POST", service.create_api_key),
        "/apikey/revoke": ("POST", service.revoke_api_key),
        "/apikey/delete": ("POST", service.delete_api_key),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
