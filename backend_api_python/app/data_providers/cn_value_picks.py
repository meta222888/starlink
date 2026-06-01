"""A-share value screen: low P/E + high dividend yield (Eastmoney + AkShare)."""
from __future__ import annotations

import math
import os
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

import pandas as pd
import requests

from app.data_sources.cn_hk_fundamentals import _PROXY_KEYS, _bypass_proxy, _float_clean
from app.utils.logger import get_logger

logger = get_logger(__name__)

CN_VALUE_PICKS_CACHE_KEY = "ai_asset_snapshot_cn_value_picks"
CN_VALUE_PICKS_TTL_SEC = 864000  # 10 days
CN_VALUE_PICKS_EMPTY_TTL_SEC = 600  # failed/empty — retry sooner, do not lock in 10d empty

_DEFAULT_MAX_PE = 25.0
_DEFAULT_MIN_DIVIDEND_PCT = 2.0
_DEFAULT_TOP_N = 20

# Eastmoney clist (browser-verified; works on home / CN cloud / HK — not push2 / 82.push2)
_DEFAULT_EASTMONEY_CLIST_HOST = "push2delay.eastmoney.com"
_DEFAULT_EASTMONEY_UT = (
    "bd1d9ddb04089700f9693c791ad93d5a87f52eed74699f5af06deaf41daa9f2"
)
_EASTMONEY_CLIST_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
_EASTMONEY_SPOT_FIELDS = "f12,f14,f9"
_EASTMONEY_CLIST_PAGE_SIZE = 5000
_EASTMONEY_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/center/gridlist.html",
    "Accept": "application/json, text/plain, */*",
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalize_a_code(raw: Any) -> str:
    s = str(raw or "").strip().replace(".0", "")
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    return digits.zfill(6)[-6:]


def _is_excluded_name(name: str) -> bool:
    n = (name or "").strip().upper()
    if not n:
        return True
    if "ST" in n:
        return True
    if n.startswith("*"):
        return True
    return False


def _eastmoney_clist_host() -> str:
    return (os.getenv("EASTMONEY_CLIST_HOST") or _DEFAULT_EASTMONEY_CLIST_HOST).strip().strip("/")


def _eastmoney_ut() -> str:
    return (os.getenv("EASTMONEY_UT") or _DEFAULT_EASTMONEY_UT).strip()


def _eastmoney_clist_page_size() -> int:
    return _env_int("EASTMONEY_CLIST_PAGE_SIZE", _EASTMONEY_CLIST_PAGE_SIZE)


@contextmanager
def _eastmoney_clist_direct() -> Generator[None, None, None]:
    """Direct HTTPS to push2delay — do not use CN_DATA_PROXY_URL (relay often breaks clist)."""
    saved: Dict[str, str] = {}
    for key in _PROXY_KEYS + ("NO_PROXY", "no_proxy"):
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    try:
        yield
    finally:
        for key in _PROXY_KEYS + ("NO_PROXY", "no_proxy"):
            os.environ.pop(key, None)
        for key, val in saved.items():
            os.environ[key] = val


def _pe_from_em_f9(raw: Any) -> Optional[float]:
    """Dynamic P/E from clist field f9 (push2delay returns human-readable PE, e.g. 8.5 or -12.3)."""
    val = _float_clean(raw)
    if val is None:
        return None
    # Legacy push2/82.push2 sometimes return integer scale (e.g. 367 → 3.67); push2delay does not.
    if abs(val) >= 100 and abs(val - round(val)) < 1e-6:
        return val / 100.0
    return val


def _parse_clist_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Eastmoney clist ``data`` block into row dicts."""
    return _iter_clist_diff(data.get("diff"))


def _iter_clist_diff(diff: Any) -> List[Dict[str, Any]]:
    if isinstance(diff, list):
        return [row for row in diff if isinstance(row, dict)]
    if isinstance(diff, dict):
        return [row for row in diff.values() if isinstance(row, dict)]
    return []


def _fetch_eastmoney_clist_page(*, pn: int, pz: int) -> Dict[str, Any]:
    host = _eastmoney_clist_host()
    url = f"https://{host}/api/qt/clist/get"
    params = {
        "pn": str(pn),
        "pz": str(pz),
        "po": "1",
        "np": "1",
        "ut": _eastmoney_ut(),
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": _EASTMONEY_CLIST_FS,
        "fields": _EASTMONEY_SPOT_FIELDS,
    }
    with _eastmoney_clist_direct():
        resp = requests.get(
            url,
            params=params,
            headers=_EASTMONEY_REQUEST_HEADERS,
            timeout=30,
        )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or payload.get("rc") != 0:
        raise ValueError(f"eastmoney clist rc={payload.get('rc') if isinstance(payload, dict) else 'invalid'}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("eastmoney clist missing data")
    return data


def _fetch_spot_pe_table_em_direct() -> pd.DataFrame:
    """Full A-share spot table via push2delay clist (f12 code, f14 name, f9 PE)."""
    page_size = max(100, _eastmoney_clist_page_size())
    rows: List[Dict[str, Any]] = []

    first = _fetch_eastmoney_clist_page(pn=1, pz=page_size)
    total = int(first.get("total") or 0)
    rows.extend(_iter_clist_diff(first.get("diff")))

    per_page = len(_iter_clist_diff(first.get("diff"))) or page_size
    if total > len(rows) and per_page > 0:
        pages = math.ceil(total / per_page)
        for pn in range(2, pages + 1):
            page = _fetch_eastmoney_clist_page(pn=pn, pz=page_size)
            rows.extend(_iter_clist_diff(page.get("diff")))
            time.sleep(0.3)

    if not rows:
        return pd.DataFrame()

    records: List[Dict[str, Any]] = []
    for item in rows:
        code = _normalize_a_code(item.get("f12"))
        if not code:
            continue
        records.append({
            "code": code,
            "name": str(item.get("f14") or "").strip(),
            "pe": _pe_from_em_f9(item.get("f9")),
        })

    slim = pd.DataFrame(records)
    slim = slim[slim["code"].astype(bool)]
    logger.info(
        "cn_value_picks: eastmoney clist spot rows=%d host=%s total=%s",
        len(slim),
        _eastmoney_clist_host(),
        total,
    )
    return slim


def _fhps_report_dates() -> List[str]:
    """Recent Eastmoney dividend report periods (YYYYMMDD).

    Prefer already-published periods (prior year annual first) — future
    ``YYYY1231`` often returns empty when called mid-year.
    """
    year = datetime.now().year
    month = datetime.now().month
    candidates = [
        f"{year - 1}1231",
        f"{year - 1}0630",
    ]
    if month >= 7:
        candidates.insert(0, f"{year}0630")
    candidates.append(f"{year}1231")
    out: List[str] = []
    seen = set()
    for d in candidates:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _fetch_spot_pe_table_akshare() -> pd.DataFrame:
    import akshare as ak  # type: ignore

    with _bypass_proxy():
        df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        return pd.DataFrame()
    code_col = "代码" if "代码" in df.columns else None
    name_col = "名称" if "名称" in df.columns else None
    pe_col = next((c for c in df.columns if "市盈率" in str(c)), None)
    if not code_col or not name_col or not pe_col:
        logger.warning("cn_value_picks: akshare spot missing columns: %s", list(df.columns))
        return pd.DataFrame()
    slim = df[[code_col, name_col, pe_col]].copy()
    slim.columns = ["code", "name", "pe"]
    slim["code"] = slim["code"].map(_normalize_a_code)
    slim["pe"] = slim["pe"].map(_pe_from_em_f9)
    slim = slim[slim["code"].astype(bool)]
    return slim


def _log_pick_pipeline_stats(
    *,
    spot: pd.DataFrame,
    div: pd.DataFrame,
    merged: pd.DataFrame,
    candidates: List[Dict[str, Any]],
    picks: List[Dict[str, Any]],
    max_pe: float,
    min_div: float,
) -> None:
    """Diagnostic counts for empty-pick debugging (see scripts/diagnose_cn_value_picks.py)."""
    pe_vals = [_float_clean(c.get("pe_ratio")) for c in candidates]
    pe_ok = [p for p in pe_vals if p is not None and 0 < p <= max_pe]
    div_vals = [_float_clean(c.get("dividend_yield_pct")) for c in candidates]
    div_ok = [d for d in div_vals if d is not None and d >= min_div]
    logger.info(
        "cn_value_picks: pipeline spot=%d div=%d merged=%d candidates=%d "
        "pe_valid=%d pe_pass_max=%.0f div_pass_min=%d picks=%d",
        len(spot),
        len(div),
        len(merged),
        len(candidates),
        sum(p is not None and p > 0 for p in pe_vals),
        max_pe,
        len(div_ok),
        len(picks),
    )
    if candidates and not picks:
        sample = candidates[:3]
        logger.warning(
            "cn_value_picks: zero picks after filters (max_pe=%s min_div=%s); sample=%s",
            max_pe,
            min_div,
            [
                {
                    "symbol": c.get("symbol"),
                    "pe": c.get("pe_ratio"),
                    "div": c.get("dividend_yield_pct"),
                }
                for c in sample
            ],
        )


def _fetch_spot_pe_table() -> pd.DataFrame:
    try:
        slim = _fetch_spot_pe_table_em_direct()
        if not slim.empty:
            return slim
    except Exception as exc:
        logger.warning("cn_value_picks: eastmoney clist failed: %s", exc)

    try:
        slim = _fetch_spot_pe_table_akshare()
        if not slim.empty:
            logger.info("cn_value_picks: spot fallback akshare rows=%d", len(slim))
            return slim
    except ImportError:
        logger.warning("cn_value_picks: akshare not installed (spot fallback skipped)")
    except Exception as exc:
        logger.warning("cn_value_picks: akshare spot fallback failed: %s", exc)
    return pd.DataFrame()


def _fetch_dividend_table() -> pd.DataFrame:
    import akshare as ak  # type: ignore

    for report_date in _fhps_report_dates():
        try:
            with _bypass_proxy():
                df = ak.stock_fhps_em(date=report_date)
        except Exception as exc:
            logger.debug("cn_value_picks: stock_fhps_em(%s) failed: %s", report_date, exc)
            continue
        if df is None or df.empty or "代码" not in df.columns:
            continue
        div_col = "现金分红-股息率" if "现金分红-股息率" in df.columns else None
        if not div_col:
            continue
        slim = df[["代码", div_col]].copy()
        slim.columns = ["code", "dividend_yield_pct"]
        if "名称" in df.columns:
            slim["name_fhps"] = df["名称"].astype(str).values
        slim["code"] = slim["code"].map(_normalize_a_code)
        slim["dividend_yield_pct"] = slim["dividend_yield_pct"].map(_float_clean)
        slim = slim[slim["code"].astype(bool)]
        if not slim.empty:
            logger.info(
                "cn_value_picks: loaded dividend yields from stock_fhps_em(%s), rows=%d",
                report_date,
                len(slim),
            )
            slim["dividend_report_date"] = report_date
            return slim
    return pd.DataFrame()


def score_value_pick(pe: float, dividend_yield_pct: float) -> float:
    """Higher is better: reward dividend yield, penalize P/E (both must be positive)."""
    if pe is None or dividend_yield_pct is None:
        return 0.0
    if pe <= 0 or dividend_yield_pct <= 0:
        return 0.0
    # Earnings yield * dividend yield — favors low PE and high payout
    return round((dividend_yield_pct / 100.0) / pe * 1000.0, 6)


def rank_cn_value_candidates(
    rows: List[Dict[str, Any]],
    *,
    max_pe: float = _DEFAULT_MAX_PE,
    min_dividend_pct: float = _DEFAULT_MIN_DIVIDEND_PCT,
    top_n: int = _DEFAULT_TOP_N,
) -> List[Dict[str, Any]]:
    """Filter and rank in-memory rows (used by tests and compute)."""
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or "")
        if _is_excluded_name(name):
            continue
        code = _normalize_a_code(row.get("symbol") or row.get("code"))
        if not code:
            continue
        pe = _float_clean(row.get("pe_ratio") if row.get("pe_ratio") is not None else row.get("pe"))
        div = _float_clean(
            row.get("dividend_yield_pct")
            if row.get("dividend_yield_pct") is not None
            else row.get("dividend_yield")
        )
        if pe is None or div is None:
            continue
        if pe <= 0 or pe > max_pe or div < min_dividend_pct:
            continue
        sc = score_value_pick(pe, div)
        if sc <= 0:
            continue
        filtered.append({
            "market": "CNStock",
            "symbol": code,
            "name": name or code,
            "pe_ratio": round(pe, 4),
            "dividend_yield_pct": round(div, 4),
            "score": sc,
        })

    filtered.sort(key=lambda r: (-float(r["score"]), -float(r["dividend_yield_pct"]), float(r["pe_ratio"])))
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(filtered[:top_n], start=1):
        item = dict(row)
        item["rank"] = i
        out.append(item)
    return out


def compute_cn_value_picks() -> Dict[str, Any]:
    """Build top-N A-share picks; returns metadata envelope even when empty."""
    max_pe = _env_float("CN_VALUE_PICKS_MAX_PE", _DEFAULT_MAX_PE)
    min_div = _env_float("CN_VALUE_PICKS_MIN_DIVIDEND_PCT", _DEFAULT_MIN_DIVIDEND_PCT)
    top_n = _env_int("CN_VALUE_PICKS_TOP_N", _DEFAULT_TOP_N)

    meta: Dict[str, Any] = {
        "market": "CNStock",
        "criteria": {
            "max_pe_ratio": max_pe,
            "min_dividend_yield_pct": min_div,
            "top_n": top_n,
        },
        "computed_at": int(time.time()),
        "source": None,
        "picks": [],
    }

    try:
        spot = _fetch_spot_pe_table()
        div = _fetch_dividend_table()
    except Exception as exc:
        logger.warning("cn_value_picks: batch fetch failed: %s", exc)
        return meta

    if spot.empty or div.empty:
        logger.warning(
            "cn_value_picks: incomplete data (spot_rows=%d, div_rows=%d)",
            len(spot),
            len(div),
        )
        return meta

    merged = spot.merge(div, on="code", how="inner", suffixes=("_spot", "_fhps"))
    if merged.empty:
        logger.warning(
            "cn_value_picks: no overlapping symbols after merge (spot=%d div=%d)",
            len(spot),
            len(div),
        )
        return meta

    candidates: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        name = str(row.get("name") or row.get("name_fhps") or "").strip()
        candidates.append({
            "symbol": row["code"],
            "name": name,
            "pe_ratio": row.get("pe"),
            "dividend_yield_pct": row.get("dividend_yield_pct"),
        })

    picks = rank_cn_value_candidates(
        candidates,
        max_pe=max_pe,
        min_dividend_pct=min_div,
        top_n=top_n,
    )
    _log_pick_pipeline_stats(
        spot=spot,
        div=div,
        merged=merged,
        candidates=candidates,
        picks=picks,
        max_pe=max_pe,
        min_div=min_div,
    )
    meta["picks"] = picks
    meta["source"] = (
        f"eastmoney_clist:{_eastmoney_clist_host()}+akshare_em:stock_fhps_em"
    )
    meta["candidate_count"] = len(candidates)
    meta["dividend_report_date"] = div.iloc[0].get("dividend_report_date") if "dividend_report_date" in div.columns else None

    if picks:
        logger.info("cn_value_picks: ranked %d picks (from %d candidates)", len(picks), len(candidates))
    else:
        logger.warning("cn_value_picks: no symbols passed filters (candidates=%d)", len(candidates))
    return meta


def compute_cn_value_picks_list() -> List[Dict[str, Any]]:
    """Return only the picks list (for snapshot payload)."""
    block = compute_cn_value_picks()
    picks = block.get("picks")
    return picks if isinstance(picks, list) else []


def get_cn_value_picks_for_snapshot(*, force: bool = False) -> List[Dict[str, Any]]:
    """Cached picks for snapshot: success → 10d TTL; empty/failed → 10min TTL."""
    from app.data_providers import get_cached, set_cached

    if not force:
        cached = get_cached(CN_VALUE_PICKS_CACHE_KEY)
        if isinstance(cached, list) and len(cached) > 0:
            return cached

    block = compute_cn_value_picks()
    picks = block.get("picks") if isinstance(block.get("picks"), list) else []
    ttl = CN_VALUE_PICKS_TTL_SEC if picks else CN_VALUE_PICKS_EMPTY_TTL_SEC
    set_cached(CN_VALUE_PICKS_CACHE_KEY, picks, ttl)
    if not picks:
        logger.warning(
            "cn_value_picks: snapshot returning empty (spot/div merge or filters); "
            "source=%s candidates=%s criteria=%s — retry in %ss or use ?force=1",
            block.get("source"),
            block.get("candidate_count"),
            block.get("criteria"),
            ttl,
        )
    return picks
