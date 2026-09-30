"""Compatibility names for Dashboard service context and response."""

from astrbot.dashboard.services.base import DashboardService as Route
from astrbot.dashboard.services.base import Response
from astrbot.dashboard.services.base import ServiceContext as RouteContext

__all__ = ["Response", "Route", "RouteContext"]
