"""Tests for unified strategy auto-stop helpers."""

from app.services.strategy_lifecycle import is_fatal_exchange_error


def test_binance_auth_fatal():
    assert is_fatal_exchange_error('Binance HTTP 401: {"code":-2015,"msg":"Invalid API-key"}')


def test_ibkr_connection_fatal():
    assert is_fatal_exchange_error("Connect call failed ('127.0.0.1', 7497)")


def test_bitget_ip_fatal():
    assert is_fatal_exchange_error("Bitget error 40018: Invalid IP")


def test_transient_not_fatal():
    assert not is_fatal_exchange_error("timeout waiting for response")
