"""
Exchange execution helpers (local deployment).

This module provides helpers for resolving exchange configs and safe logging.

Notes:
- In paper mode, the system only enqueues signals into `pending_orders`.
- Real trading execution is intentionally not implemented here.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.utils.credential_crypto import decrypt_credential_blob

logger = get_logger(__name__)


def _safe_json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    s = value.strip()
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


# Map exchange_id -> implied market_category, used as a safety net so we never
# silently route stock/forex strategies through the crypto data source just
# because `market_category` was missing from the row.
#
# Keep this list in sync with:
#   - app/services/live_trading/factory.py::create_client
#   - app/services/pending_order_worker.py::_execute_live_order validation
#   - app/services/strategy.py validators (create / update / batch_create)
_EXCHANGE_TO_MARKET: Dict[str, str] = {
    "ibkr": "USStock",
    "alpaca": "USStock",  # Alpaca primarily for US stocks; crypto is opt-in via market_category override
    "mt5": "Forex",
}
_CRYPTO_EXCHANGES = {
    "binance", "okx", "bitget", "bybit", "coinbaseexchange",
    "coinbase_exchange", "coinbase",
    "kraken", "kucoin", "gate", "deepcoin", "htx",
}

_EXCHANGE_ID_ALIASES = {
    "coinbase_exchange": "coinbaseexchange",
    "coinbase": "coinbaseexchange",
}

_CREDENTIAL_ID_KEYS = ("credential_id", "credentialId", "credentials_id", "credentialsId")


def normalize_exchange_id(exchange_id: Any) -> str:
    """Canonical broker id for policy checks and client factory routing."""
    key = str(exchange_id or "").strip().lower()
    return _EXCHANGE_ID_ALIASES.get(key, key)


def get_credential_id(exchange_config: Dict[str, Any]) -> Any:
    """Return a credential id from snake_case or camelCase config keys."""
    if not isinstance(exchange_config, dict):
        return None
    for key in _CREDENTIAL_ID_KEYS:
        value = exchange_config.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _infer_market_category_from_exchange(exchange_id: str) -> str:
    """
    Best-effort inference when market_category is missing on a strategy row.

    Returns 'Crypto' as the legacy default only if exchange_id is empty or unknown.
    """
    eid = (exchange_id or "").strip().lower()
    if not eid:
        return "Crypto"
    if eid in _EXCHANGE_TO_MARKET:
        return _EXCHANGE_TO_MARKET[eid]
    if eid in _CRYPTO_EXCHANGES:
        return "Crypto"
    return "Crypto"


def mask_secret(s: str, keep: int = 4) -> str:
    """Return a masked representation of a secret for safe logs."""
    if not s:
        return ""
    s = str(s)
    if len(s) <= keep * 2:
        return s[: max(1, keep)] + "***"
    return f"{s[:keep]}...{s[-keep:]}"


def safe_exchange_config_for_log(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    out = dict(cfg)
    for k in ["api_key", "secret_key", "passphrase", "apiKey", "secret", "password"]:
        if k in out and out.get(k):
            out[k] = mask_secret(str(out.get(k)))
    return out


def load_strategy_configs(strategy_id: int) -> Dict[str, Any]:
    """Load strategy config fields needed for live execution."""
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT id, user_id, exchange_config, trading_config, market_type, leverage, execution_mode, market_category
            FROM qd_strategies_trading
            WHERE id = %s
            """,
            (int(strategy_id),),
        )
        row = cur.fetchone() or {}
        cur.close()

    exchange_config = _safe_json_loads(row.get("exchange_config"), {})
    trading_config = _safe_json_loads(row.get("trading_config"), {})

    market_type = (row.get("market_type") or exchange_config.get("market_type") or "swap").strip()
    leverage = float(row.get("leverage") or trading_config.get("leverage") or exchange_config.get("leverage") or 1.0)
    execution_mode = (row.get("execution_mode") or "signal").strip().lower()

    # market_category MUST come from the strategy row; if it's empty (legacy or
    # corrupt rows), infer from exchange_id rather than silently defaulting to
    # Crypto — that is what historically caused TSLA to be queried via CCXT.
    raw_mc = (row.get("market_category") or "").strip()
    if raw_mc:
        market_category = raw_mc
    else:
        ex_id = ""
        if isinstance(exchange_config, dict):
            ex_id = str(exchange_config.get("exchange_id") or exchange_config.get("exchangeId") or "").strip().lower()
        market_category = _infer_market_category_from_exchange(ex_id)
        logger.warning(
            "Strategy %s has empty market_category — inferred '%s' from exchange_id=%r. "
            "Please re-save the strategy with an explicit market_category to silence this warning.",
            strategy_id, market_category, ex_id,
        )

    user_id = int(row.get("user_id") or 1)

    return {
        "strategy_id": int(strategy_id),
        "user_id": user_id,
        "exchange_config": exchange_config if isinstance(exchange_config, dict) else {},
        "trading_config": trading_config if isinstance(trading_config, dict) else {},
        "market_type": market_type,
        "leverage": leverage,
        "execution_mode": execution_mode,
        "market_category": market_category,
    }


def _load_credential_config(credential_id: int, user_id: int = 1) -> Dict[str, Any]:
    """Load credential JSON from qd_exchange_credentials (Fernet via SECRET_KEY)."""
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT exchange_id AS row_exchange_id, encrypted_config
            FROM qd_exchange_credentials
            WHERE id = %s AND user_id = %s
            """,
            (int(credential_id), int(user_id)),
        )
        row = cur.fetchone() or {}
        cur.close()
    if not row:
        return {
            "_credential_error": f"credential_id {int(credential_id)} not found for user {int(user_id)}"
        }
    row_exchange_id = normalize_exchange_id(
        row.get("row_exchange_id") if isinstance(row, dict) else ""
    )
    raw = row.get("encrypted_config") if isinstance(row, dict) else None
    try:
        plain = decrypt_credential_blob(raw)
    except ValueError as e:
        logger.warning(f"decrypt credential_id={credential_id}: {e}")
        cfg = {"_credential_error": f"credential_id {int(credential_id)} cannot be decrypted"}
        if row_exchange_id:
            cfg["exchange_id"] = row_exchange_id
        return cfg
    cfg = _safe_json_loads(plain, {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    blob_ex = normalize_exchange_id(cfg.get("exchange_id") or cfg.get("exchangeId"))
    if row_exchange_id:
        if blob_ex and blob_ex != row_exchange_id:
            logger.info(
                "credential id=%s: normalizing exchange_id %r -> %r (DB column wins)",
                credential_id,
                blob_ex,
                row_exchange_id,
            )
        cfg["exchange_id"] = row_exchange_id
    elif blob_ex:
        cfg["exchange_id"] = blob_ex
    return cfg


def resolve_exchange_config(exchange_config: Dict[str, Any], user_id: int = 1) -> Dict[str, Any]:
    """
    Resolve exchange config.

    Supports:
    - direct inline config: {exchange_id, api_key, secret_key, passphrase?}
    - credential reference: {credential_id: 123, ...overrides}
    """
    if not isinstance(exchange_config, dict):
        return {}

    merged: Dict[str, Any] = {}
    credential_id = get_credential_id(exchange_config)
    try:
        if credential_id:
            base = _load_credential_config(int(credential_id), user_id=user_id)
            if isinstance(base, dict):
                merged.update(base)
    except Exception as e:
        logger.warning(f"Failed to load credential_id={credential_id}: {e}")
        merged["_credential_error"] = f"credential_id {credential_id} is invalid for user {int(user_id)}"

    # Overlay strategy-level settings (non-empty wins)
    for k, v in exchange_config.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        merged[k] = v

    ex = normalize_exchange_id(merged.get("exchange_id") or merged.get("exchangeId"))
    if ex:
        merged["exchange_id"] = ex
    if credential_id:
        merged["credential_id"] = credential_id

    return merged


def credential_error(resolved_config: Dict[str, Any]) -> str:
    """Return a human-readable saved-credential error, if any."""
    if not isinstance(resolved_config, dict):
        return ""
    return str(resolved_config.get("_credential_error") or "").strip()


