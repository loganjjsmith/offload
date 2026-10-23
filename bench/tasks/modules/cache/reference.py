"""A least-recently-used cache with a fixed capacity and optional expiry."""
import time
from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity, on_evict=None, ttl=None, clock=time.monotonic):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if ttl is not None and not ttl > 0:
            raise ValueError("ttl must be greater than 0")
        self.capacity = capacity
        self.on_evict = on_evict
        self.ttl = ttl
        self.clock = clock
        self._data = OrderedDict()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "expirations": 0}

    def _expire(self):
        now = self.clock()
        expired = [k for k, (_, at) in self._data.items() if at is not None and at <= now]
        for key in expired:
            value, _ = self._data.pop(key)
            self._stats["expirations"] += 1
            if self.on_evict:
                self.on_evict(key, value, "expired")
        return len(expired)

    def get(self, key, default=None):
        self._expire()
        if key not in self._data:
            self._stats["misses"] += 1
            return default
        self._stats["hits"] += 1
        self._data.move_to_end(key)
        return self._data[key][0]

    def put(self, key, value, ttl=None):
        if ttl is not None and not ttl > 0:
            raise ValueError("ttl must be greater than 0")
        self._expire()
        life = ttl if ttl is not None else self.ttl
        at = None if life is None else self.clock() + life
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = (value, at)
            return
        while len(self._data) >= self.capacity:
            old_key, (old_value, _) = self._data.popitem(last=False)
            self._stats["evictions"] += 1
            if self.on_evict:
                self.on_evict(old_key, old_value, "evicted")
        self._data[key] = (value, at)

    def delete(self, key):
        self._expire()
        return self._data.pop(key, None) is not None

    def keys(self):
        self._expire()
        return list(self._data)

    def purge(self):
        return self._expire()

    def stats(self):
        self._expire()
        return dict(self._stats)

    def __contains__(self, key):
        self._expire()
        return key in self._data

    def __len__(self):
        self._expire()
        return len(self._data)
