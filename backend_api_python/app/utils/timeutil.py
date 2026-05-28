"""Time-zone helpers for serializing datetimes to the frontend.

<<<<<<< HEAD
Most ``qd_*`` tables use ``TIMESTAMP WITHOUT TIME ZONE`` columns.  PostgreSQL
connections in this project use a UTC session time zone, and SQLite's
``CURRENT_TIMESTAMP`` is UTC too, so naive DB datetimes are treated as UTC
instants.  API responses are emitted in the server/system time zone with an
explicit offset (for example ``2026-05-17T01:18:29+08:00``), so clients display
the same wall-clock time operators see on the host.
=======
Background
----------
Most ``qd_*`` tables use ``TIMESTAMP WITHOUT TIME ZONE`` columns.  Our PostgreSQL
pool sets ``options="-c timezone=UTC"`` (see ``db_postgres.py``), so ``NOW()``
and driver round-trips store a *naive* **UTC wall-clock** value.  When the
backend serializes that ``datetime`` with ``.isoformat()`` the result has **no
time zone suffix** (e.g. ``"2026-05-08T19:36:00"``).

The frontend uses ``new Date(text)`` to parse it; modern browsers interpret a
naive ISO string as the *browser's local time*, which yields wrong values for
any user whose browser time zone differs from the server's.

To fix this we always serialize timestamps as **UTC ISO 8601 with a ``Z``
suffix**.  The browser then renders them in whatever locale the user is in,
without any further work on the frontend.
>>>>>>> 9ce1a88814ea26c853fbcd7fc8c686672ff6d810
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import os

try:
    from zoneinfo import ZoneInfo  # py>=3.9
except Exception:  # pragma: no cover - fallback for very old runtimes
    ZoneInfo = None  # type: ignore[misc,assignment]

_FIXED_TZ_OFFSETS = {
    "UTC": 0,
    "Etc/UTC": 0,
    "GMT": 0,
    "Asia/Shanghai": 8,
    "Asia/Chongqing": 8,
    "Asia/Hong_Kong": 8,
    "Asia/Taipei": 8,
    "Asia/Singapore": 8,
}

<<<<<<< HEAD

def _system_tzinfo():
    """Resolve the server/system wall-clock time zone.

    Prefer the ``TZ`` env var when it is set by Docker/systemd.  Otherwise use
    Python's view of the host local time zone.
    """
    name = (os.getenv("TZ") or "").strip()
    if name and ZoneInfo is not None:
=======
def _db_naive_tzinfo() -> timezone:
    """Timezone for naive ``datetime`` values read from PostgreSQL.

    The connection pool pins the session to UTC.  Naive timestamps are UTC wall
    clock — **not** the backend container's ``TZ`` (e.g. Asia/Shanghai).
    """
    override = (os.getenv("DB_NAIVE_TIMESTAMP_TZ") or "UTC").strip() or "UTC"
    if override.upper() in ("UTC", "GMT", "ETC/UTC", "ETC/GMT"):
        return timezone.utc
    if ZoneInfo is not None:
>>>>>>> 9ce1a88814ea26c853fbcd7fc8c686672ff6d810
        try:
            return ZoneInfo(override)  # type: ignore[return-value]
        except Exception:
            pass
    if name in _FIXED_TZ_OFFSETS:
        return timezone(timedelta(hours=_FIXED_TZ_OFFSETS[name]))
    match = re.fullmatch(r"(?:UTC|GMT)?([+-])(\d{1,2})(?::?(\d{2}))?", name)
    if match:
        sign = 1 if match.group(1) == "+" else -1
        hours = int(match.group(2))
        minutes = int(match.group(3) or 0)
        if hours <= 23 and minutes <= 59:
            return timezone(sign * timedelta(hours=hours, minutes=minutes))
    return datetime.now().astimezone().tzinfo or timezone.utc


def to_system_iso(value: Any) -> Optional[str]:
    """Convert a value to a system-local ISO 8601 string with an offset.

    Accepts ``datetime``, ISO strings, numeric epoch seconds, or ``None``.
    Returns ``None`` for falsy inputs that aren't valid timestamps.

    Rules
    -----
<<<<<<< HEAD
    * Aware ``datetime`` → converted to the system time zone.
    * Naive ``datetime`` → assumed to be a UTC DB timestamp, then converted to
      the system time zone.
=======
    * Aware ``datetime`` → converted to UTC.
    * Naive ``datetime`` → assumed to be UTC wall clock from our PG session
      (``options=-c timezone=UTC``), then converted/emitted as UTC ``Z``.
>>>>>>> 9ce1a88814ea26c853fbcd7fc8c686672ff6d810
    * Numeric input → treated as epoch seconds (or milliseconds when too large).
    * String input that parses as ISO 8601 → re-emitted in the system time
      zone.  If the string has no time-zone designator, treat it as UTC.
    * Anything else → ``None`` (the route can decide to fall back to ``str()``).
    """
    if value is None or value == "":
        return None

    dt: Optional[datetime] = None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        # Heuristic: > 1e12 is milliseconds.
        if ts > 1e12:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            # Support trailing "Z" (Python <3.11 does not accept it directly).
            normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
            # ``fromisoformat`` accepts both ``T`` and space separators since
            # Python 3.11; on 3.9/3.10 it tolerates space too but not trailing
            # microsecond rounding edge cases.  Replace space defensively.
            if " " in normalized and "T" not in normalized:
                normalized = normalized.replace(" ", "T", 1)
            dt = datetime.fromisoformat(normalized)
        except Exception:
            return None
    else:
        return None

    if dt is None:
        return None

    if dt.tzinfo is None:
<<<<<<< HEAD
        dt = dt.replace(tzinfo=timezone.utc)
    dt_system = dt.astimezone(_system_tzinfo())
    # Drop microseconds for smaller, cleaner payloads while keeping an explicit
    # offset so browser parsing remains unambiguous.
    return dt_system.replace(microsecond=0).isoformat()
=======
        dt = dt.replace(tzinfo=_db_naive_tzinfo())
    dt_utc = dt.astimezone(timezone.utc)
    # Always emit with trailing Z and second-precision (drop microseconds for
    # smaller, cleaner payloads).  ISO 8601 with Z is unambiguous for all
    # browsers.
    return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
>>>>>>> 9ce1a88814ea26c853fbcd7fc8c686672ff6d810


def to_utc_iso(value: Any) -> Optional[str]:
    """Backward-compatible alias for the global API timestamp serializer."""
    return to_system_iso(value)


__all__ = ["to_system_iso", "to_utc_iso"]
