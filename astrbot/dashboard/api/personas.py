"""Legacy-compatible persona API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/persona/list": ("GET", service.list_personas),
        "/persona/detail": ("POST", service.get_persona_detail),
        "/persona/create": ("POST", service.create_persona),
        "/persona/update": ("POST", service.update_persona),
        "/persona/delete": ("POST", service.delete_persona),
        "/persona/move": ("POST", service.move_persona),
        "/persona/reorder": ("POST", service.reorder_items),
        "/persona/folder/list": ("GET", service.list_folders),
        "/persona/folder/tree": ("GET", service.get_folder_tree),
        "/persona/folder/detail": ("POST", service.get_folder_detail),
        "/persona/folder/create": ("POST", service.create_folder),
        "/persona/folder/update": ("POST", service.update_folder),
        "/persona/folder/delete": ("POST", service.delete_folder),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
