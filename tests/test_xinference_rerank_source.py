from unittest.mock import AsyncMock, Mock

import pytest

from astrbot.core.provider.sources.xinference_rerank_source import (
    XinferenceRerankProvider,
)


@pytest.fixture
def provider() -> XinferenceRerankProvider:
    instance = XinferenceRerankProvider.__new__(XinferenceRerankProvider)
    instance.model = Mock()
    return instance


@pytest.mark.asyncio
async def test_rerank_failure_propagates_instead_of_returning_empty_results(provider):
    provider.model.rerank = AsyncMock(side_effect=RuntimeError("upstream down"))

    with pytest.raises(RuntimeError, match="upstream down"):
        await provider.rerank(query="q", documents=["a", "b"])


@pytest.mark.asyncio
async def test_uninitialized_model_raises_instead_of_returning_empty_results(provider):
    provider.model = None

    with pytest.raises(RuntimeError, match="not initialized"):
        await provider.rerank(query="q", documents=["a"])
