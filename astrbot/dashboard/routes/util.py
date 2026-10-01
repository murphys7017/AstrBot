"""Compatibility import for relocated configuration helpers."""

import sys

from astrbot.dashboard.services import util as implementation

sys.modules[__name__] = implementation
