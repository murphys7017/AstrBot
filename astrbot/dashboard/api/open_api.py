"""Legacy-compatible open_api API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/v1/chat": ("POST", service.chat_send),
        "/v1/chat/sessions": ("GET", service.get_chat_sessions),
        "/v1/configs": ("GET", service.get_chat_configs),
        "/v1/file": [
            ("POST", service.openapi_upload_file),
            ("GET", service.openapi_get_file),
        ],
        "/v1/im/message": ("POST", service.send_message),
        "/v1/im/bots": ("GET", service.get_bots),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])

    app.websocket("/api/v1/chat/ws")(service.chat_ws)
