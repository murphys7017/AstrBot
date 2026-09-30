"""Compatibility import for the relocated Dashboard service."""

import sys

from astrbot.dashboard.services import stat_service as implementation

sys.modules[__name__] = implementation
