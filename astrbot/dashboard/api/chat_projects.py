"""Legacy-compatible chatui_project API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/chatui_project/create": ("POST", service.create_project),
        "/chatui_project/list": ("GET", service.list_projects),
        "/chatui_project/get": ("GET", service.get_project),
        "/chatui_project/update": ("POST", service.update_chatui_project),
        "/chatui_project/delete": ("GET", service.delete_project),
        "/chatui_project/add_session": ("POST", service.add_session_to_project),
        "/chatui_project/remove_session": ("POST", service.remove_session_from_project),
        "/chatui_project/get_sessions": ("GET", service.get_project_sessions),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
