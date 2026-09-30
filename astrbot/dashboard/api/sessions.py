"""Legacy-compatible session_management API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/session/list-rule": ("GET", service.list_session_rule),
        "/session/update-rule": ("POST", service.update_session_rule),
        "/session/delete-rule": ("POST", service.delete_session_rule),
        "/session/batch-delete-rule": ("POST", service.batch_delete_session_rule),
        "/session/active-umos": ("GET", service.list_umos),
        "/session/list-all-with-status": ("GET", service.list_all_umos_with_status),
        "/session/batch-update-service": ("POST", service.batch_update_service),
        "/session/batch-update-provider": ("POST", service.batch_update_provider),
        "/session/groups": ("GET", service.list_groups),
        "/session/group/create": ("POST", service.create_group),
        "/session/group/update": ("POST", service.update_group),
        "/session/group/delete": ("POST", service.delete_group),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
