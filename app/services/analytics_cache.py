"""Small process-local response caches with one active fill per filter set.

Fill work stays in the request that owns its database session. Cancellation
releases the lock; the next waiting request can retry with its own session.
No task outlives a request while retaining a request-scoped AsyncSession.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import wraps
from time import monotonic
from typing import Any, Awaitable, Callable

from pydantic import BaseModel
from pydantic.fields import FieldInfo


@dataclass
class _Fill:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class AnalyticsCache:
    def __init__(self, ttl: float = 60.0, max_entries: int = 64) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self.entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.fills: dict[str, _Fill] = {}

    async def get(self, key: str, load: Callable[[], Awaitable[Any]]) -> Any:
        fill = self.fills.setdefault(key, _Fill())
        fill.users += 1
        try:
            async with fill.lock:
                entry = self.entries.get(key)
                if entry and monotonic() - entry[0] < self.ttl:
                    self.entries.move_to_end(key)
                    return entry[1]
                self.entries.pop(key, None)
                value = await load()
                self.entries[key] = (monotonic(), value)
                while len(self.entries) > self.max_entries:
                    self.entries.popitem(last=False)
                return value
        finally:
            fill.users -= 1
            if fill.users == 0:
                self.fills.pop(key, None)


def cached_analytics(*, ttl: float = 60.0, max_entries: int = 64):
    """Cache an internal analytics read, excluding its DB session from the key."""
    def decorate(fn):
        # Resolve postponed annotations in the endpoint's own module so
        # FastAPI still sees its real request models through this wrapper.
        signature = inspect.signature(fn, eval_str=True)
        cache = AnalyticsCache(ttl, max_entries)

        @wraps(fn)
        async def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            for name, value in bound.arguments.items():
                if isinstance(value, FieldInfo):
                    bound.arguments[name] = value.default
            values = {
                name: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
                for name, value in bound.arguments.items() if name != "session"
            }
            key = json.dumps(values, sort_keys=True, default=str)
            return await cache.get(key, lambda: fn(*bound.args, **bound.kwargs))

        wrapped.__signature__ = signature
        wrapped.analytics_cache = cache
        return wrapped
    return decorate
