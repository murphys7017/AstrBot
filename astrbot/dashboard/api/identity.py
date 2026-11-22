"""Legacy-compatible identity candidate API routing."""


def register_legacy_routes(app, service):
    app.add_url_rule(
        "/api/identity/candidates",
        view_func=service.list_candidates,
        methods=["GET"],
    )
