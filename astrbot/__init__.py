__version__ = "4.29.0-beta.1"

from .core.log import LogManager

logger = LogManager.GetLogger(log_name="astrbot")
