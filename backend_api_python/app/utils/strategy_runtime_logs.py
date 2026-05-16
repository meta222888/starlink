"""Persist strategy runtime lines for the strategy management UI (`qd_strategy_logs`)."""

from __future__ import annotations

import os
from typing import Optional

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _retention_limit() -> int:
    try:
        return max(0, int(os.getenv("STRATEGY_LOG_RETENTION", "1000")))
    except Exception:
        return 1000


def prune_strategy_logs(strategy_id: int, keep: Optional[int] = None) -> int:
    """Keep only the newest N log rows for a strategy. Best-effort helper."""
    sid = int(strategy_id)
    limit = _retention_limit() if keep is None else max(0, int(keep))
    if limit <= 0:
        return 0
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            DELETE FROM qd_strategy_logs
            WHERE strategy_id = ?
              AND id NOT IN (
                SELECT id FROM qd_strategy_logs
                WHERE strategy_id = ?
                ORDER BY id DESC
                LIMIT ?
              )
            """,
            (sid, sid, limit),
        )
        deleted = int(getattr(cur, "rowcount", 0) or 0)
        db.commit()
        cur.close()
        return deleted


def clear_strategy_logs(strategy_id: int) -> int:
    """Delete all runtime logs for a strategy."""
    sid = int(strategy_id)
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute("DELETE FROM qd_strategy_logs WHERE strategy_id = ?", (sid,))
        deleted = int(getattr(cur, "rowcount", 0) or 0)
        db.commit()
        cur.close()
        return deleted


def append_strategy_log(strategy_id: int, level: str, message: str) -> None:
    """Best-effort insert; never raises to caller."""
    try:
        sid = int(strategy_id)
        lv = (level or "info").strip().lower()[:20]
        msg = str(message or "").strip()
        if not msg:
            return
        msg = msg[:8000]
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "INSERT INTO qd_strategy_logs (strategy_id, level, message) VALUES (?, ?, ?)",
                (sid, lv, msg),
            )
            db.commit()
            cur.close()
        prune_strategy_logs(sid)
    except Exception as e:
        logger.debug("append_strategy_log skip: %s", e)
