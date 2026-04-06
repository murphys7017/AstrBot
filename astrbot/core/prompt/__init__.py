"""
AstrBot Prompt Engine - 上下文数据层（第一阶段）

本模块提供：
- ContextCatalog: 声明式上下文定义
- ContextPack/ContextSlot: 收集到的上下文数据容器
- ContextCollector: 上下文收集器抽象基类和具体实现
-（未来：Selector 选择器、Renderer 渲染器）
"""

from .collectors import (
    ConversationHistoryCollector,
    InputCollector,
    MemoryCollector,
    PersonaCollector,
    PolicyCollector,
    SessionCollector,
)
from .context_catalog import (
    CatalogItem,
    ContextCatalog,
    ContextCatalogLoader,
    get_catalog,
)
from .context_collect import (
    PROMPT_CONTEXT_PACK_EXTRA_KEY,
    collect_context_pack,
    log_context_pack,
)
from .context_types import (
    CategoryType,
    ContextPack,
    ContextSlot,
    LifecycleType,
    LLMExposureType,
    PlacementType,
    RenderModeType,
    SlotName,
)
from .interfaces import ContextCollectorInterface
from .persona_segments import (
    finalize_persona_segments,
    normalize_section_name,
    parse_legacy_persona_prompt,
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
    # Persona parsing
    "normalize_section_name",
    "parse_legacy_persona_prompt",
    "finalize_persona_segments",
    # Interfaces
    "ContextCollectorInterface",
    # Collectors
    "ConversationHistoryCollector",
    "InputCollector",
    "MemoryCollector",
    "PersonaCollector",
    "PolicyCollector",
    "SessionCollector",
    # Collection flow
    "PROMPT_CONTEXT_PACK_EXTRA_KEY",
    "collect_context_pack",
    "log_context_pack",
]
