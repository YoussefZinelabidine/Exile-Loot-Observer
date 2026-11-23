"""Safe HTTP client: the only way the crawler talks to GGG."""

from collections.abc import Mapping

import httpx


class SafeHttpClient:
    """Synchronous wrapper around `httpx.Client` (sync vs async is provisional).

    Order of checks for each request:
    1. circuit breaker
    2. daily budget (character endpoints only)
    3. rate limiter
    4. the request
    5. update the limiter from response headers
    6. on 429, trip the breaker
    """

    def get(
        self,
        url: str,
        *,
        policy: str,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Send a GET request under the safety checks listed in the class docstring."""
        raise NotImplementedError("Phase 1")
