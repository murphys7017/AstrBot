"""Legacy-compatible platform API routing."""


def register_legacy_routes(app, service):
    app.add_url_rule(
        "/api/platform/webhook/<webhook_uuid>",
        view_func=service.unified_webhook_callback,
        methods=["GET", "POST"],
    )

    app.add_url_rule(
        "/api/platform/stats", view_func=service.get_platform_stats, methods=["GET"]
    )

    app.add_url_rule(
        "/api/platform/registration/<platform_type>",
        view_func=service.handle_platform_registration,
        methods=["POST"],
    )
