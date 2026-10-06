"""Legacy-compatible plugin API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/plugin/get": ("GET", service.get_plugins),
        "/plugin/detail": ("GET", service.get_plugin_detail),
        "/plugin/capabilities": ("GET", service.get_plugin_capabilities),
        "/plugin/check-compat": ("POST", service.check_plugin_compatibility),
        "/plugin/page/entry": ("GET", service.get_plugin_page_entry_config),
        "/plugin/view/entry": ("GET", service.get_plugin_page_entry_config),
        "/plugin/install": ("POST", service.install_plugin),
        "/plugin/install-upload": ("POST", service.install_plugin_upload),
        "/plugin/update": ("POST", service.update_plugin),
        "/plugin/update-all": ("POST", service.update_all_plugins),
        "/plugin/uninstall": ("POST", service.uninstall_plugin),
        "/plugin/uninstall-failed": ("POST", service.uninstall_failed_plugin),
        "/plugin/market_list": ("GET", service.get_online_plugins),
        "/plugin/off": ("POST", service.off_plugin),
        "/plugin/on": ("POST", service.on_plugin),
        "/plugin/reload-failed": ("POST", service.reload_failed_plugins),
        "/plugin/reload": ("POST", service.reload_plugins),
        "/plugin/readme": ("GET", service.get_plugin_readme),
        "/plugin/changelog": ("GET", service.get_plugin_changelog),
        "/plugin/source/get": ("GET", service.get_custom_source),
        "/plugin/source/save": ("POST", service.save_custom_source),
        "/plugin/source/get-failed-plugins": ("GET", service.get_failed_plugins),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])

    app.add_url_rule(
        "/api/plugin/page/content/<plugin_name>/<page_name>/",
        endpoint="plugin_page_content_entry",
        view_func=service.get_plugin_page_entry,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/plugin/view/content/<plugin_name>/<page_name>/",
        endpoint="plugin_view_content_entry",
        view_func=service.get_plugin_page_entry,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/plugin/page/content/<plugin_name>/<page_name>/<path:asset_path>",
        endpoint="plugin_page_content_asset",
        view_func=service.get_plugin_page_asset,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/plugin/view/content/<plugin_name>/<page_name>/<path:asset_path>",
        endpoint="plugin_view_content_asset",
        view_func=service.get_plugin_page_asset,
        methods=["GET"],
    )

    # Canonical plugin View assets carry their scoped token in the path so
    # relative URLs inherit the token without server-side URL rewriting.
    app.add_url_rule(
        "/api/v1/plugins/<plugin_id>/views/<view_name>/_t/<token>/",
        endpoint="plugin_view_token_entry",
        view_func=service.get_plugin_view_token_asset,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/v1/plugins/<plugin_id>/views/<view_name>/_t/<token>/<path:asset_path>",
        endpoint="plugin_view_token_asset",
        view_func=service.get_plugin_view_token_asset,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/v1/plugins/<plugin_id>/pages/<view_name>/_t/<token>/",
        endpoint="plugin_page_token_entry",
        view_func=service.get_plugin_view_token_asset,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/v1/plugins/<plugin_id>/pages/<view_name>/_t/<token>/<path:asset_path>",
        endpoint="plugin_page_token_asset",
        view_func=service.get_plugin_view_token_asset,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/plugin/page/bridge-sdk.js",
        endpoint="plugin_page_bridge_sdk",
        view_func=service.get_plugin_page_bridge_sdk,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/plugin/view/bridge-sdk.js",
        endpoint="plugin_view_bridge_sdk",
        view_func=service.get_plugin_page_bridge_sdk,
        methods=["GET"],
    )
