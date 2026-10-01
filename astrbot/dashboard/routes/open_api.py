"""Compatibility import for the relocated Dashboard service."""

import sys

from astrbot.dashboard.services import open_api_service as implementation

sys.modules[__name__] = implementation
