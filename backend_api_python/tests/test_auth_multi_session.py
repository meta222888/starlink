"""Tests for multi-device JWT session behavior."""

from app.utils import auth


def test_verify_token_allows_older_token_version(monkeypatch):
    """A newer login must not invalidate an existing Web/App token."""
    token = auth.generate_token(
        user_id=123,
        username="multi_session_user",
        role="user",
        token_version=1,
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("token_version DB check should not run")

    monkeypatch.setattr(auth, "_verify_token_version", fail_if_called)

    payload = auth.verify_token(token)

    assert payload["user_id"] == 123
    assert payload["sub"] == "multi_session_user"
