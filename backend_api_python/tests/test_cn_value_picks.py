"""Unit tests for A-share value pick ranking."""
from __future__ import annotations

from app.data_providers.cn_value_picks import (
    rank_cn_value_candidates,
    score_value_pick,
    _is_excluded_name,
    _normalize_a_code,
    _parse_clist_rows,
    _pe_from_em_f9,
)


def test_normalize_a_code():
    assert _normalize_a_code("600519") == "600519"
    assert _normalize_a_code("1") == "000001"
    assert _normalize_a_code(600519) == "600519"


def test_excludes_st_names():
    assert _is_excluded_name("ST某某") is True
    assert _is_excluded_name("*ST测试") is True
    assert _is_excluded_name("贵州茅台") is False


def test_score_value_pick():
    assert score_value_pick(10, 5) > score_value_pick(20, 5)
    assert score_value_pick(10, 5) > score_value_pick(10, 2)
    assert score_value_pick(0, 5) == 0.0


def test_pe_from_em_f9_push2delay_and_legacy_scale():
    # push2delay: human-readable decimals (do not divide)
    assert _pe_from_em_f9(46.79) == 46.79
    assert _pe_from_em_f9(-12.3) == -12.3
    # legacy push2 integer scale (e.g. 平安银行 f9=367 → PE 3.67)
    assert _pe_from_em_f9(367) == 3.67
    assert _pe_from_em_f9(None) is None


def test_parse_clist_rows():
    rows = _parse_clist_rows({
        "total": 2,
        "diff": {
            "0": {"f12": "600036", "f14": "招商银行", "f9": 6.5},
            "1": {"f12": "600519", "f14": "贵州茅台", "f9": 22.1},
        },
    })
    assert len(rows) == 2
    assert rows[0]["f12"] == "600036"


def test_rank_with_realistic_em_pe_scale():
    rows = [
        {"symbol": "600036", "name": "招商银行", "pe_ratio": 6.5, "dividend_yield_pct": 5.0},
        {"symbol": "601398", "name": "工商银行", "pe_ratio": 5.2, "dividend_yield_pct": 6.0},
    ]
    out = rank_cn_value_candidates(rows, max_pe=25, min_dividend_pct=2, top_n=5)
    assert len(out) == 2


def test_rank_cn_value_candidates_top_n():
    rows = [
        {"symbol": "600519", "name": "茅台", "pe_ratio": 22, "dividend_yield_pct": 3.5},
        {"symbol": "600036", "name": "招行", "pe_ratio": 6, "dividend_yield_pct": 5.0},
        {"symbol": "000001", "name": "平安", "pe_ratio": 8, "dividend_yield_pct": 4.0},
        {"symbol": "300001", "name": "ST测试", "pe_ratio": 5, "dividend_yield_pct": 8.0},
        {"symbol": "600000", "name": "浦发", "pe_ratio": 40, "dividend_yield_pct": 6.0},
    ]
    out = rank_cn_value_candidates(rows, max_pe=25, min_dividend_pct=2, top_n=2)
    assert len(out) == 2
    assert out[0]["rank"] == 1
    assert all("ST" not in p["name"] for p in out)
    assert all(p["pe_ratio"] <= 25 for p in out)
    symbols = {p["symbol"] for p in out}
    assert "600036" in symbols or "000001" in symbols
