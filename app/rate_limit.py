from dataclasses import dataclass
from threading import Lock
from time import time


@dataclass
class Bucket:
    count: int
    reset_at: float


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, Bucket] = {}
        self._lock = Lock()

    def allow(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        now = time()
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket or now >= bucket.reset_at:
                bucket = Bucket(count=0, reset_at=now + window_seconds)
                self._buckets[key] = bucket

            if bucket.count >= max_requests:
                retry_after = max(1, int(bucket.reset_at - now))
                return False, retry_after

            bucket.count += 1

            if len(self._buckets) > 10000:
                expired_keys = [k for k, v in self._buckets.items() if now >= v.reset_at]
                for expired_key in expired_keys:
                    self._buckets.pop(expired_key, None)

            return True, 0
