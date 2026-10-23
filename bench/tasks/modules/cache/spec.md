## Changes

Add expiry and statistics to `LRUCache`. Everything not mentioned here keeps working as before
(capacity, `get`/`put`/`delete`/`keys`, `in`, `len`, the `ValueError` for a capacity below 1).

1. **Constructor**: `LRUCache(capacity, on_evict=None, ttl=None, clock=time.monotonic)`. `ttl` is the
   default lifetime of an entry in seconds (`None` means entries never expire). `clock` is a function
   returning the current time in seconds; the cache must read the time only through it. A `ttl` that is
   not `None` and not greater than 0 raises `ValueError`.
2. **Per-entry lifetime**: `put(key, value, ttl=None)`. The entry expires at `clock() + lifetime`, where
   the lifetime is the `ttl` argument if given, else the cache's `ttl`; with neither, it never expires.
   A `ttl` argument that is not greater than 0 raises `ValueError`. Replacing an existing key sets a new
   expiry time from its new lifetime.
3. **Expired entries are absent**: an entry whose expiry time is less than or equal to `clock()` is
   expired. `get` returns the default for it, `in` is `False`, and it is not counted by `len` or listed
   by `keys`. `get` does not extend an entry's lifetime.
4. **Removing expired entries**: whenever any public method (`get`, `put`, `delete`, `keys`, `in`, `len`,
   `purge`, `stats`) runs, it first removes every expired entry, calling `on_evict` for each in least to
   most recently used order. So a `put` that needs room removes expired entries before evicting any live
   one.
5. **Callback reason**: `on_evict` is now called as `on_evict(key, value, reason)`, where `reason` is
   `"expired"` or `"evicted"` (removed to make room). `delete` and replacing a key still call nothing.
6. **`purge() -> int`**: removes expired entries (as in 4) and returns how many it removed.
7. **`stats() -> dict`**: `{"hits": h, "misses": m, "evictions": e, "expirations": x}`, counted since
   the cache was created. A `get` that returns a stored value is a hit and any other `get` is a miss
   (`in` counts neither). `evictions` counts entries removed to make room; `expirations` counts expired
   entries removed.
