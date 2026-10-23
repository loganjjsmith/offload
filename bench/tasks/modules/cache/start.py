"""A least-recently-used cache with a fixed capacity."""
from collections import OrderedDict


class LRUCache:
    """Keeps at most `capacity` entries; adding one more evicts the least recently used.

    `on_evict(key, value)` is called for every entry evicted to make room.
    """

    def __init__(self, capacity, on_evict=None):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self.on_evict = on_evict
        self._data = OrderedDict()

    def get(self, key, default=None):
        """The value for `key`, marking it most recently used; `default` if absent."""
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key, value):
        """Adds or replaces an entry and marks it most recently used."""
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = value
            return
        while len(self._data) >= self.capacity:
            old_key, old_value = self._data.popitem(last=False)
            if self.on_evict:
                self.on_evict(old_key, old_value)
        self._data[key] = value

    def delete(self, key):
        """Removes `key`; returns whether it was present. No callback."""
        return self._data.pop(key, _MISSING) is not _MISSING

    def keys(self):
        """Keys from least to most recently used."""
        return list(self._data)

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)


_MISSING = object()
