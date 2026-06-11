"""Yahoo Finance chart API helpers for spot quotes (US / HK)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from app.data_providers import safe_float
from app.data_sources.tencent import normalize_hk_code
from app.utils.logger import get_logger

logger = get_logger(__name__)


def hk_yahoo_symbol(symbol: str) -> str:
    """Convert HK symbol to Yahoo Finance format (e.g. 00700 -> 0700.HK)."""
    code = normalize_hk_code(symbol)
    num = code.replace("HK", "")
    if num.isdigit():
        return str(int(num)).zfill(4) + ".HK"
    return f"{num}.HK" if num else ""


def fetch_yahoo_chart_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Spot quote via Yahoo chart API — lighter than yfinance batch calls."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"interval": "1d", "range": "5d"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; QuantDinger/1.0)"},
            timeout=10,
        )
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = safe_float(meta.get("regularMarketPrice") or meta.get("previousClose"))
        prev = safe_float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
        if price <= 0:
            return None
        change_pct = ((price - prev) / prev * 100.0) if prev > 0 else 0.0
        return {
            "last": price,
            "change": round(price - prev, 4) if prev else 0.0,
            "changePercent": round(change_pct, 2),
            "previousClose": prev,
        }
    except Exception as e:
        logger.debug("Yahoo chart quote failed for %s: %s", sym, e)
        return None
