"""Legacy-compatible config API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/config/abconf/new": ("POST", service.create_abconf),
        "/config/abconf": ("GET", service.get_abconf),
        "/config/abconfs": ("GET", service.get_abconf_list),
        "/config/abconf/delete": ("POST", service.delete_abconf),
        "/config/abconf/update": ("POST", service.update_abconf),
        "/config/umo_abconf_routes": ("GET", service.get_uc_table),
        "/config/umo_abconf_route/update_all": ("POST", service.update_ucr_all),
        "/config/umo_abconf_route/update": ("POST", service.update_ucr),
        "/config/umo_abconf_route/delete": ("POST", service.delete_ucr),
        "/config/get": ("GET", service.get_configs),
        "/config/default": ("GET", service.get_default_config),
        "/config/astrbot/update": ("POST", service.post_astrbot_configs),
        "/config/plugin/update": ("POST", service.post_plugin_configs),
        "/config/file/upload": ("POST", service.upload_config_file),
        "/config/file/delete": ("POST", service.delete_config_file),
        "/config/file/get": ("GET", service.get_config_file_list),
        "/config/platform/new": ("POST", service.post_new_platform),
        "/config/platform/update": ("POST", service.post_update_platform),
        "/config/platform/delete": ("POST", service.post_delete_platform),
        "/config/platform/list": ("GET", service.get_platform_list),
        "/config/provider/new": ("POST", service.post_new_provider),
        "/config/provider/update": ("POST", service.post_update_provider),
        "/config/provider/delete": ("POST", service.post_delete_provider),
        "/config/provider/template": ("GET", service.get_provider_template),
        "/config/provider/check_one": ("GET", service.check_one_provider_status),
        "/config/provider/test_json_output": (
            "POST",
            service.test_provider_json_output,
        ),
        "/config/provider/list": ("GET", service.get_provider_config_list),
        "/config/provider/model_list": ("GET", service.get_provider_model_list),
        "/config/provider/get_embedding_dim": ("POST", service.get_embedding_dim),
        "/config/provider_sources/models": ("GET", service.get_provider_source_models),
        "/config/provider_sources/update": ("POST", service.update_provider_source),
        "/config/provider_sources/delete": ("POST", service.delete_provider_source),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
