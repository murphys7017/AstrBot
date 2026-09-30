"""Compatibility import for the relocated Dashboard service."""

import sys

from astrbot.dashboard.services import persona_service as implementation

sys.modules[__name__] = implementation
