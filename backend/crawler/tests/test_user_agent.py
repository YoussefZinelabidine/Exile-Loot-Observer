import pytest


@pytest.mark.skip(reason="Phase 1")
def test_build_user_agent_names_app_and_contact() -> None:
    """Will check: the User-Agent names the app and includes the contact email."""
