from quart import abort, send_file

from astrbot.core import file_token_service

from .base import DashboardService, ServiceContext


class FileService(DashboardService):
    def __init__(
        self,
        context: ServiceContext,
    ) -> None:
        super().__init__(context)

    async def serve_file(self, file_token: str):
        try:
            file_path = await file_token_service.handle_file(file_token)
            return await send_file(file_path)
        except (FileNotFoundError, KeyError):
            return abort(404)


class FileRoute(FileService):
    """Compatibility constructor for callers of the former route module."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from astrbot.dashboard.api.files import register_legacy_routes

        register_legacy_routes(self.app, self)
