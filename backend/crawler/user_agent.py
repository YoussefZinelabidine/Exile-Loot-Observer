"""User-Agent builder (format fixed in shared/user-agents.md)."""

from backend.crawler.errors import MissingContactInfoError


def build_user_agent(version: str, *, contact_email: str | None, project_url: str | None) -> str:
    """Return `ELO/<version> (+<project_url>; contact: <email>)`.

    Raises MissingContactInfoError if the contact email or project URL is empty or blank:
    no GGG request may be sent without both.
    """
    email = (contact_email or "").strip()
    url = (project_url or "").strip()
    if not email or not url:
        raise MissingContactInfoError(
            "ELO_CONTACT_EMAIL and ELO_PROJECT_URL must both be set to contact GGG"
        )
    return f"ELO/{version} (+{url}; contact: {email})"
