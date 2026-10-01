"""Compatibility import for the relocated Dashboard service."""

import sys

from astrbot.dashboard.services import command_service as implementation

sys.modules[__name__] = implementation
