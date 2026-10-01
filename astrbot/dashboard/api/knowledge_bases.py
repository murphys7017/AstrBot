"""Legacy-compatible knowledge_base API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/kb/list": ("GET", service.list_kbs),
        "/kb/create": ("POST", service.create_kb),
        "/kb/get": ("GET", service.get_kb),
        "/kb/update": ("POST", service.update_kb),
        "/kb/delete": ("POST", service.delete_kb),
        "/kb/stats": ("GET", service.get_kb_stats),
        "/kb/document/list": ("GET", service.list_documents),
        "/kb/document/upload": ("POST", service.upload_document),
        "/kb/document/import": ("POST", service.import_documents),
        "/kb/document/upload/url": ("POST", service.upload_document_from_url),
        "/kb/document/upload/progress": ("GET", service.get_upload_progress),
        "/kb/document/get": ("GET", service.get_document),
        "/kb/document/delete": ("POST", service.delete_document),
        "/kb/chunk/list": ("GET", service.list_chunks),
        "/kb/chunk/delete": ("POST", service.delete_chunk),
        "/kb/retrieve": ("POST", service.retrieve),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
