"""Unit tests for HTX swap API V5 helpers and client."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.live_trading import htx_v5
from app.services.live_trading.htx import HtxClient


def test_v5_ok_accepts_status_and_code():
    assert htx_v5.v5_ok({"status": "ok", "data": {}})
    assert htx_v5.v5_ok({"code": 200, "data": {}})
    assert not htx_v5.v5_ok({"code": 400, "message": "fail"})


def test_normalize_balance_from_v5_details():
    raw = {
        "code": 200,
        "data": {
            "equity": "1000",
            "available_margin": "800",
            "details": [
                {
                    "currency": "USDT",
                    "equity": "1000",
                    "available": "750",
                    "withdraw_available": "750",
                }
            ],
        },
    }
    out = htx_v5.normalize_balance(raw)
    assert out["status"] == "ok"
    assert len(out["data"]) == 1
    row = out["data"][0]
    assert row["margin_asset"] == "USDT"
    assert row["margin_available"] == 750.0
    assert row["margin_balance"] == 1000.0


def test_normalize_positions_list():
    raw = {
        "code": 200,
        "data": [
            {"contract_code": "BTC-USDT", "volume": 10, "direction": "buy"},
        ],
    }
    out = htx_v5.normalize_positions(raw)
    assert len(out["data"]) == 1
    assert out["data"][0]["contract_code"] == "BTC-USDT"
    assert out["data"][0]["volume"] == 10


def test_normalize_order_place():
    raw = {"status": "ok", "data": {"order_id": "12345", "order_id_str": "12345"}}
    out = htx_v5.normalize_order_place(raw)
    assert out["data"]["order_id_str"] == "12345"


def test_swap_balance_uses_v5_only():
    c = HtxClient(api_key="k", secret_key="s", market_type="swap")
    v5_raw = {
        "code": 200,
        "data": {
            "details": [{"currency": "USDT", "available": "100", "equity": "100"}],
        },
    }
    with patch.object(c, "_swap_v5_request", return_value=v5_raw) as mock_v5:
        out = c.get_balance()
    mock_v5.assert_called_once_with("GET", "/v5/account/balance")
    assert out["data"][0]["margin_available"] == 100.0


def test_place_swap_order_v5_only():
    c = HtxClient(api_key="k", secret_key="s", market_type="swap")
    body = {
        "contract_code": "BTC-USDT",
        "volume": 1,
        "direction": "buy",
        "offset": "open",
        "lever_rate": 5,
        "order_price_type": "opponent",
    }
    v5_resp = {"status": "ok", "data": {"order_id_str": "999"}}
    with patch.object(c, "_swap_v5_request", return_value=v5_resp):
        res = c._place_swap_order(body)
    assert res.exchange_order_id == "999"


def test_is_single_asset_mode_unavailable():
    assert htx_v5.is_single_asset_mode_unavailable(
        "The Single-Asset Collateral mode is temporarily unavailable."
    )
    assert not htx_v5.is_single_asset_mode_unavailable("insufficient margin")


def test_v5_request_retries_after_mode_switch():
    c = HtxClient(api_key="k", secret_key="s", market_type="swap")
    fail_raw = {"code": 400, "message": "The Single-Asset Collateral mode is temporarily unavailable."}
    ok_raw = {"code": 200, "data": {"details": [{"currency": "USDT", "available": "1", "equity": "1"}]}}
    with patch.object(c, "_swap_private_request_raw", side_effect=[fail_raw, ok_raw]):
        with patch.object(c, "_try_upgrade_to_multi_asset_mode", return_value=True):
            out = c._swap_v5_request("GET", "/v5/account/balance")
    assert htx_v5.v5_ok(out)


def test_cancel_order_swap_v5():
    c = HtxClient(api_key="k", secret_key="s", market_type="swap")
    with patch.object(c, "_swap_v5_request", return_value={"code": 200}) as mock_v5:
        c.cancel_order(symbol="BTC/USDT", order_id="123")
    mock_v5.assert_called_once()
    assert mock_v5.call_args[0][1] == "/v5/trade/cancel_order"
