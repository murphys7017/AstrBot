from .base import DashboardService, ServiceContext


class StaticFileService(DashboardService):
    def __init__(self, context: ServiceContext) -> None:
        super().__init__(context)

    async def index(self):
        return await self.app.send_static_file("index.html")


class StaticFileRoute(StaticFileService):
    """Compatibility constructor for callers of the former route module."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from astrbot.dashboard.api.static_files import register_legacy_routes

        register_legacy_routes(self.app, self)
