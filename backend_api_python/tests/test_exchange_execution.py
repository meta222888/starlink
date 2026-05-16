"""Tests for exchange config resolution."""

from app.services import exchange_execution


def test_resolve_exchange_config_accepts_camel_case_credential_id(monkeypatch):
    def fake_load_credential_config(credential_id, user_id=1):
        assert credential_id == 7
        assert user_id == 42
        return {
            "exchange_id": "okx",
            "api_key": "from-credential",
            "secret_key": "from-credential-secret",
        }

    monkeypatch.setattr(exchange_execution, "_load_credential_config", fake_load_credential_config)

    resolved = exchange_execution.resolve_exchange_config(
        {
            "credentialId": 7,
            "market_type": "swap",
        },
        user_id=42,
    )

    assert resolved["credential_id"] == 7
    assert resolved["exchange_id"] == "okx"
    assert resolved["api_key"] == "from-credential"
    assert resolved["market_type"] == "swap"


def test_resolve_exchange_config_normalizes_camel_case_exchange_id():
    resolved = exchange_execution.resolve_exchange_config({"exchangeId": "coinbase_exchange"})

    assert resolved["exchange_id"] == "coinbaseexchange"
