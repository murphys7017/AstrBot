"""Legacy-compatible conversation API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/conversation/list": ("GET", service.list_conversations),
        "/conversation/detail": ("POST", service.get_conv_detail),
        "/conversation/update": ("POST", service.upd_conv),
        "/conversation/delete": ("POST", service.del_conv),
        "/conversation/update_history": ("POST", service.update_history),
        "/conversation/export": ("POST", service.export_conversations),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
