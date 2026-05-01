"""
Thread-safe TTL cache with LRU eviction.

Used by /api/weather to avoid re-hitting NWS for points the user clicked
within the last few minutes. Sub-50ms cache hit replaces ~1.5–3s upstream
round-trip; meaningful for SRS §4.1 Reliability under repeat traffic.

Implementation notes:
    - `OrderedDict` + a `threading.Lock` is enough for our read/write
      volume. We're not optimizing for high-concurrency; we're optimizing
      for "no race conditions when Flask happens to run multi-threaded
      under a production WSGI server."
    - `time.monotonic()` for TTL math — wall-clock jumps (NTP correction,
      DST transitions) wouldn't expire entries early or late.
    - Cache reports `hits` / `misses` / `size` via `.stats()` so the
      /api/cache/stats endpoint can render it without extra plumbing.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """Bounded TTL cache with LRU eviction.

    The cache stores `(value, expires_at_monotonic)` tuples. `get()` lazily
    evicts expired entries; `set()` evicts the least-recently-used entry
    when at capacity.
    """

    def __init__(self, ttl_seconds: float, max_size: int = 1000) -> None:
        self.ttl = float(ttl_seconds)
        self.max_size = int(max_size)
        self._data: OrderedDict[Any, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> Any | None:
        """Return the cached value or None if missing/expired."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._data[key]
                self.misses += 1
                return None
            # Touch for LRU
            self._data.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: Any, value: Any) -> None:
        """Insert or update an entry. Evicts LRU when over capacity."""
        with self._lock:
            self._data[key] = (value, time.monotonic() + self.ttl)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        """Wipe everything. Resets hit/miss counters."""
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        """Snapshot for /api/cache/stats."""
        with self._lock:
            total = self.hits + self.misses
            return {
                "hits":        self.hits,
                "misses":      self.misses,
                "size":        len(self._data),
                "max_size":    self.max_size,
                "ttl_seconds": self.ttl,
                "hit_rate":    (self.hits / total) if total else 0.0,
            }
