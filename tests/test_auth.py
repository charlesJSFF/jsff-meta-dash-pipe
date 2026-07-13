import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction")
)

from auth import PageTokenLookupError, get_page_access_token  # noqa: E402

ME_ACCOUNTS_RESPONSE = {
    "data": [
        {"id": "page-123", "name": "J. Stockard Fly Fishing", "access_token": "page-token-abc"},
        {"id": "page-456", "name": "Other Page", "access_token": "page-token-xyz"},
    ],
    "paging": {},
}


def test_returns_matching_page_access_token(monkeypatch):
    monkeypatch.setattr("auth._http_get_json", lambda url: ME_ACCOUNTS_RESPONSE)

    token = get_page_access_token("system-user-token", "page-123")

    assert token == "page-token-abc"


def test_falls_back_to_system_user_token_when_page_not_found(monkeypatch, capsys):
    monkeypatch.setattr("auth._http_get_json", lambda url: ME_ACCOUNTS_RESPONSE)

    token = get_page_access_token("system-user-token", "page-999")

    assert token == "system-user-token"
    assert "Page not found" in capsys.readouterr().out


def test_raises_on_me_accounts_failure(monkeypatch):
    def fake_http_get_json(url):
        raise PageTokenLookupError("/me/accounts request failed: boom")

    monkeypatch.setattr("auth._http_get_json", fake_http_get_json)

    with pytest.raises(PageTokenLookupError):
        get_page_access_token("system-user-token", "page-123")
