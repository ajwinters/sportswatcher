"""
Rate limiter for API calls using token bucket algorithm.
"""

import time
from collections import deque
from threading import Lock
from typing import Optional


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    pass


class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    Tracks both per-minute and per-day limits to stay within
    free tier constraints.
    """

    def __init__(
        self,
        requests_per_minute: int = 10,
        requests_per_day: int = 100,
    ):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests per minute
            requests_per_day: Maximum requests per day
        """
        self.rpm = requests_per_minute
        self.rpd = requests_per_day
        self.minute_window: deque = deque()
        self.day_window: deque = deque()
        self.lock = Lock()

    def _clean_old_entries(self, now: float) -> None:
        """Remove expired entries from tracking windows."""
        minute_ago = now - 60
        day_ago = now - 86400

        while self.minute_window and self.minute_window[0] < minute_ago:
            self.minute_window.popleft()

        while self.day_window and self.day_window[0] < day_ago:
            self.day_window.popleft()

    def get_remaining_requests(self) -> dict:
        """
        Get remaining requests for each limit.

        Returns:
            Dictionary with 'minute' and 'day' remaining counts
        """
        with self.lock:
            now = time.time()
            self._clean_old_entries(now)

            return {
                "minute": max(0, self.rpm - len(self.minute_window)),
                "day": max(0, self.rpd - len(self.day_window)),
            }

    def can_make_request(self) -> bool:
        """Check if a request can be made without blocking."""
        remaining = self.get_remaining_requests()
        return remaining["minute"] > 0 and remaining["day"] > 0

    def wait_if_needed(self, raise_on_daily_limit: bool = True) -> Optional[float]:
        """
        Block until request can be made within rate limits.

        Args:
            raise_on_daily_limit: If True, raise exception when daily limit reached

        Returns:
            Time waited in seconds, or None if no wait needed

        Raises:
            RateLimitExceeded: If daily limit is reached and raise_on_daily_limit is True
        """
        with self.lock:
            now = time.time()
            self._clean_old_entries(now)

            # Check daily limit first
            if len(self.day_window) >= self.rpd:
                if raise_on_daily_limit:
                    raise RateLimitExceeded(
                        f"Daily API limit of {self.rpd} requests reached. "
                        "Resets in 24 hours."
                    )
                # Calculate time until oldest request expires
                wait_time = self.day_window[0] + 86400 - now
                return wait_time

            # Check minute limit
            waited = None
            if len(self.minute_window) >= self.rpm:
                # Wait until oldest request in minute window expires
                sleep_time = self.minute_window[0] + 60 - now
                if sleep_time > 0:
                    # Release lock while sleeping
                    self.lock.release()
                    try:
                        time.sleep(sleep_time)
                        waited = sleep_time
                    finally:
                        self.lock.acquire()
                    # Re-clean after sleeping
                    now = time.time()
                    self._clean_old_entries(now)

            # Record this request
            now = time.time()
            self.minute_window.append(now)
            self.day_window.append(now)

            return waited

    def record_request(self) -> None:
        """Manually record a request (for external tracking)."""
        with self.lock:
            now = time.time()
            self._clean_old_entries(now)
            self.minute_window.append(now)
            self.day_window.append(now)

    def reset(self) -> None:
        """Reset all tracking (for testing)."""
        with self.lock:
            self.minute_window.clear()
            self.day_window.clear()


# Global rate limiter instance for Tennis API
_tennis_api_limiter: Optional[RateLimiter] = None


def get_tennis_api_limiter() -> RateLimiter:
    """Get the global Tennis API rate limiter."""
    global _tennis_api_limiter
    if _tennis_api_limiter is None:
        from config.settings import get_settings

        settings = get_settings()
        _tennis_api_limiter = RateLimiter(
            requests_per_minute=settings.tennis_api_requests_per_minute,
            requests_per_day=settings.tennis_api_requests_per_day,
        )
    return _tennis_api_limiter
