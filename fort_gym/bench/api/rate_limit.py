"""Simple in-process rate limiting utilities."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Dict, Optional, Tuple

from fastapi import Request


def _is_trusted_proxy(client_host: Optional[str]) -> bool:
    if not client_host:
        return False
    try:
        addr = ip_address(client_host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


def get_rate_limit_client_id(request: Request) -> str:
    """Return a stable client identifier for rate limiting.

    When `FORT_GYM_TRUST_PROXY=1` and the request originates from a trusted proxy
    (loopback/private), use `X-Forwarded-For` to identify the real client.
    """

    client_host = getattr(request.client, "host", None)
    if os.getenv("FORT_GYM_TRUST_PROXY", "0") == "1" and _is_trusted_proxy(client_host):
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
    return client_host or "unknown"


@dataclass
class _TokenBucket:
    capacity: float
    tokens: float
    refill_per_s: float
    updated_at: float

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        if elapsed <= 0.0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_s)
        self.updated_at = now

    def take(self, amount: float, now: float) -> Tuple[bool, float]:
        self.refill(now)
        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0.0
        missing = amount - self.tokens
        retry_after = missing / self.refill_per_s if self.refill_per_s > 0 else 60.0
        return False, max(0.1, retry_after)


class RateLimiter:
    """Thread-safe token bucket rate limiter keyed by (bucket_name, client_id)."""

    def __init__(self) -> None:
        self._buckets: Dict[Tuple[str, str], _TokenBucket] = {}
        self._lock = threading.Lock()

    def allow(self, bucket: str, client_id: str, *, capacity: int, refill_per_s: float) -> Tuple[bool, float]:
        now = time.monotonic()
        key = (bucket, client_id)
        with self._lock:
            existing = self._buckets.get(key)
            if existing is None or existing.capacity != float(capacity) or existing.refill_per_s != refill_per_s:
                existing = _TokenBucket(
                    capacity=float(capacity),
                    tokens=float(capacity),
                    refill_per_s=float(refill_per_s),
                    updated_at=now,
                )
                self._buckets[key] = existing
            ok, retry_after = existing.take(1.0, now)
            return ok, retry_after


DEFAULT_ADMIN_RPM = 120
DEFAULT_RUNS_RPM = 60


def get_rate_limit_config() -> Tuple[int, int]:
    admin_rpm = int(os.getenv("FORT_GYM_RATE_LIMIT_ADMIN_RPM", str(DEFAULT_ADMIN_RPM)))
    runs_rpm = int(os.getenv("FORT_GYM_RATE_LIMIT_RUNS_RPM", str(DEFAULT_RUNS_RPM)))
    return max(1, admin_rpm), max(1, runs_rpm)


__all__ = ["RateLimiter", "get_rate_limit_client_id", "get_rate_limit_config"]

