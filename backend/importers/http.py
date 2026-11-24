"""HTTP client for the data downloads (RePoE, poe.re, GitHub).

User-Agent format: shared/user-agents.md. Values come from settings, never from code.
Tests inject an ``httpx.MockTransport``; no test ever uses a real transport.
"""

from importlib import metadata

import httpx

from backend.importers.errors import ImporterError, MissingContactInfoError

TIMEOUT_S = 60.0


def package_version() -> str:
    try:
        return metadata.version("elo-backend")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def build_data_user_agent(
    *, contact_email: str | None, project_url: str | None, version: str | None = None
) -> str:
    """``ELO/<v> (+<url>; contact: <email>)``; without an email ``ELO/<v> (+<url>)``.

    Raises MissingContactInfoError when the project URL is missing (the source is skipped).
    """
    url = (project_url or "").strip()
    email = (contact_email or "").strip()
    if not url:
        raise MissingContactInfoError("ELO_PROJECT_URL is not set; not contacting data hosts")
    version = version or package_version()
    if email:
        return f"ELO/{version} (+{url}; contact: {email})"
    return f"ELO/{version} (+{url})"


def make_client(user_agent: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent},
        timeout=TIMEOUT_S,
        follow_redirects=True,
        transport=transport,
    )


def get_bytes(client: httpx.Client, url: str) -> bytes:
    """GET ``url`` and return the body; any failure becomes an ImporterError."""
    try:
        response = client.get(url)
        response.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise ImporterError(f"download failed: {url} ({type(exc).__name__})") from exc
    return response.content
