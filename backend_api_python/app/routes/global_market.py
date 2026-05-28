"""
Global Market Dashboard APIs.

Provides aggregated global market data including:
- Major indices (US, Europe, Japan, Korea, Australia, India)
- Forex pairs
- Crypto prices
- Market heatmap data (crypto, stocks, forex)
- Economic calendar with impact indicators
- Fear & Greed Index / VIX
- Financial news (Chinese & English)

Endpoints:
- GET /api/global-market/overview       - Global market overview
- GET /api/global-market/heatmap        - Market heatmap data
- GET /api/global-market/news           - Financial news (with lang param)
- GET /api/global-market/calendar       - Economic calendar
- GET /api/global-market/sentiment      - Fear & Greed / VIX
- GET /api/global-market/adanos-sentiment - Optional Adanos stock sentiment
- GET /api/global-market/opportunities  - Trading opportunities scanner
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, jsonify, request, g

from app.utils.logger import get_logger
from app.utils.auth import login_required

# Unified data-provider layer.
#
# Every endpoint below wraps its expensive compute in `cached_or_compute`,
# which gives us three properties for free:
#   1. Cache hit -> 0 upstream calls.
#   2. Cache miss with concurrent callers -> single upstream call (the
#      others block on the per-key lock and then read the populated cache).
#   3. Soft-expired cache -> the previous value is returned IMMEDIATELY
#      and the refresh runs in the background. Users never wait for stale
#      data to become fresh; the next user gets the new value.
#
# These three together are what stops the "open AI asset analysis page,
# wait 2s on yfinance" experience.
from app.data_providers import (
    cached_or_compute, set_cached, clear_cache, invalidate,
)
from app.data_providers.crypto import fetch_crypto_prices
from app.data_providers.forex import fetch_forex_pairs
from app.data_providers.commodities import fetch_commodities
from app.data_providers.indices import fetch_stock_indices
from app.data_providers.sentiment import (
    fetch_fear_greed_index, fetch_vix, fetch_dollar_index,
    fetch_yield_curve, fetch_vxn, fetch_gvz, fetch_put_call_ratio,
)
from app.data_providers.adanos_sentiment import fetch_adanos_market_sentiment
from app.data_providers.news import fetch_financial_news, get_economic_calendar
from app.data_providers.heatmap import generate_heatmap_data
from app.data_providers.opportunities import (
    analyze_opportunities_crypto, analyze_opportunities_stocks,
    analyze_opportunities_local_stocks, analyze_opportunities_forex,
)
from app.config.api_keys import APIKeys
from app.utils.config_loader import load_addon_config
from app.utils.market_visibility import filter_market_items
from app.data.market_symbols_seed import get_hot_symbols as seed_get_hot_symbols

logger = get_logger(__name__)

global_market_bp = Blueprint("global_market", __name__)


# ============ API Endpoints ============

def _compute_market_overview():
    """Fan-out four upstream pulls in parallel; never raise — return empty
    lists on failure so the route always returns 200."""
    result = {
        "indices": [], "forex": [], "crypto": [], "commodities": [],
        "timestamp": int(time.time()),
    }
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_stock_indices): "indices",
            executor.submit(fetch_forex_pairs): "forex",
            executor.submit(fetch_crypto_prices): "crypto",
            executor.submit(fetch_commodities): "commodities",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                data = future.result()
                result[key] = data if data else []
            except Exception as e:
                logger.error("Failed to fetch %s: %s", key, e, exc_info=True)
                result[key] = []

    logger.info(
        "Market overview compute: indices=%d, forex=%d, crypto=%d, commodities=%d",
        len(result["indices"]), len(result["forex"]),
        len(result["crypto"]), len(result["commodities"]),
    )

    # Also seed the per-section caches so any standalone endpoint that
    # reads them (e.g. a future /api/global-market/indices) benefits from
    # the same fetch.
    set_cached("stock_indices", result["indices"])
    set_cached("forex_pairs", result["forex"])
    set_cached("crypto_prices", result["crypto"])
    return result


@global_market_bp.route("/overview", methods=["GET"])
@login_required
def market_overview():
    """Get global market overview including indices, forex, crypto, and commodities."""
    try:
        force = request.args.get("force", "").lower() in ("true", "1")
        data = cached_or_compute(
            "market_overview", _compute_market_overview, force=force
        )
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("market_overview failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@global_market_bp.route("/heatmap", methods=["GET"])
@login_required
def market_heatmap():
    """Get market heatmap data for crypto, stock sectors, forex, and indices."""
    try:
        force = request.args.get("force", "").lower() in ("true", "1")
        data = cached_or_compute(
            "market_heatmap", generate_heatmap_data, force=force
        )
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("market_heatmap failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@global_market_bp.route("/news", methods=["GET"])
@login_required
def market_news():
    """Get financial news from various sources.  Query params: lang ('cn'|'en'|'all')."""
    try:
        lang = request.args.get("lang", "all")
        force = request.args.get("force", "").lower() in ("true", "1")
        cache_key = f"market_news_{lang}"
        data = cached_or_compute(
            cache_key,
            lambda: fetch_financial_news(lang),
            ttl=180,
            force=force,
        )
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("market_news failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@global_market_bp.route("/calendar", methods=["GET"])
@login_required
def economic_calendar():
    """Get economic calendar events with impact indicators."""
    try:
        force = request.args.get("force", "").lower() in ("true", "1")
        data = cached_or_compute(
            "economic_calendar", get_economic_calendar, force=force
        )
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("economic_calendar failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


def _compute_market_sentiment():
    """Fan-out 7 macro sentiment indicators in parallel.

    None-safe: any sub-fetcher that fails contributes a None which we
    backfill with neutral defaults so the UI never sees missing fields.
    """
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(fetch_fear_greed_index): "fear_greed",
            executor.submit(fetch_vix): "vix",
            executor.submit(fetch_dollar_index): "dxy",
            executor.submit(fetch_yield_curve): "yield_curve",
            executor.submit(fetch_vxn): "vxn",
            executor.submit(fetch_gvz): "gvz",
            executor.submit(fetch_put_call_ratio): "vix_term",
        }
        results = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.error("Failed to fetch %s: %s", key, e)
                results[key] = None

    logger.info(
        "Sentiment compute: Fear&Greed=%s, VIX=%s, DXY=%s",
        (results.get("fear_greed") or {}).get("value"),
        (results.get("vix") or {}).get("value"),
        (results.get("dxy") or {}).get("value"),
    )

    return {
        "fear_greed": results.get("fear_greed") or {"value": 50, "classification": "Neutral"},
        "vix":         results.get("vix")         or {"value": 0,   "level": "unknown"},
        "dxy":         results.get("dxy")         or {"value": 0,   "level": "unknown"},
        "yield_curve": results.get("yield_curve") or {"spread": 0,  "level": "unknown"},
        "vxn":         results.get("vxn")         or {"value": 0,   "level": "unknown"},
        "gvz":         results.get("gvz")         or {"value": 0,   "level": "unknown"},
        "vix_term":    results.get("vix_term")    or {"value": 1.0, "level": "unknown"},
        "timestamp": int(time.time()),
    }


@global_market_bp.route("/sentiment", methods=["GET"])
@login_required
def market_sentiment():
    """Get comprehensive market sentiment indicators."""
    try:
        force = request.args.get("force", "").lower() in ("true", "1")
        data = cached_or_compute(
            "market_sentiment", _compute_market_sentiment, force=force
        )
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("market_sentiment failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@global_market_bp.route("/adanos-sentiment", methods=["GET"])
@login_required
def adanos_market_sentiment():
    """Get optional Adanos Market Sentiment for selected US stock tickers."""
    try:
        tickers = request.args.get("tickers", "")
        source = request.args.get("source")
        days = int(request.args.get("days") or 7)
        force = request.args.get("force", "").lower() in ("true", "1")
        cache_key = f"adanos_sentiment:{source or 'default'}:{days}:{tickers.upper()}"

        def _compute():
            # Only the *successful* path gets cached. If the upstream is
            # disabled or errored we still surface the response but skip
            # caching by clearing the entry post-hoc.
            data = fetch_adanos_market_sentiment(tickers, source=source, days=days)
            return data

        data = cached_or_compute(cache_key, _compute, ttl=300, force=force)
        # If the freshly-computed result is an "unhealthy" payload, evict
        # the cache so we don't keep returning it for 5 minutes.
        if isinstance(data, dict) and (not data.get("enabled") or data.get("error")):
            invalidate(cache_key)
        return jsonify({"code": 1, "msg": "success", "data": data})

    except ValueError as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error("adanos_market_sentiment failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


def _compute_trading_opportunities():
    """Run all market scanners sequentially. Each scanner is resilient and
    only contributes to the accumulator on success.

    Per-market visibility comes from :func:`app.utils.market_visibility.is_market_visible`
    so the radar never surfaces a market that the watchlist picker has hidden.
    Skipping a disabled market also avoids the (slow) upstream price /
    fundamentals fetches for it, so the cache miss latency drops too.
    """
    from app.utils.market_visibility import is_market_visible as _vis

    opportunities: list = []
    candidate_scanners = [
        ("Crypto",  lambda: analyze_opportunities_crypto(opportunities)),
        ("USStock", lambda: analyze_opportunities_stocks(opportunities)),
        ("Forex",   lambda: analyze_opportunities_forex(opportunities)),
        ("CNStock", lambda: analyze_opportunities_local_stocks(opportunities, "CNStock")),
        ("HKStock", lambda: analyze_opportunities_local_stocks(opportunities, "HKStock")),
    ]
    scanners = [(label, fn) for label, fn in candidate_scanners if _vis(label)]

    for label, scanner in scanners:
        try:
            scanner()
            count = len([o for o in opportunities if o.get("market") == label])
            logger.info("Trading opportunities: found %d %s opportunities", count, label)
        except Exception as e:
            logger.error("Failed to analyze %s opportunities: %s", label, e, exc_info=True)

    opportunities.sort(key=lambda x: abs(x.get("change_24h", 0)), reverse=True)

    by_market = {}
    for o in opportunities:
        by_market[o.get("market", "?")] = by_market.get(o.get("market", "?"), 0) + 1
    logger.info("Trading opportunities: total %d (%s)", len(opportunities), by_market)
    return opportunities


@global_market_bp.route("/opportunities", methods=["GET"])
@login_required
def trading_opportunities():
    """Scan for trading opportunities across Crypto, US/CN/HK Stocks, and Forex."""
    try:
        force = request.args.get("force", "").lower() in ("true", "1")
        data = cached_or_compute(
            "trading_opportunities",
            _compute_trading_opportunities,
            force=force,
        )

        # Post-filter against current env flags. Even if a stale cache still
        # holds (or a future scanner accidentally includes) data for a market
        # the operator has disabled in env, the response is guaranteed to be
        # consistent with `/api/market/types`.
        from app.utils.market_visibility import hidden_markets as _hidden
        hidden = _hidden()
        if hidden and isinstance(data, list):
            data = [o for o in data if (o.get("market") if isinstance(o, dict) else None) not in hidden]

        return jsonify({"code": 1, "msg": "success", "data": data or []})
    except Exception as e:
        logger.error("trading_opportunities failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


def _has_configured_market_credentials() -> bool:
    """Require at least one backend-configured provider credential.

    The snapshot endpoint is intended for authenticated server-side use and
    should not become an anonymous "free market data relay". We therefore
    require operators to configure at least one upstream credential in
    addon config or env before serving this payload.
    """
    configured_keys = (
        "FINNHUB_API_KEY",
        "TWELVE_DATA_API_KEY",
        "TIINGO_API_KEY",
        "COINGLASS_API_KEY",
        "CRYPTOQUANT_API_KEY",
        "ADANOS_API_KEY",
    )
    if any(APIKeys.is_configured(k) for k in configured_keys):
        return True

    try:
        cfg = load_addon_config()
    except Exception:
        cfg = {}
    sections = ("finnhub", "twelve_data", "tiingo", "coinglass", "cryptoquant", "adanos")
    for section in sections:
        api_key = ((cfg.get(section) or {}).get("api_key") or "").strip()
        if api_key:
            return True
    return False


def _compute_market_types():
    desired_order = ["USStock", "CNStock", "HKStock", "Crypto", "Forex", "Futures", "MOEX"]
    order_rank = {v: i for i, v in enumerate(desired_order)}
    data = filter_market_items(
        [{"value": v, "i18nKey": f"dashboard.analysis.market.{v}"} for v in desired_order],
        key="value",
    )
    data.sort(key=lambda it: order_rank.get((it or {}).get("value"), 10000))
    return data


def _compute_hot_symbols_by_market():
    out = {}
    for item in _compute_market_types():
        market = (item or {}).get("value")
        if not market:
            continue
        try:
            out[market] = seed_get_hot_symbols(market=market, limit=10)
        except Exception as e:
            logger.warning("hot symbols fetch failed for %s: %s", market, e)
            out[market] = []
    return out


def _compute_current_user_profile():
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return None
    profile = None
    try:
        from app.services.user_service import get_user_service
        profile = get_user_service().get_user_by_id(user_id)
    except Exception as e:
        logger.debug("user profile fallback for %s: %s", user_id, e)
    if isinstance(profile, dict):
        return {
            "id": profile.get("id"),
            "username": profile.get("username"),
            "nickname": profile.get("nickname", "User"),
            "email": profile.get("email"),
            "avatar": profile.get("avatar", "/avatar2.jpg"),
            "timezone": str(profile.get("timezone") or "").strip(),
            "role": profile.get("role", "user"),
        }
    return {
        "id": user_id,
        "username": getattr(g, "user", None),
        "nickname": "User",
        "email": None,
        "avatar": "/avatar2.jpg",
        "timezone": "",
        "role": getattr(g, "user_role", "user"),
    }


@global_market_bp.route("/ai-asset-analysis/snapshot", methods=["GET"])
@login_required
def ai_asset_analysis_snapshot():
    """Return homepage snapshot data for /#/ai-asset-analysis.

    Excludes personal watchlist rows by design. Every block is served through
    cache wrappers to avoid direct/stampeding upstream pulls.
    """
    try:
        if not _has_configured_market_credentials():
            return jsonify({
                "code": 0,
                "msg": "No backend market-data credential configured. Configure at least one provider API key first.",
                "data": None,
            }), 503

        force = request.args.get("force", "").lower() in ("true", "1")
        user_id = getattr(g, "user_id", 0)
        payload = {
            "user_info": cached_or_compute(
                f"ai_asset_snapshot_user:{user_id}",
                _compute_current_user_profile,
                ttl=60,
                force=force,
            ),
            "market_types": cached_or_compute(
                "ai_asset_snapshot_market_types",
                _compute_market_types,
                ttl=600,
                force=force,
            ) or [],
            "hot_symbols": cached_or_compute(
                "ai_asset_snapshot_hot_symbols",
                _compute_hot_symbols_by_market,
                ttl=1800,
                force=force,
            ) or {},
            "opportunities": cached_or_compute(
                "trading_opportunities",
                _compute_trading_opportunities,
                force=force,
            ) or [],
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
            "timestamp": int(time.time()),
        }
        return jsonify({"code": 1, "msg": "success", "data": payload})
    except Exception as e:
        logger.error("ai_asset_analysis_snapshot failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@global_market_bp.route("/refresh", methods=["POST"])
@login_required
def refresh_data():
    """Force refresh all market data (clears cache)."""
    try:
        clear_cache()
        return jsonify({"code": 1, "msg": "Cache cleared successfully", "data": None})
    except Exception as e:
        logger.error("refresh_data failed: %s", e, exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
