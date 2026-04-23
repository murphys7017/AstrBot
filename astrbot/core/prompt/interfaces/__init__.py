"""
接口模块 - 定义 Prompt Engine 的抽象接口
"""

from .context_collector_inferface import ContextCollectorInterface
from .prompt_extension_collector_interface import PromptExtensionCollectorInterface

__all__ = [
    "ContextCollectorInterface",
    "PromptExtensionCollectorInterface",
]
