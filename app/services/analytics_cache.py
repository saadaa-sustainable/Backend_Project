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


#: How many answers ONE endpoint keeps.
#:
#: Was 64, which was survivable while a cache key was little more than
#: a date: each endpoint held a handful of entries and the rest of the
#: allowance went unused. The period picker changed that. A key now
#: carries the whole window -- from_day, day, compare_from, compare_to,
#: compare -- so every range a reader tries is a new entry, and the 64
#: fill up.
#:
#: They are not cheap. An entry is the live response OBJECT, several
#: times the size of its JSON, and the inventory answer alone is about
#: three quarters of a megabyte on the wire. Fifty-one endpoints each
#: holding sixty-four of those will not fit in the 512 MB this service
#: runs in, and a process that exceeds it is killed -- which is what
#: took the API down twice in one day.
#:
#: Four is enough for what the cache is actually for: absorbing the
#: burst of identical requests a page makes when it loads, and the
#: repeat when a second reader opens it moments later. Beyond that the
#: TTL is doing the work, not the depth.
_DEFAULT_MAX_ENTRIES = 4


class AnalyticsCache:
    def __init__(self, ttl: float = 60.0,
                 max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self.entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.fills: dict[str, _Fill] = {}
        #: Bumped by invalidate(). A fill that started before the bump is
        #: reading pre-write data, so its result is returned to the
        #: caller that asked for it but never stored -- otherwise a read
        #: already in flight when a write lands would re-cache the stale
        #: answer for a further full ttl.
        self.generation = 0

    def invalidate(self) -> None:
        """Drop every cached answer. Called after a write."""
        self.entries.clear()
        self.generation += 1

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
                started_at = self.generation
                value = await load()
                if self.generation != started_at:
                    return value
                self.entries[key] = (monotonic(), value)
                while len(self.entries) > self.max_entries:
                    self.entries.popitem(last=False)
                return value
        finally:
            fill.users -= 1
            if fill.users == 0:
                self.fills.pop(key, None)


def cached_analytics(*, ttl: float = 60.0,
                     max_entries: int = _DEFAULT_MAX_ENTRIES):
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
