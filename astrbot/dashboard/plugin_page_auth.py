from urllib.parse import unquote

from astrbot.dashboard.asgi_runtime import request

PLUGIN_PAGE_CONTENT_PREFIX = "/api/plugin/page/content/"
PLUGIN_PAGE_BRIDGE_PATH = "/api/plugin/page/bridge-sdk.js"
PLUGIN_VIEW_CONTENT_PREFIX = "/api/plugin/view/content/"
PLUGIN_VIEW_BRIDGE_PATH = "/api/plugin/view/bridge-sdk.js"
PLUGIN_VIEW_TOKEN_PREFIX = "/api/v1/plugins/"
PLUGIN_PAGE_TOKEN_TYPE = "plugin_page_asset"


class PluginPageAuth:
    @staticmethod
    def is_protected_path(path: str) -> bool:
        return any(
            path.startswith(prefix)
            for prefix in (
                PLUGIN_PAGE_CONTENT_PREFIX,
                PLUGIN_VIEW_CONTENT_PREFIX,
                PLUGIN_PAGE_BRIDGE_PATH,
                PLUGIN_VIEW_BRIDGE_PATH,
            )
        ) or PluginPageAuth.is_path_token_path(path)

    @staticmethod
    def is_path_token_path(path: str) -> bool:
        parts = path.split("/")
        return (
            len(parts) >= 9
            and parts[1:4] == ["api", "v1", "plugins"]
            and parts[5] in {"views", "pages"}
            and parts[7] == "_t"
            and bool(parts[8])
        )

    @staticmethod
    def extract_path_asset_token(path: str) -> str | None:
        if not PluginPageAuth.is_path_token_path(path):
            return None
        parts = path.split("/")
        return unquote(parts[8]).strip() or None

    @staticmethod
    def extract_path_scope(path: str) -> tuple[str | None, str | None]:
        if not PluginPageAuth.is_path_token_path(path):
            return None, None
        parts = path.split("/")
        plugin_name = unquote(parts[4]).strip() or None
        page_name = unquote(parts[6]).strip() or None
        return plugin_name, page_name

    @staticmethod
    def is_asset_token(payload: dict) -> bool:
        return payload.get("token_type") == PLUGIN_PAGE_TOKEN_TYPE

    @staticmethod
    def extract_asset_token() -> str | None:
        query_asset_token = request.args.get("asset_token", "").strip()
        return query_asset_token or None

    @staticmethod
    def extract_plugin_name_from_path(path: str) -> str | None:
        prefix = next(
            (
                prefix
                for prefix in (PLUGIN_PAGE_CONTENT_PREFIX, PLUGIN_VIEW_CONTENT_PREFIX)
                if path.startswith(prefix)
            ),
            None,
        )
        if prefix is None:
            return None
        remainder = path[len(prefix) :]
        plugin_part = remainder.split("/", 1)[0] if remainder else ""
        return unquote(plugin_part) if plugin_part else None

    @staticmethod
    def extract_page_name_from_path(path: str) -> str | None:
        prefix = next(
            (
                prefix
                for prefix in (PLUGIN_PAGE_CONTENT_PREFIX, PLUGIN_VIEW_CONTENT_PREFIX)
                if path.startswith(prefix)
            ),
            None,
        )
        if prefix is None:
            return None
        remainder = path[len(prefix) :]
        parts = remainder.split("/", 2)
        page_part = parts[1] if len(parts) > 1 else ""
        return unquote(page_part) if page_part else None

    @classmethod
    def is_scope_valid(cls, payload: dict, path: str) -> bool:
        if not cls.is_protected_path(path):
            return False
        if path.startswith((PLUGIN_PAGE_BRIDGE_PATH, PLUGIN_VIEW_BRIDGE_PATH)):
            return True

        request_plugin_name, request_page_name = cls.extract_path_scope(path)
        if request_plugin_name and request_page_name:
            return (
                payload.get("plugin_name") == request_plugin_name
                and payload.get("page_name") == request_page_name
            )

        token_plugin_name = payload.get("plugin_name")
        token_page_name = payload.get("page_name")
        request_plugin_name = cls.extract_plugin_name_from_path(path)
        request_page_name = cls.extract_page_name_from_path(path)
        if (
            not isinstance(token_plugin_name, str)
            or not token_plugin_name
            or not isinstance(token_page_name, str)
            or not token_page_name
            or not request_plugin_name
            or not request_page_name
        ):
            return False
        return (
            token_plugin_name == request_plugin_name
            and token_page_name == request_page_name
        )
