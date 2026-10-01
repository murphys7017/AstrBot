"""Legacy-compatible stat API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/stat/get": ("GET", service.get_stat),
        "/stat/personal-runtime": ("GET", service.get_personal_runtime),
        "/stat/provider-tokens": ("GET", service.get_provider_token_stats),
        "/stat/version": ("GET", service.get_version),
        "/stat/start-time": ("GET", service.get_start_time),
        "/stat/restart-core": ("POST", service.restart_core),
        "/stat/test-ghproxy-connection": ("POST", service.test_ghproxy_connection),
        "/stat/changelog": ("GET", service.get_changelog),
        "/stat/changelog/list": ("GET", service.list_changelog_versions),
        "/stat/first-notice": ("GET", service.get_first_notice),
        "/stat/storage": ("GET", service.get_storage_status),
        "/stat/storage/cleanup": ("POST", service.cleanup_storage),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
