"""
港股/H股数据源 — 多层 fallback

有 TWELVE_DATA_API_KEY:
  所有周期 → Twelve Data（主） → 腾讯日/周线 → yfinance → AkShare

无 API Key:
  分钟/小时 → yfinance → AkShare
  日/周线 → 腾讯 fqkline → yfinance → AkShare
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional

from app.data_providers import safe_float
from app.data_sources.base import BaseDataSource
from app.data_sources.tencent import normalize_hk_code, fetch_quote, parse_quote_to_ticker, fetch_kline, tencent_kline_rows_to_dicts
from app.data_sources.yahoo_quote import fetch_yahoo_chart_quote, hk_yahoo_symbol
from app.data_sources.asia_stock_kline import (
    normalize_chart_timeframe,
    fetch_twelvedata_klines,
    fetch_yfinance_klines,
    fetch_akshare_minute_klines,
    fetch_akshare_weekly_klines,
    yf_symbol_from_tencent,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _ticker_from_yahoo(symbol: str) -> Optional[Dict[str, Any]]:
    yahoo = fetch_yahoo_chart_quote(hk_yahoo_symbol(symbol))
    if not yahoo or safe_float(yahoo.get("last")) <= 0:
        return None
    return {
        "last": yahoo.get("last", 0),
        "change": yahoo.get("change", 0),
        "changePercent": yahoo.get("changePercent", 0),
        "high": yahoo.get("last", 0),
        "low": yahoo.get("last", 0),
        "open": yahoo.get("last", 0),
        "previousClose": yahoo.get("previousClose", 0),
        "symbol": normalize_hk_code(symbol),
    }


def _ticker_from_yfinance(tencent_code: str) -> Optional[Dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError:
        return None

    yf_sym = yf_symbol_from_tencent(tencent_code, is_hk=True)
    try:
        ticker = yf.Ticker(yf_sym)
        try:
            fast_info = ticker.fast_info
            last_price = fast_info.get("lastPrice") or fast_info.get("last_price")
            prev_close = (
                fast_info.get("previousClose")
                or fast_info.get("previous_close")
                or fast_info.get("regularMarketPreviousClose")
            )
            if last_price:
                last_price = float(last_price)
                prev_close = float(prev_close) if prev_close else 0.0
                change = (last_price - prev_close) if prev_close else 0.0
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                return {
                    "last": last_price,
                    "change": round(change, 4),
                    "changePercent": round(change_pct, 2),
                    "high": float(fast_info.get("dayHigh") or fast_info.get("day_high") or last_price),
                    "low": float(fast_info.get("dayLow") or fast_info.get("day_low") or last_price),
                    "open": float(fast_info.get("open") or fast_info.get("regularMarketOpen") or last_price),
                    "previousClose": prev_close,
                    "symbol": tencent_code,
                }
        except Exception as e:
            logger.debug("yfinance fast_info failed for HK %s: %s", yf_sym, e)
    except Exception as e:
        logger.debug("yfinance HK ticker failed for %s: %s", yf_sym, e)
    return None


class HKStockDataSource(BaseDataSource):
    """港股/H股数据源（TwelveData + Tencent + yfinance + AkShare）"""

    name = "HKStock/multi-source"

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        code = normalize_hk_code(symbol)
        parts = fetch_quote(code)
        if parts:
            t = parse_quote_to_ticker(parts)
            if safe_float(t.get("last")) > 0:
                return {
                    "last": t.get("last", 0),
                    "change": t.get("change", 0),
                    "changePercent": t.get("changePercent", 0),
                    "high": t.get("high", 0),
                    "low": t.get("low", 0),
                    "open": t.get("open", 0),
                    "previousClose": t.get("previousClose", 0),
                    "name": t.get("name", ""),
                    "symbol": code,
                }

        for fallback in (
            lambda: _ticker_from_yahoo(symbol),
            lambda: _ticker_from_yfinance(code),
        ):
            try:
                row = fallback()
                if row and safe_float(row.get("last")) > 0:
                    return row
            except Exception as e:
                logger.debug("HK ticker fallback failed for %s: %s", code, e)

        return {"last": 0, "symbol": code}

    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        code = normalize_hk_code(symbol)
        tf = normalize_chart_timeframe(timeframe)
        lim = max(int(limit or 300), 1)

        # Tier 1: Twelve Data (paid, most reliable)
        rows = fetch_twelvedata_klines(
            is_hk=True, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
        )
        if rows:
            return self.filter_and_limit(
                rows,
                limit=lim,
                before_time=before_time,
                after_time=after_time,
                truncate=(after_time is None),
            )

        # Tier 2: Tencent for daily/weekly (fast, free)
        if tf in ("1D", "1W"):
            tf_map = {"1D": "day", "1W": "week"}
            period = tf_map.get(tf, "day")
            raw_rows = fetch_kline(code, period=period, count=lim, adj="qfq")
            out = tencent_kline_rows_to_dicts(raw_rows)
            if out:
                return self.filter_and_limit(
                    out,
                    limit=lim,
                    before_time=before_time,
                    after_time=after_time,
                    truncate=(after_time is None),
                )

        # Tier 3: yfinance (works when Yahoo not rate-limited)
        rows = fetch_yfinance_klines(
            is_hk=True, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
        )
        if rows:
            return self.filter_and_limit(
                rows,
                limit=lim,
                before_time=before_time,
                after_time=after_time,
                truncate=(after_time is None),
            )

        # Tier 4: AkShare (fragile overseas, last resort)
        if tf in ("1m", "5m", "15m", "30m", "1H", "4H"):
            rows = fetch_akshare_minute_klines(
                is_hk=True, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
            )
        elif tf == "1W":
            rows = fetch_akshare_weekly_klines(
                is_hk=True, tencent_code=code, limit=lim, before_time=before_time
            )
        else:
            rows = []

        return self.filter_and_limit(
            rows,
            limit=lim,
            before_time=before_time,
            after_time=after_time,
            truncate=(after_time is None),
        )
