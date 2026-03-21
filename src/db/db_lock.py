from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class DBWriteLock:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def run(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            return await coro_factory()
