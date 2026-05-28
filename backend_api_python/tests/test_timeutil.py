<<<<<<< HEAD
"""Tests for API timestamp serialization."""

from datetime import datetime, timezone

from app.utils.timeutil import to_system_iso


def test_to_system_iso_uses_tz_env_for_utc_datetime(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")

    value = datetime(2026, 5, 16, 17, 18, 29, tzinfo=timezone.utc)

    assert to_system_iso(value) == "2026-05-17T01:18:29+08:00"


def test_to_system_iso_treats_naive_db_timestamp_as_utc(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")

    value = datetime(2026, 5, 16, 17, 18, 29)

    assert to_system_iso(value) == "2026-05-17T01:18:29+08:00"
=======
"""Tests for UTC serialization of naive DB timestamps."""

from datetime import datetime, timezone

from app.utils.timeutil import to_utc_iso


def test_naive_datetime_from_pg_session_is_utc_not_container_tz():
    # PG pool uses timezone=UTC: 17:59 Shanghai event → 09:59 naive in DB.
    naive = datetime(2026, 5, 25, 9, 59, 30)
    assert to_utc_iso(naive) == "2026-05-25T09:59:30Z"


def test_aware_utc_datetime_emits_z():
    aware = datetime(2026, 5, 25, 9, 59, 30, tzinfo=timezone.utc)
    assert to_utc_iso(aware) == "2026-05-25T09:59:30Z"


def test_iso_string_with_z_re_emitted():
    assert to_utc_iso("2026-05-25T09:59:30Z") == "2026-05-25T09:59:30Z"
>>>>>>> 9ce1a88814ea26c853fbcd7fc8c686672ff6d810
