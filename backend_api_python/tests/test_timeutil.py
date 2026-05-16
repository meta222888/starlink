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
