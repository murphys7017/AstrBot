"""
AstrBot Prompt Engine - 上下文数据层（第一阶段）

本模块提供：
- ContextCatalog: 声明式上下文定义
- ContextPack/ContextSlot: 收集到的上下文数据容器
-（未来：ContextCollector 收集器、Selector 选择器、Renderer 渲染器）
"""

from .context_types import (
    CategoryType,
    LifecycleType,
    PlacementType,
    RenderModeType,
    LLMExposureType,
    SlotName,
    ContextSlot,
    ContextPack,
)
from .context_catalog import (
    CatalogItem,
    ContextCatalog,
    ContextCatalogLoader,
    get_catalog,
)

__all__ = [
    # Types
    "CategoryType",
    "LifecycleType",
    "PlacementType",
    "RenderModeType",
    "LLMExposureType",
    "SlotName",
    # Data models
    "ContextSlot",
    "ContextPack",
    # Catalog
    "CatalogItem",
    "ContextCatalog",
    "ContextCatalogLoader",
    "get_catalog",
]
