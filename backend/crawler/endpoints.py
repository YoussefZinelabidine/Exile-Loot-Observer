"""The hard-coded table of GGG endpoints the crawler may call.

The rate-limit policy and the budget cost are derived from the endpoint, never supplied by
the caller. Any other host, scheme, port or path is refused before anything is sent.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from urllib.parse import urlsplit

import httpx

from backend.crawler.constants import POLICY_CHARACTER, POLICY_ITEMS, POLICY_LADDER_VIEW
from backend.crawler.errors import EndpointNotAllowedError

ALLOWED_HOST: Final[str] = "www.pathofexile.com"


@dataclass(frozen=True)
class Endpoint:
    """Rate-limit policy of an endpoint and whether a request costs one budget unit."""

    policy: str
    charges_budget: bool = False


ENDPOINTS: Final[Mapping[str, Endpoint]] = MappingProxyType(
    {
        "/api/leagues": Endpoint(POLICY_LADDER_VIEW),
        "/api/ladders": Endpoint(POLICY_LADDER_VIEW),
        "/character-window/get-characters": Endpoint(POLICY_CHARACTER),
        "/character-window/get-passive-skills": Endpoint(POLICY_CHARACTER),
        "/character-window/get-items": Endpoint(POLICY_ITEMS, charges_budget=True),
    }
)


def resolve_endpoint(url: str) -> Endpoint:
    """Return the table entry for `url`, or raise EndpointNotAllowedError.

    Requires https, host `www.pathofexile.com`, the default port, no credentials in the URL
    and an exact path match from `ENDPOINTS`. The query string is not part of the match.
    """
    try:
        parsed = httpx.URL(url)
        scheme = parsed.scheme
        host = parsed.host.lower()  # IDNA problems surface here
        port = parsed.port
        path = parsed.path
        # `userinfo` or any "@" in the netloc (also catches an empty `https://@host`)
        has_userinfo = bool(parsed.userinfo) or "@" in urlsplit(url).netloc
    except Exception as exc:  # InvalidURL, IDNA/UnicodeError, ValueError, ...
        raise EndpointNotAllowedError(f"Invalid URL ({type(exc).__name__})") from exc
    if scheme != "https" or host != ALLOWED_HOST or port is not None or has_userinfo:
        raise EndpointNotAllowedError(f"Host not allowed: {host!r}")
    endpoint = ENDPOINTS.get(path)
    if endpoint is None:
        raise EndpointNotAllowedError(f"Path not allowed: {path!r}")
    return endpoint
