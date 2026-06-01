#!/usr/bin/env python3
"""One-shot diagnostic for cn_value_picks (run on the server)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow: cd backend_api_python && python3 scripts/diagnose_cn_value_picks.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_providers.cn_value_picks import (  # noqa: E402
    _eastmoney_clist_host,
    _fetch_dividend_table,
    _fetch_eastmoney_clist_page,
    _fetch_spot_pe_table,
    _pe_from_em_f9,
    compute_cn_value_picks,
)


def main() -> int:
    print("=== Eastmoney clist (page 1) ===")
    try:
        data = _fetch_eastmoney_clist_page(pn=1, pz=5)
        diff = data.get("diff")
        items = list(diff.values()) if isinstance(diff, dict) else (diff or [])
        print("host:", _eastmoney_clist_host())
        print("total:", data.get("total"), "page_items:", len(items))
        for row in items[:3]:
            print(
                " sample",
                row.get("f12"),
                row.get("f14"),
                "f9_raw=",
                row.get("f9"),
                "pe=",
                _pe_from_em_f9(row.get("f9")),
            )
    except Exception as exc:
        print("clist FAIL:", exc)
        return 1

    print("\n=== Spot / dividend tables ===")
    spot = _fetch_spot_pe_table()
    div = _fetch_dividend_table()
    print("spot_rows:", len(spot))
    print("div_rows:", len(div))
    if not spot.empty:
        pe = spot["pe"].dropna()
        print("spot pe>0:", int((pe > 0).sum()), "pe<=25:", int(((pe > 0) & (pe <= 25)).sum()))
    if not div.empty:
        d = div["dividend_yield_pct"].dropna()
        print("div>=2:", int((d >= 2).sum()))

    if not spot.empty and not div.empty:
        merged = spot.merge(div, on="code", how="inner")
        print("merged_rows:", len(merged))

    print("\n=== compute_cn_value_picks ===")
    block = compute_cn_value_picks()
    picks = block.get("picks") or []
    print("picks:", len(picks))
    print("source:", block.get("source"))
    print("candidate_count:", block.get("candidate_count"))
    if picks:
        print("top1:", json.dumps(picks[0], ensure_ascii=False))
    return 0 if picks else 2


if __name__ == "__main__":
    raise SystemExit(main())
