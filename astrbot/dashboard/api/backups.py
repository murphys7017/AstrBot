"""Legacy-compatible backup API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/backup/list": ("GET", service.list_backups),
        "/backup/export": ("POST", service.export_backup),
        "/backup/upload": ("POST", service.upload_backup),
        "/backup/upload/init": ("POST", service.upload_init),
        "/backup/upload/chunk": ("POST", service.upload_chunk),
        "/backup/upload/complete": ("POST", service.upload_complete),
        "/backup/upload/abort": ("POST", service.upload_abort),
        "/backup/check": ("POST", service.check_backup),
        "/backup/import": ("POST", service.import_backup),
        "/backup/progress": ("GET", service.get_progress),
        "/backup/download": ("GET", service.download_backup),
        "/backup/delete": ("POST", service.delete_backup),
        "/backup/rename": ("POST", service.rename_backup),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
