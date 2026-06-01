"""Read-class market data endpoints."""
from __future__ import annotations

from app.data.market_symbols_seed import (
    get_hot_symbols as seed_get_hot_symbols,
    search_symbols as seed_search_symbols,
)
from app.data_providers import cached_or_compute
from app.data_providers.heatmap import generate_heatmap_data
from app.data_providers.cn_value_picks import get_cn_value_picks_for_snapshot
from app.data_providers.news import get_economic_calendar
from app.services.kline import KlineService
from app.routes.global_market import (
    _compute_market_overview,
    _compute_market_sentiment,
    _compute_market_types,
    _compute_hot_symbols_by_market,
    _compute_trading_opportunities,
    _has_configured_market_credentials,
)
from app.utils.agent_auth import (
    SCOPE_R, agent_required, instrument_allowed, market_allowed,
)
from app.utils.logger import get_logger
from app.utils.market_visibility import is_market_visible
from flask import request

from . import agent_v1_bp
from ._helpers import clip_int, envelope, error

logger = get_logger(__name__)
_kline_service = KlineService()


_MARKETS = [
    {"value": "USStock",  "label": "US Stocks"},
    {"value": "CNStock",  "label": "China A-shares"},
    {"value": "HKStock",  "label": "HK Stocks"},
    {"value": "Crypto",   "label": "Crypto"},
    {"value": "Forex",    "label": "Forex"},
    {"value": "Futures",  "label": "Futures"},
    {"value": "MOEX",     "label": "MOEX"},
]


@agent_v1_bp.route("/markets", methods=["GET"])
@agent_required(SCOPE_R)
def list_markets():
    """List markets the calling token is allowed to query.

    Filtering is the intersection of three rules:
      1. The token's ``markets`` allowlist (set per credential).
      2. Per-deployment visibility (``ENABLED_MARKETS`` / legacy ``SHOW_*``),
         resolved by :func:`app.utils.market_visibility.is_market_visible` so
         the Agent API stays in lock-step with the watchlist picker.
    """
    visible = [
        m for m in _MARKETS
        if market_allowed(m["value"]) and is_market_visible(m["value"])
    ]
    return envelope(visible)


@agent_v1_bp.route("/markets/<market>/symbols", methods=["GET"])
@agent_required(SCOPE_R)
def market_symbols(market: str):
    """Search symbols within a market.

    Query params:
        keyword: substring/code to match (case-insensitive)
        limit:   1..100 (default 20)
    """
    if not market_allowed(market):
        return error(403, f"Market not allowed for this token: {market}", http=403)

    keyword = (request.args.get("keyword") or "").strip().upper()
    limit = clip_int(request.args.get("limit"), default=20, lo=1, hi=100)

    if not keyword:
        out = seed_get_hot_symbols(market=market, limit=limit) or []
    else:
        out = seed_search_symbols(market=market, keyword=keyword, limit=limit) or []
    return envelope(out)


@agent_v1_bp.route("/klines", methods=["GET"])
@agent_required(SCOPE_R)
def klines():
    """OHLCV bars.

    Query params:
        market, symbol     (required)
        timeframe          (default 1D)
        limit              1..2000 (default 300)
        before_time        unix seconds (optional, for backwards pagination)
    """
    market = (request.args.get("market") or "").strip()
    symbol = (request.args.get("symbol") or "").strip()
    timeframe = (request.args.get("timeframe") or "1D").strip()
    limit = clip_int(request.args.get("limit"), default=300, lo=1, hi=2000)
    before_raw = request.args.get("before_time") or request.args.get("beforeTime")

    if not market or not symbol:
        return error(400, "market and symbol are required")
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    before_time = None
    if before_raw:
        try:
            before_time = int(before_raw)
        except Exception:
            return error(400, "before_time must be unix seconds")

    try:
        rows = _kline_service.get_kline(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            before_time=before_time,
        ) or []
    except Exception as exc:
        logger.error(f"agent_v1/klines failed: {exc}", exc_info=True)
        return error(500, "kline fetch failed", details=str(exc), retriable=True, http=502)

    return envelope({
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(rows),
        "klines": rows,
    })


@agent_v1_bp.route("/price", methods=["GET"])
@agent_required(SCOPE_R)
def price():
    """Latest price for a symbol."""
    market = (request.args.get("market") or "").strip()
    symbol = (request.args.get("symbol") or "").strip()
    if not market or not symbol:
        return error(400, "market and symbol are required")
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)
    try:
        rows = _kline_service.get_kline(market=market, symbol=symbol, timeframe="1m", limit=1) or []
        if not rows:
            return envelope({"market": market, "symbol": symbol, "price": None})
        last = rows[-1]
        # KlineService rows are typically dicts with 'close'/'c' keys.
        close = (
            last.get("close") if isinstance(last, dict) else None
        ) or (last.get("c") if isinstance(last, dict) else None)
        return envelope({
            "market": market,
            "symbol": symbol,
            "price": close,
            "raw": last,
        })
    except Exception as exc:
        logger.error(f"agent_v1/price failed: {exc}", exc_info=True)
        return error(500, "price fetch failed", details=str(exc), retriable=True, http=502)


@agent_v1_bp.route("/markets/ai-asset-snapshot", methods=["GET"])
@agent_required(SCOPE_R)
def ai_asset_snapshot():
    """Aggregate snapshot for AI asset analysis homepage via Agent Token.

    Response shape intentionally mirrors `/api/global-market/ai-asset-analysis/snapshot`
    but is agent-scoped and returned in Agent v1 envelope format.
    """
    if not _has_configured_market_credentials():
        return error(
            503,
            "No backend market-data credential configured. Configure at least one provider API key first.",
            http=503,
        )

    force = (request.args.get("force") or "").strip().lower() in ("1", "true")
    market_types = cached_or_compute(
        "ai_asset_snapshot_market_types",
        _compute_market_types,
        ttl=600,
        force=force,
    ) or []
    allowed_markets = {
        m.get("value")
        for m in market_types
        if isinstance(m, dict) and m.get("value") and market_allowed(m.get("value"))
    }
    filtered_market_types = [m for m in market_types if isinstance(m, dict) and m.get("value") in allowed_markets]

    hot_symbols_all = cached_or_compute(
        "ai_asset_snapshot_hot_symbols",
        _compute_hot_symbols_by_market,
        ttl=1800,
        force=force,
    ) or {}
    hot_symbols = {
        market: symbols
        for market, symbols in hot_symbols_all.items()
        if market in allowed_markets
    }

    opportunities = cached_or_compute(
        "trading_opportunities",
        _compute_trading_opportunities,
        force=force,
    ) or []
    if isinstance(opportunities, list):
        opportunities = [
            o for o in opportunities
            if isinstance(o, dict) and o.get("market") in allowed_markets
        ]

    payload = {
        "market_types": filtered_market_types,
        "hot_symbols": hot_symbols,
        "opportunities": opportunities,
        "market_sentiment": cached_or_compute(
            "market_sentiment",
            _compute_market_sentiment,
            force=force,
        ) or {},
        "market_overview": cached_or_compute(
            "market_overview",
            _compute_market_overview,
            force=force,
        ) or {},
        "market_heatmap": cached_or_compute(
            "market_heatmap",
            generate_heatmap_data,
            force=force,
        ) or {},
        "economic_calendar": cached_or_compute(
            "economic_calendar",
            get_economic_calendar,
            force=force,
        ) or [],
        "cn_value_picks": (
            get_cn_value_picks_for_snapshot(force=force)
            if "CNStock" in allowed_markets
            else []
        ),
    }
    return envelope(payload)
