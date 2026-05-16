"""
Coinbase (Advanced Trade + CDP API keys).

Uses REST `api.coinbase.com/api/v3/brokerage/...` with Bearer JWT (ES256),
not the legacy Coinbase Exchange HMAC (api.exchange.coinbase.com).

Stored credentials (same DB fields as other exchanges):
- api_key: CDP API key *name* / id (shown in Developer Platform)
- secret_key: EC private key (PEM or one-line base64 PKCS#8)
- passphrase: unused (optional empty)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

import requests

from app.services.live_trading import base as live_base
from app.services.live_trading.base import BaseRestClient, LiveOrderResult, LiveTradingError
from app.services.live_trading.coinbase_cdp_auth import (
    API_PREFIX,
    CB_REST_HOST,
    build_rest_jwt,
    format_jwt_uri,
    normalize_cdp_private_key,
)
from app.services.live_trading.symbols import to_coinbase_product_id

logger = logging.getLogger(__name__)


def _short(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


def _coinbase_response_summary(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"type": type(raw).__name__}
    sr = raw.get("success_response") or raw.get("successResponse") or {}
    er = raw.get("error_response") or raw.get("errorResponse") or {}
    return {
        "success": raw.get("success"),
        "order_id": _extract_order_id(raw),
        "failure_reason": raw.get("failure_reason") or raw.get("failureReason"),
        "error": raw.get("error") or (er.get("error") if isinstance(er, dict) else None),
        "message": raw.get("message") or (er.get("message") if isinstance(er, dict) else None),
        "success_keys": sorted(sr.keys()) if isinstance(sr, dict) else [],
        "top_keys": sorted(raw.keys()),
    }


def _extract_order_id(raw: Dict[str, Any]) -> str:
    if not isinstance(raw, dict):
        return ""
    sr = raw.get("success_response") or raw.get("successResponse")
    if isinstance(sr, dict):
        inner = sr.get("order") if isinstance(sr.get("order"), dict) else sr
        if isinstance(inner, dict):
            oid = inner.get("order_id") or inner.get("orderId")
            if oid:
                return str(oid)
    return str(raw.get("order_id") or raw.get("orderId") or "")


def _normalize_order_for_wait(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map Advanced Trade order fields to keys used by pending_order_worker.wait loops."""
    if not isinstance(raw, dict):
        return {}
    out = dict(raw)
    # Filled base size
    fs = raw.get("filled_size") or raw.get("filled_quantity")
    if fs is None and isinstance(raw.get("filled_value"), dict):
        fs = raw.get("filled_size")
    out.setdefault("filled_size", fs)
    # Executed notional (for avg price)
    ev = raw.get("total_value_after_fees") or raw.get("filled_value") or raw.get("average_filled_price")
    if isinstance(ev, dict):
        ev = ev.get("value")
    if ev is not None:
        out.setdefault("executed_value", ev)
    else:
        try:
            avg = float(raw.get("average_filled_price") or 0)
            fs2 = float(out.get("filled_size") or 0)
            if avg > 0 and fs2 > 0:
                out.setdefault("executed_value", avg * fs2)
        except Exception:
            pass
    fee = raw.get("total_fees") or raw.get("fee")
    if isinstance(fee, dict):
        fee = fee.get("value")
    if fee is not None:
        out.setdefault("fill_fees", fee)
    return out


class CoinbaseExchangeClient(BaseRestClient):
    """
    Spot trading via Coinbase Advanced Trade API (retail/brokerage CDP keys).
    """

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        passphrase: str = "",
        base_url: str = "",
        timeout_sec: float = 15.0,
    ):
        # Legacy arg `base_url` (exchange.coinbase.com) is ignored — Advanced Trade is fixed host.
        super().__init__(base_url=f"https://{CB_REST_HOST}", timeout_sec=timeout_sec)
        self.api_key = (api_key or "").strip()
        self._secret_pem = ""
        if not self.api_key:
            raise LiveTradingError("Missing Coinbase CDP API key id (api_key)")
        try:
            self._secret_pem = normalize_cdp_private_key(secret_key)
        except LiveTradingError:
            raise
        except Exception as e:
            raise LiveTradingError(f"Invalid Coinbase CDP private key: {e}") from e

    def _jwt_for(self, method: str, path: str) -> str:
        uri = format_jwt_uri(method, path)
        return build_rest_jwt(uri=uri, api_key=self.api_key, secret_pem=self._secret_pem)

    def _brokerage_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        p = path if path.startswith("/") else f"/{path}"
        token = self._jwt_for(method, p)
        url = f"https://{CB_REST_HOST}{p}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "QuantDinger/CoinbaseAdvancedTrade",
        }
        log_body = json_body if method.upper() != "GET" else None
        logger.info(
            "coinbase request: method=%s path=%s params=%s body=%s",
            str(method or "GET").upper(),
            p,
            params or {},
            _short(log_body),
        )
        try:
            resp = requests.request(
                str(method or "GET").upper(),
                url,
                params=params or None,
                json=json_body if json_body is not None else None,
                headers=headers,
                timeout=self.timeout_sec,
                verify=live_base._get_requests_verify(),
            )
        except UnicodeEncodeError as e:
            raise LiveTradingError(
                "Auth failed: non-ASCII characters in Coinbase credentials or headers cannot be encoded. "
                f"{e}"
            ) from e
        text = resp.text or ""
        parsed: Dict[str, Any] = {}
        try:
            parsed = resp.json() if text else {}
        except Exception:
            parsed = {"raw_text": text[:2000]}
        logger.info(
            "coinbase response: method=%s path=%s status=%s summary=%s",
            str(method or "GET").upper(),
            p,
            resp.status_code,
            _coinbase_response_summary(parsed),
        )
        if resp.status_code >= 400:
            err = parsed.get("message") or parsed.get("error") or text[:500]
            raise LiveTradingError(f"Coinbase Advanced Trade HTTP {resp.status_code}: {err}")
        if isinstance(parsed, dict) and parsed.get("error"):
            raise LiveTradingError(f"Coinbase Advanced Trade error: {parsed.get('error')}")
        if (
            str(method or "").upper() == "POST"
            and p.endswith("/orders")
            and isinstance(parsed, dict)
            and parsed.get("success") is False
        ):
            er = parsed.get("error_response") or parsed.get("errorResponse") or {}
            msg = (
                parsed.get("failure_reason")
                or parsed.get("failureReason")
                or (er.get("message") if isinstance(er, dict) else None)
                or (er.get("error") if isinstance(er, dict) else None)
                or "order rejected"
            )
            raise LiveTradingError(f"Coinbase Advanced Trade order rejected: {msg}")
        return parsed

    def ping(self) -> bool:
        try:
            r = requests.get(
                f"https://{CB_REST_HOST}{API_PREFIX}/time",
                timeout=min(10.0, self.timeout_sec),
                verify=live_base._get_requests_verify(),
            )
            return r.status_code == 200
        except Exception:
            return False

    def get_accounts(self) -> Any:
        return self._brokerage_request("GET", f"{API_PREFIX}/accounts", params={"limit": 250})

    def _best_ask_mid(self, product_id: str) -> float:
        raw = self._brokerage_request(
            "GET",
            f"{API_PREFIX}/best_bid_ask",
            params={"product_ids": product_id},
        )
        pricebooks = raw.get("pricebooks") if isinstance(raw, dict) else None
        if not isinstance(pricebooks, list) or not pricebooks:
            raise LiveTradingError(f"No best_bid_ask for {product_id}")
        book = pricebooks[0] if isinstance(pricebooks[0], dict) else {}
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        try:
            bid = float(bids[0].get("price") if bids and isinstance(bids[0], dict) else 0)
            ask = float(asks[0].get("price") if asks and isinstance(asks[0], dict) else 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2.0
            return ask or bid
        except Exception as e:
            raise LiveTradingError(f"best_bid_ask parse failed for {product_id}: {e}") from e

    def place_market_order(
        self, *, symbol: str, side: str, size: float, client_order_id: Optional[str] = None
    ) -> LiveOrderResult:
        sd = (side or "").strip().lower()
        if sd not in ("buy", "sell"):
            raise LiveTradingError(f"Invalid side: {side}")
        qty = float(size or 0.0)
        if qty <= 0:
            raise LiveTradingError("Invalid size")
        product_id = to_coinbase_product_id(symbol)
        coi = (client_order_id or "").strip() or uuid.uuid4().hex
        side_key = "BUY" if sd == "buy" else "SELL"
        ioc: Dict[str, str] = {}
        if sd == "buy":
            mid = self._best_ask_mid(product_id)
            quote = mid * qty
            if quote <= 0:
                raise LiveTradingError("Could not compute quote_size for market buy")
            ioc["quote_size"] = f"{quote:.8f}".rstrip("0").rstrip(".")
        else:
            ioc["base_size"] = f"{qty:.8f}".rstrip("0").rstrip(".")

        body = {
            "client_order_id": coi,
            "product_id": product_id,
            "side": side_key,
            "order_configuration": {"market_market_ioc": ioc},
        }
        raw = self._brokerage_request("POST", f"{API_PREFIX}/orders", json_body=body)
        oid = _extract_order_id(raw if isinstance(raw, dict) else {})
        if not oid:
            raise LiveTradingError(f"Coinbase Advanced Trade did not return order_id: {_coinbase_response_summary(raw)}")
        return LiveOrderResult(
            exchange_id="coinbaseexchange",
            exchange_order_id=oid,
            filled=0.0,
            avg_price=0.0,
            raw=raw if isinstance(raw, dict) else {"raw": raw},
        )

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        size: float,
        price: float,
        client_order_id: Optional[str] = None,
    ) -> LiveOrderResult:
        sd = (side or "").strip().lower()
        if sd not in ("buy", "sell"):
            raise LiveTradingError(f"Invalid side: {side}")
        qty = float(size or 0.0)
        px = float(price or 0.0)
        if qty <= 0 or px <= 0:
            raise LiveTradingError("Invalid size/price")
        product_id = to_coinbase_product_id(symbol)
        coi = (client_order_id or "").strip() or uuid.uuid4().hex
        side_key = "BUY" if sd == "buy" else "SELL"
        body = {
            "client_order_id": coi,
            "product_id": product_id,
            "side": side_key,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": f"{qty:.8f}".rstrip("0").rstrip("."),
                    "limit_price": f"{px:.8f}".rstrip("0").rstrip("."),
                    "post_only": False,
                }
            },
        }
        raw = self._brokerage_request("POST", f"{API_PREFIX}/orders", json_body=body)
        oid = _extract_order_id(raw if isinstance(raw, dict) else {})
        if not oid:
            raise LiveTradingError(f"Coinbase Advanced Trade did not return order_id: {_coinbase_response_summary(raw)}")
        return LiveOrderResult(
            exchange_id="coinbaseexchange",
            exchange_order_id=oid,
            filled=0.0,
            avg_price=0.0,
            raw=raw if isinstance(raw, dict) else {"raw": raw},
        )

    def cancel_order(self, *, order_id: str = "", client_order_id: str = "") -> Any:
        if order_id:
            return self._brokerage_request(
                "POST",
                f"{API_PREFIX}/orders/batch_cancel",
                json_body={"order_ids": [str(order_id)]},
            )
        if client_order_id:
            # Resolve client id -> exchange order id (best effort).
            o = self.get_order(order_id="", client_order_id=str(client_order_id))
            oid = ""
            if isinstance(o, dict):
                oid = str(o.get("order_id") or o.get("orderId") or "")
            if oid:
                return self.cancel_order(order_id=oid)
            raise LiveTradingError("Could not resolve client_order_id to cancel on Coinbase Advanced Trade")
        raise LiveTradingError("Coinbase cancel_order requires order_id or client_order_id")

    def get_order(self, *, order_id: str = "", client_order_id: str = "") -> Any:
        if order_id:
            raw = self._brokerage_request("GET", f"{API_PREFIX}/orders/historical/{order_id}")
            if isinstance(raw, dict) and isinstance(raw.get("order"), dict):
                raw = raw["order"]
            return _normalize_order_for_wait(raw) if isinstance(raw, dict) else raw
        if client_order_id:
            # Historical batch returns recent orders; scan for matching client_order_id.
            raw = self._brokerage_request(
                "GET",
                f"{API_PREFIX}/orders/historical/batch",
                params={"limit": 100},
            )
            orders = raw.get("orders") if isinstance(raw, dict) else None
            if isinstance(orders, list):
                for item in orders:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("client_order_id") or "") == str(client_order_id):
                        return _normalize_order_for_wait(item)
            raise LiveTradingError("Coinbase Advanced Trade: client_order_id not found in recent orders")
        raise LiveTradingError("Coinbase get_order requires order_id or client_order_id")

    def wait_for_fill(
        self,
        *,
        order_id: str = "",
        client_order_id: str = "",
        max_wait_sec: float = 10.0,
        poll_interval_sec: float = 0.5,
    ) -> Dict[str, Any]:
        import time as _t

        end_ts = _t.time() + float(max_wait_sec or 0.0)
        last: Dict[str, Any] = {}
        while True:
            timed_out = _t.time() >= end_ts
            try:
                resp = self.get_order(order_id=str(order_id or ""), client_order_id=str(client_order_id or ""))
                last = _normalize_order_for_wait(resp) if isinstance(resp, dict) else {"raw": resp}
            except Exception:
                last = last or {}
            status = str(last.get("status") or "")
            filled = 0.0
            avg_price = 0.0
            fee = 0.0
            fee_ccy = ""
            try:
                filled = float(last.get("filled_size") or 0.0)
            except Exception:
                filled = 0.0
            try:
                executed_value = float(last.get("executed_value") or 0.0)
                if filled > 0 and executed_value > 0:
                    avg_price = executed_value / filled
            except Exception:
                avg_price = 0.0
            try:
                fee = abs(float(last.get("fill_fees") or last.get("total_fees") or 0.0))
            except Exception:
                fee = 0.0
            if fee > 0:
                fee_ccy = "USD"

            st = status.lower()
            terminal = st in ("filled", "done", "cancelled", "canceled", "rejected", "expired", "failed")

            if filled > 0 and avg_price > 0:
                if fee <= 0 and not timed_out:
                    _t.sleep(float(poll_interval_sec or 0.5))
                    continue
                return {"filled": filled, "avg_price": avg_price, "fee": fee, "fee_ccy": fee_ccy, "status": status, "order": last}
            if terminal:
                return {"filled": filled, "avg_price": avg_price, "fee": fee, "fee_ccy": fee_ccy, "status": status, "order": last}
            if timed_out:
                return {"filled": filled, "avg_price": avg_price, "fee": fee, "fee_ccy": fee_ccy, "status": status, "order": last}
            _t.sleep(float(poll_interval_sec or 0.5))
