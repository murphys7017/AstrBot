"""Legacy-compatible auth API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/auth/login": ("POST", service.login),
        "/auth/logout": ("POST", service.logout),
        "/auth/setup-status": ("GET", service.setup_status),
        "/auth/setup": ("POST", service.setup),
        "/auth/setup-authenticated": ("POST", service.setup_authenticated),
        "/auth/account/edit": ("POST", service.edit_account),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
