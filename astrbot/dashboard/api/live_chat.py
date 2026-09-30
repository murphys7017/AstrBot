"""Legacy-compatible live_chat API routing."""


def register_legacy_routes(app, service):
    app.websocket("/api/live_chat/ws")(service.live_chat_ws)

    app.websocket("/api/unified_chat/ws")(service.unified_chat_ws)
