"""Legacy-compatible tools API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/tools/mcp/servers": ("GET", service.get_mcp_servers),
        "/tools/mcp/add": ("POST", service.add_mcp_server),
        "/tools/mcp/update": ("POST", service.update_mcp_server),
        "/tools/mcp/delete": ("POST", service.delete_mcp_server),
        "/tools/mcp/test": ("POST", service.test_mcp_connection),
        "/tools/list": ("GET", service.get_tool_list),
        "/tools/toggle-tool": ("POST", service.toggle_tool),
        "/tools/permission": ("POST", service.update_tool_permission),
        "/tools/mcp/sync-provider": ("POST", service.sync_provider),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
