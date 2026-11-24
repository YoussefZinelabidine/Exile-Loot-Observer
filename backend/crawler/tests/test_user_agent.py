import pytest

from backend.crawler.errors import MissingContactInfoError
from backend.crawler.user_agent import build_user_agent


def test_exact_format() -> None:
    ua = build_user_agent(
        "1.2.3", contact_email="project@example.org", project_url="https://example.org/elo"
    )
    assert ua == "ELO/1.2.3 (+https://example.org/elo; contact: project@example.org)"


@pytest.mark.parametrize(
    ("email", "url"),
    [(None, "https://x.org"), ("a@b.c", None), ("", "https://x.org"), ("a@b.c", "  ")],
)
def test_refuses_when_contact_info_missing(email, url) -> None:
    with pytest.raises(MissingContactInfoError):
        build_user_agent("1.0", contact_email=email, project_url=url)
