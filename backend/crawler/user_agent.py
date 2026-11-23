"""User-Agent builder."""


def build_user_agent(version: str, *, contact_email: str | None, project_url: str | None) -> str:
    """Build the User-Agent string.

    The final format is not agreed yet (open question). It must name the app
    and a contact email.
    """
    raise NotImplementedError("Phase 1")
