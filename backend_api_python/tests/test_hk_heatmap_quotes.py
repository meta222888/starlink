"""Tests for HK stock quote fallbacks used by heatmap."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.data_sources.hk_stock import HKStockDataSource
from app.data_sources.yahoo_quote import fetch_yahoo_chart_quote, hk_yahoo_symbol
from app.data_providers.opportunities import _fetch_single_local_stock_quote


def test_hk_yahoo_symbol_normalizes_codes():
    assert hk_yahoo_symbol("00700") == "0700.HK"
    assert hk_yahoo_symbol("700") == "0700.HK"
    assert hk_yahoo_symbol("0700.HK") == "0700.HK"


@patch("app.data_sources.hk_stock.fetch_quote", return_value=None)
@patch("app.data_sources.hk_stock.fetch_yahoo_chart_quote")
def test_hk_get_ticker_falls_back_to_yahoo(mock_yahoo, _mock_tencent):
    mock_yahoo.return_value = {
        "last": 457.2,
        "change": -8.4,
        "changePercent": -1.8,
        "previousClose": 465.6,
    }
    row = HKStockDataSource().get_ticker("00700")
    assert row["last"] == 457.2
    assert row["changePercent"] == -1.8
    mock_yahoo.assert_called_once_with("0700.HK")


@patch("app.data_sources.hk_stock.fetch_quote")
@patch("app.data_sources.hk_stock.fetch_yahoo_chart_quote", return_value=None)
@patch("app.data_sources.hk_stock._ticker_from_yfinance")
def test_hk_get_ticker_prefers_tencent(mock_yfinance, _mock_yahoo, mock_tencent):
    mock_tencent.return_value = ["x"] * 6
    with patch("app.data_sources.hk_stock.parse_quote_to_ticker") as mock_parse:
        mock_parse.return_value = {
            "last": 460.0,
            "change": 1.0,
            "changePercent": 0.22,
            "high": 461.0,
            "low": 458.0,
            "open": 459.0,
            "previousClose": 459.0,
            "name": "腾讯控股",
        }
        row = HKStockDataSource().get_ticker("00700")
    assert row["last"] == 460.0
    mock_yfinance.assert_not_called()


@patch("app.data_providers.opportunities._fetch_yfinance_hk_quote", return_value=None)
@patch("app.data_sources.factory.DataSourceFactory.get_source")
@patch("app.data_providers.opportunities._fetch_yahoo_hk_chart_quote")
def test_hk_opportunity_quote_uses_yahoo_first(mock_yahoo, mock_get_source, _mock_yf):
    mock_yahoo.return_value = {"last": 100.5, "changePercent": 1.2}
    row = _fetch_single_local_stock_quote(
        "HKStock",
        {"symbol": "00700", "name": "腾讯控股"},
        fast=True,
    )
    assert row is not None
    assert row["price"] == 100.5
    assert row["change"] == 1.2
    mock_get_source.assert_not_called()


@patch("app.data_sources.yahoo_quote.requests.get")
def test_fetch_yahoo_chart_quote_parses_meta(mock_get):
    mock_get.return_value.json.return_value = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": 457.2,
                        "chartPreviousClose": 465.6,
                    }
                }
            ]
        }
    }
    mock_get.return_value.raise_for_status = lambda: None
    row = fetch_yahoo_chart_quote("0700.HK")
    assert row is not None
    assert row["last"] == 457.2
    assert row["changePercent"] == pytest.approx(-1.8, abs=0.05)
