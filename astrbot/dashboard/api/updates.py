"""Legacy-compatible update API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/update/check": ("GET", service.check_update),
        "/update/progress": ("GET", service.get_update_progress),
        "/update/releases": ("GET", service.get_releases),
        "/update/do": ("POST", service.update_project),
        "/update/dashboard": ("POST", service.update_dashboard),
        "/update/pip-install": ("POST", service.install_pip_package),
        "/update/migration": ("POST", service.do_migration),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
