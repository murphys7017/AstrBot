"""Compatibility import for the relocated Dashboard service."""

import sys

from astrbot.dashboard.services import cron_service as implementation

sys.modules[__name__] = implementation
