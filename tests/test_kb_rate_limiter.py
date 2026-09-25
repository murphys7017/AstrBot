import asyncio
import time

import pytest

import astrbot.api  # noqa: F401
from astrbot.core.knowledge_base.kb_helper import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_spaces_concurrent_callers():
    limiter = RateLimiter(max_rpm=1200)
    entered_at = []

    async def enter_limiter():
        async with limiter:
            entered_at.append(time.monotonic())

    await asyncio.gather(*(enter_limiter() for _ in range(3)))

    assert len(entered_at) == 3
    assert all(
        later - earlier >= limiter.interval * 0.8
        for earlier, later in zip(entered_at, entered_at[1:])
    )
