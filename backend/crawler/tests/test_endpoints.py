import pytest

from backend.crawler.constants import POLICY_CHARACTER, POLICY_ITEMS, POLICY_LADDER_VIEW
from backend.crawler.endpoints import ENDPOINTS, Endpoint, resolve_endpoint
from backend.crawler.errors import CrawlerError, EndpointNotAllowedError

H = "https://www.pathofexile.com"


@pytest.mark.parametrize(
    ("path", "policy", "charges"),
    [
        ("/api/leagues", POLICY_LADDER_VIEW, False),
        ("/api/ladders", POLICY_LADDER_VIEW, False),
        ("/character-window/get-characters", POLICY_CHARACTER, False),
        ("/character-window/get-passive-skills", POLICY_CHARACTER, False),
        ("/character-window/get-items", POLICY_ITEMS, True),
    ],
)
def test_table(path, policy, charges) -> None:
    assert resolve_endpoint(H + path) == Endpoint(policy, charges)
    assert resolve_endpoint(H + path + "?accountName=x&character=y") == Endpoint(policy, charges)


def test_table_is_exactly_five_and_read_only() -> None:
    assert len(ENDPOINTS) == 5
    with pytest.raises(TypeError):
        ENDPOINTS["/x"] = Endpoint("p")  # type: ignore[index]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/leagues",
        "https://pathofexile.com/api/leagues",
        "https://www.pathofexile.com.evil.test/api/leagues",
        "https://evil.test@www.pathofexile.com/api/leagues",
        "https://@www.pathofexile.com/api/leagues",
        "https://:@www.pathofexile.com/api/leagues",
        "http://www.pathofexile.com/api/leagues",
        "https://www.pathofexile.com:8443/api/leagues",
        "https://www.pathofexile.com/api/other",
        "https://www.pathofexile.com/api/leagues/",
        "https://www.pathofexile.com/",
        "https://www.pathofexile.com/api/trade/search",
        "not a url",
        "",
    ],
)
def test_everything_else_is_refused(url) -> None:
    with pytest.raises(CrawlerError):
        resolve_endpoint(url)
    with pytest.raises(EndpointNotAllowedError):
        resolve_endpoint(url)


def test_any_url_parser_exception_means_refusal(monkeypatch) -> None:
    import httpx

    def boom(url):
        raise UnicodeError("label too long")

    monkeypatch.setattr(httpx, "URL", boom)
    with pytest.raises(EndpointNotAllowedError):
        resolve_endpoint(H + "/api/leagues")


@pytest.mark.parametrize("url", ["https://" + "a" * 300 + ".com/api/leagues", "https://\u2025/x"])
def test_odd_hostnames_are_refused(url) -> None:
    with pytest.raises(CrawlerError):
        resolve_endpoint(url)


def test_host_idna_error_is_refused(monkeypatch) -> None:
    import httpx

    class Bad:
        scheme = "https"
        port = None
        path = "/api/leagues"
        userinfo = b""

        @property
        def host(self):
            raise UnicodeError("idna")

    monkeypatch.setattr(httpx, "URL", lambda url: Bad())
    with pytest.raises(EndpointNotAllowedError):
        resolve_endpoint(H + "/api/leagues")
