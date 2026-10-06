"""Native dashboard host and preserved local service wiring."""

from importlib import import_module

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request

from astrbot.dashboard.asgi_runtime import FastAPIAppAdapter
from astrbot.dashboard.services.base import ServiceContext


def create_dashboard_app(server):
    app = FastAPI(title="AstrBot API", docs_url=None, redoc_url=None, openapi_url=None)
    # Compress sizeable dashboard assets and JSON responses without buffering SSE.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    adapter = FastAPIAppAdapter(app, static_folder=server.data_path)
    adapter.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024
    adapter.config["BODY_LIMIT_OVERRIDES"] = (
        ("/api/backup/upload/chunk", 2 * 1024 * 1024),
        ("/api/chat/post_file/chunk", 2 * 1024 * 1024),
        ("/api/chat/post_file", 513 * 1024 * 1024),
        ("/api/config/file/upload", 501 * 1024 * 1024),
        ("/api/kb/document/upload", 513 * 1024 * 1024),
        ("/api/plugin/install-upload", 129 * 1024 * 1024),
    )
    adapter._dashboard_server = server
    adapter.before_request(server.auth_middleware)
    context = ServiceContext(server.config, adapter)
    server.app = adapter
    server.context = context
    core = server.core_lifecycle
    db = server.db
    specifications = [
        (
            "ur",
            "update",
            "UpdateService",
            "updates",
            (core.astrbot_updator, core),
            {"dashboard_static_folder": server.data_path},
        ),
        (
            "sr",
            "stat",
            "StatService",
            "stats",
            (db, core),
            {"dashboard_static_folder": server.data_path},
        ),
        ("pr", "plugin", "PluginService", "plugins", (core, core.plugin_manager), {}),
        ("command_route", "command", "CommandService", "extensions", (core,), {}),
        ("cr", "config", "ConfigService", "config_profiles", (core,), {}),
        ("lr", "log", "LogService", "logs", (core.log_broker,), {}),
        ("sfr", "static_file", "StaticFileService", "static_files", (), {}),
        ("ar", "auth", "AuthService", "auth", (db,), {}),
        ("api_key_route", "api_key", "ApiKeyService", "api_keys", (db,), {}),
        ("chat_route", "chat", "ChatService", "chat", (db, core), {}),
        ("open_api_route", "open_api", "OpenApiService", "open_api", (db, core), {}),
        (
            "chatui_project_route",
            "chatui_project_api",
            "ChatUIProjectApiService",
            "chat_projects",
            (db,),
            {},
        ),
        ("tools_root", "tools", "ToolsService", "tools", (core,), {}),
        ("subagent_route", "subagent", "SubAgentService", "subagents", (core,), {}),
        ("skills_route", "skills", "SkillsService", "skills", (core,), {}),
        (
            "conversation_route",
            "conversation",
            "ConversationService",
            "conversations",
            (db, core),
            {},
        ),
        ("file_route", "file", "FileService", "files", (), {}),
        (
            "session_management_route",
            "session_management",
            "SessionManagementService",
            "sessions",
            (db, core),
            {},
        ),
        ("persona_route", "persona", "PersonaService", "personas", (db, core), {}),
        ("cron_route", "cron", "CronService", "cron", (core,), {}),
        ("t2i_route", "t2i", "T2iService", "t2i", (core,), {}),
        (
            "kb_route",
            "knowledge_base",
            "KnowledgeBaseService",
            "knowledge_bases",
            (core,),
            {},
        ),
        ("platform_route", "platform", "PlatformService", "platform", (core,), {}),
        ("backup_route", "backup", "BackupService", "backups", (db, core), {}),
        (
            "live_chat_route",
            "live_chat",
            "LiveChatService",
            "live_chat",
            (db, core),
            {},
        ),
    ]
    services = {}
    for attribute, module, class_name, api_module, args, kwargs in specifications:
        service_type = getattr(
            import_module(f"astrbot.dashboard.services.{module}_service"), class_name
        )
        if attribute == "open_api_route":
            args = (*args, server.chat_route)
        service = service_type(context, *args, **kwargs)
        setattr(server, attribute, service)
        services[attribute] = service
        import_module(f"astrbot.dashboard.api.{api_module}").register_legacy_routes(
            adapter, service
        )
    app.state.core_lifecycle = core
    app.state.db = db
    app.state.services = services
    app.state.dashboard = server
    adapter.add_url_rule(
        "/api/plug/<path:subpath>",
        server.srv_plug_route,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return JSONResponse(
            {"status": "error", "message": str(error.detail), "data": None},
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.get("/{path:path}", include_in_schema=False)
    async def static_asset(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        # Deep links are limited to known SPA routes, never unknown API paths.
        if path.startswith(("plugin-page/", "plugin-view/", "plugin/")):
            return await adapter.send_static_file("index.html")
        return await adapter.send_static_file(path)

    return app
