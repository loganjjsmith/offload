from solution import LRUCache


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _cache(capacity=3, ttl=None):
    clock, events = Clock(), []
    cache = LRUCache(capacity, on_evict=lambda k, v, why: events.append((k, v, why)), ttl=ttl, clock=clock)
    return cache, clock, events


# Behaviour kept from the original module.

def test_capacity_validated():
    for bad in (0, -2):
        try:
            LRUCache(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"capacity {bad} accepted")


def test_get_put_basic():
    c = LRUCache(2)
    c.put("a", 1)
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.get("b", "d") == "d"


def test_lru_eviction_order():
    c, _, events = _cache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")
    c.put("c", 3)
    assert c.keys() == ["a", "c"]
    assert events == [("b", 2, "evicted")]


def test_replace_moves_to_end_without_callback():
    c, _, events = _cache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 10)
    assert c.keys() == ["b", "a"]
    assert c.get("a") == 10
    assert events == []


def test_delete_contains_len():
    c, _, events = _cache()
    c.put("a", 1)
    c.put("b", None)
    assert "b" in c and len(c) == 2
    assert c.delete("a") is True
    assert c.delete("a") is False
    assert c.delete("b") is True
    assert len(c) == 0 and events == []


def test_works_without_callback():
    c = LRUCache(1)
    c.put("a", 1)
    c.put("b", 2)
    assert c.keys() == ["b"]


def test_default_clock_is_real_time():
    c = LRUCache(2, ttl=60)
    c.put("a", 1)
    assert c.get("a") == 1


# Expiry.

def test_ttl_validated():
    for bad in (0, -1):
        try:
            LRUCache(2, ttl=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"ttl {bad} accepted")
        c = LRUCache(2)
        try:
            c.put("a", 1, ttl=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"put ttl {bad} accepted")


def test_entry_expires():
    c, clock, events = _cache(ttl=10)
    c.put("a", 1)
    clock.t += 9.5
    assert c.get("a") == 1
    clock.t += 0.5
    assert c.get("a") is None
    assert events == [("a", 1, "expired")]


def test_expired_at_exact_time():
    c, clock, _ = _cache(ttl=5)
    c.put("a", 1)
    clock.t += 5
    assert "a" not in c


def test_no_ttl_never_expires():
    c, clock, _ = _cache()
    c.put("a", 1)
    clock.t += 1e9
    assert c.get("a") == 1


def test_per_entry_ttl_overrides():
    c, clock, _ = _cache(ttl=100)
    c.put("short", 1, ttl=1)
    c.put("long", 2)
    clock.t += 2
    assert c.keys() == ["long"]


def test_per_entry_ttl_without_cache_ttl():
    c, clock, _ = _cache()
    c.put("a", 1, ttl=3)
    c.put("b", 2)
    clock.t += 3
    assert c.keys() == ["b"]


def test_get_does_not_extend():
    c, clock, _ = _cache(ttl=10)
    c.put("a", 1)
    clock.t += 6
    c.get("a")
    clock.t += 6
    assert c.get("a") is None


def test_replace_resets_expiry():
    c, clock, _ = _cache(ttl=10)
    c.put("a", 1)
    clock.t += 6
    c.put("a", 2)
    clock.t += 6
    assert c.get("a") == 2


def test_expired_hidden_from_len_keys_contains():
    c, clock, _ = _cache(ttl=10)
    c.put("a", 1)
    c.put("b", 2, ttl=100)
    clock.t += 20
    assert len(c) == 1 and c.keys() == ["b"] and "a" not in c


def test_expired_removed_in_lru_order():
    c, clock, events = _cache(capacity=5, ttl=10)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3, ttl=100)
    c.put("d", 4)
    c.get("a")
    clock.t += 50
    c.purge()
    assert events == [("b", 2, "expired"), ("d", 4, "expired"), ("a", 1, "expired")]


def test_expired_removed_before_eviction():
    c, clock, events = _cache(capacity=2)
    c.put("live", 1)
    c.put("old", 2, ttl=1)
    clock.t += 2
    c.put("new", 3)
    assert c.keys() == ["live", "new"]
    assert events == [("old", 2, "expired")]


def test_put_over_expired_key_is_new_entry():
    c, clock, events = _cache(ttl=1)
    c.put("a", 1)
    clock.t += 5
    c.put("a", 2)
    assert events == [("a", 1, "expired")]
    assert c.get("a") == 2


def test_delete_expired_returns_false():
    c, clock, events = _cache(ttl=1)
    c.put("a", 1)
    clock.t += 1
    assert c.delete("a") is False
    assert events == [("a", 1, "expired")]


def test_purge_returns_count():
    c, clock, _ = _cache(capacity=5, ttl=10)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3, ttl=50)
    clock.t += 11
    assert c.purge() == 2
    assert c.purge() == 0


def test_purge_without_callback():
    clock = Clock()
    c = LRUCache(3, ttl=1, clock=clock)
    c.put("a", 1)
    clock.t += 2
    assert c.purge() == 1


# Statistics.

def test_stats_start_at_zero():
    c, _, _ = _cache()
    assert c.stats() == {"hits": 0, "misses": 0, "evictions": 0, "expirations": 0}


def test_stats_hits_and_misses():
    c, _, _ = _cache()
    c.put("a", 1)
    c.get("a")
    c.get("a")
    c.get("zz")
    assert "a" in c and "zz" not in c
    s = c.stats()
    assert (s["hits"], s["misses"]) == (2, 1)


def test_stats_expired_get_is_miss():
    c, clock, _ = _cache(ttl=1)
    c.put("a", 1)
    clock.t += 2
    c.get("a")
    assert c.stats() == {"hits": 0, "misses": 1, "evictions": 0, "expirations": 1}


def test_stats_evictions_and_expirations():
    c, clock, _ = _cache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)
    c.put("d", 4, ttl=1)
    clock.t += 1
    c.purge()
    s = c.stats()
    assert (s["evictions"], s["expirations"]) == (2, 1)


def test_stats_counts_expiry_seen_by_stats_itself():
    c, clock, _ = _cache(ttl=1)
    c.put("a", 1)
    clock.t += 1
    assert c.stats()["expirations"] == 1
