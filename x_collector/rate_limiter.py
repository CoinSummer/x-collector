"""Adaptive rate limiter for X API.

This module implements an adaptive rate limiting strategy based on
X/Twitter API v2's rate limit headers:
- x-rate-limit-remaining: Requests remaining in current window
- x-rate-limit-reset: Unix timestamp when window resets

Strategy:
1. Normal mode: Wait `safe_delay` between requests
2. Slow mode: When remaining < safe_threshold, use `slow_delay`
3. Critical mode: When remaining < critical_threshold, wait for reset

Example:
    ```python
    config = RateLimitConfig(safe_delay=0.7, slow_delay=2.0)
    limiter = RateLimiter(config)

    # Update after each API response
    limiter.update(remaining=50, reset_time=1699999999)

    # Wait before next request
    await limiter.wait()
    ```
"""

import asyncio
import time
import logging
from dataclasses import dataclass
from typing import Optional

from x_collector.config import RateLimitConfig


logger = logging.getLogger(__name__)


@dataclass
class RateLimitState:
    """Current rate limit state."""
    remaining: int = 1500
    reset_time: int = 0
    last_request_time: float = 0.0

    @property
    def seconds_until_reset(self) -> int:
        """Seconds until rate limit resets."""
        return max(0, self.reset_time - int(time.time()))

    @property
    def is_critical(self) -> bool:
        """Check if we're at critical rate limit."""
        return self.remaining < 3


class RateLimiter:
    """Adaptive rate limiter for X API.

    Automatically adjusts request delays based on remaining rate limit quota.

    Attributes:
        config: Rate limit configuration
        state: Current rate limit state
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        """Initialize rate limiter.

        Args:
            config: Rate limit configuration (uses defaults if None)
        """
        self.config = config or RateLimitConfig()
        self.state = RateLimitState()
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0

    def update(self, remaining: int, reset_time: int) -> None:
        """Update rate limit state from API response headers.

        Call this after each successful API request with values from:
        - x-rate-limit-remaining header
        - x-rate-limit-reset header

        Args:
            remaining: Requests remaining in current window
            reset_time: Unix timestamp when window resets
        """
        self.state.remaining = remaining
        self.state.reset_time = reset_time
        self.state.last_request_time = time.time()
        self._total_requests += 1

    async def wait(self) -> float:
        """Wait appropriate amount of time before next request.

        Implements adaptive rate limiting:
        1. Critical: remaining < critical_threshold -> wait for reset
        2. Slow: remaining < safe_threshold -> use slow_delay
        3. Normal: use safe_delay

        Returns:
            Actual seconds waited
        """
        current_time = time.time()
        wait_time = 0.0

        if self.state.remaining < self.config.critical_threshold:
            # Critical: wait for rate limit reset
            wait_time = max(1, self.state.reset_time - int(current_time) + 5)
            logger.warning(
                f"Rate limit critical (remaining={self.state.remaining}), "
                f"waiting {wait_time:.1f}s for reset"
            )
        elif self.state.remaining < self.config.safe_threshold:
            # Slow mode: longer delays
            wait_time = self.config.slow_delay
            logger.info(
                f"Rate limit low (remaining={self.state.remaining}), "
                f"using slow delay ({wait_time}s)"
            )
        else:
            # Normal mode: standard delay
            wait_time = self.config.safe_delay

        if wait_time > 0:
            await asyncio.sleep(wait_time)
            self._total_waits += 1
            self._total_wait_time += wait_time

        return wait_time

    async def wait_for_reset(self) -> float:
        """Wait until rate limit resets.

        Use this after receiving a 429 response.

        Returns:
            Seconds waited
        """
        wait_time = max(60, self.state.seconds_until_reset + 5)
        logger.warning(f"Rate limited (429), waiting {wait_time}s for reset")
        await asyncio.sleep(wait_time)
        self._total_wait_time += wait_time
        return wait_time

    @property
    def stats(self) -> dict:
        """Get rate limiter statistics.

        Returns:
            Dict with stats including total requests, waits, etc.
        """
        return {
            "total_requests": self._total_requests,
            "total_waits": self._total_waits,
            "total_wait_time": round(self._total_wait_time, 2),
            "current_remaining": self.state.remaining,
            "seconds_until_reset": self.state.seconds_until_reset,
        }

    def __repr__(self) -> str:
        return (
            f"RateLimiter(remaining={self.state.remaining}, "
            f"reset_in={self.state.seconds_until_reset}s)"
        )


class TokenBucketLimiter:
    """Token bucket rate limiter for smoother request distribution.

    This is an alternative to the adaptive limiter that provides
    more consistent request spacing.

    Args:
        rate: Requests per second
        burst: Maximum burst size (bucket capacity)
    """

    def __init__(self, rate: float = 1.5, burst: int = 10):
        """Initialize token bucket.

        Args:
            rate: Tokens (requests) per second
            burst: Maximum tokens in bucket
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Acquire a token, waiting if necessary.

        Returns:
            Seconds waited
        """
        async with self._lock:
            now = time.time()

            # Add tokens based on time elapsed
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now

            if self._tokens >= 1:
                self._tokens -= 1
                return 0.0

            # Need to wait for a token
            wait_time = (1 - self._tokens) / self.rate
            await asyncio.sleep(wait_time)
            self._tokens = 0
            self._last_update = time.time()
            return wait_time

    @property
    def available_tokens(self) -> float:
        """Current available tokens."""
        elapsed = time.time() - self._last_update
        return min(self.burst, self._tokens + elapsed * self.rate)
