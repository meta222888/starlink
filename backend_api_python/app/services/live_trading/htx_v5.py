"""
HTX USDT-M swap API V5 helpers.

Maps V5 responses to the legacy linear-swap shapes consumed by quick_trade / pending_order_worker.
Ref: https://www.htx.com/zh-cn/opend/newApiPages/?id=5521
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def v5_ok(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    if str(raw.get("status") or "").lower() == "ok":
        return True
    code = raw.get("code")
    if code is None:
        return False
    try:
        return int(code) == 200
    except (TypeError, ValueError):
        return False


def v5_data(raw: Dict[str, Any]) -> Any:
    return raw.get("data")


def v5_err_message(raw: Dict[str, Any]) -> str:
    return str(
        raw.get("err_msg")
        or raw.get("msg")
        or raw.get("message")
        or raw.get("err_code")
        or raw
    )


def is_single_asset_mode_unavailable(msg: str) -> bool:
    """HTX V5 may reject private calls while account is still on single-asset collateral."""
    text = str(msg or "").lower()
    return "single-asset" in text and ("unavailable" in text or "not available" in text or "暂停" in text)


def normalize_balance(raw: Dict[str, Any]) -> Dict[str, Any]:
    """V5 balance -> legacy swap_cross_account_info-like list in data."""
    data = v5_data(raw)
    if not isinstance(data, dict):
        return {"status": "ok", "data": []}
    details = data.get("details") or []
    rows: List[Dict[str, Any]] = []
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            ccy = str(item.get("currency") or "USDT").upper()
            avail = float(item.get("available") or item.get("withdraw_available") or 0)
            equity = float(item.get("equity") or item.get("margin_balance") or avail or 0)
            rows.append({
                "margin_asset": ccy,
                "margin_available": avail,
                "withdraw_available": float(item.get("withdraw_available") or avail),
                "margin_balance": equity,
                "margin_static": equity,
                "margin_mode": "cross",
            })
    if not rows:
        avail = float(data.get("available_margin") or data.get("equity") or 0)
        equity = float(data.get("equity") or avail)
        if equity > 0 or avail > 0:
            rows.append({
                "margin_asset": "USDT",
                "margin_available": avail,
                "withdraw_available": avail,
                "margin_balance": equity,
                "margin_static": equity,
                "margin_mode": "cross",
            })
    return {"status": "ok", "code": 200, "data": rows}


def normalize_positions(raw: Dict[str, Any]) -> Dict[str, Any]:
    """V5 positions -> legacy swap_position_info list."""
    data = v5_data(raw)
    items: List[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("positions", "list", "data"):
            nested = data.get(key)
            if isinstance(nested, list):
                items = nested
                break
        if not items and data.get("contract_code"):
            items = [data]
    rows: List[Dict[str, Any]] = []
    for p in items:
        if not isinstance(p, dict):
            continue
        row = dict(p)
        vol = p.get("volume") or p.get("qty") or p.get("position_qty") or p.get("amount") or 0
        row.setdefault("volume", vol)
        row.setdefault("contract_code", p.get("contract_code") or p.get("symbol") or "")
        row.setdefault("direction", p.get("direction") or p.get("side") or "")
        rows.append(row)
    return {"status": "ok", "code": 200, "data": rows}


def normalize_order_place(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = v5_data(raw)
    if not isinstance(data, dict):
        data = raw if isinstance(raw, dict) else {}
    oid = str(
        data.get("order_id_str")
        or data.get("order_id")
        or data.get("id")
        or ""
    )
    return {"status": "ok", "code": 200, "data": {"order_id_str": oid, "order_id": oid}}


def normalize_order_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = v5_data(raw)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


def build_swap_order_body(
    *,
    contract_code: str,
    volume: int,
    direction: str,
    offset: str,
    lever_rate: int,
    order_price_type: str,
    price: Optional[float] = None,
    client_order_id: Optional[int] = None,
    channel_code: str = "",
    margin_mode: str = "cross",
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "contract_code": contract_code,
        "volume": int(volume),
        "direction": direction,
        "offset": offset,
        "lever_rate": int(lever_rate),
        "order_price_type": order_price_type,
        "margin_mode": margin_mode,
    }
    if price is not None and float(price) > 0:
        body["price"] = float(price)
    if client_order_id is not None:
        body["client_order_id"] = int(client_order_id)
    if channel_code:
        body["channel_code"] = channel_code
    return body


def build_cancel_body(
    *,
    contract_code: str,
    order_id: str = "",
    client_order_id: str = "",
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"contract_code": contract_code}
    if order_id:
        body["order_id"] = str(order_id)
    elif client_order_id:
        body["client_order_id"] = str(client_order_id)
    return body


def build_order_query_params(
    *,
    contract_code: str,
    order_id: str = "",
    client_order_id: str = "",
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"contract_code": contract_code}
    if order_id:
        params["order_id"] = str(order_id)
    elif client_order_id:
        params["client_order_id"] = str(client_order_id)
    return params


def build_lever_body(*, contract_code: str, lever_rate: int, margin_mode: str = "cross") -> Dict[str, Any]:
    return {
        "contract_code": contract_code,
        "lever_rate": int(lever_rate),
        "margin_mode": margin_mode,
    }
