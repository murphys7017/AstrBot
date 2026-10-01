"""Legacy-compatible log API routing."""


def register_legacy_routes(app, service):
    app.add_url_rule("/api/live-log", view_func=service.log, methods=["GET"])

    app.add_url_rule("/api/log-history", view_func=service.log_history, methods=["GET"])

    app.add_url_rule(
        "/api/trace/settings", view_func=service.get_trace_settings, methods=["GET"]
    )

    app.add_url_rule(
        "/api/trace/settings", view_func=service.update_trace_settings, methods=["POST"]
    )
