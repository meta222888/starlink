"""Tests for strategy runtime log API behavior."""

from datetime import datetime

from flask import g

from app.routes import strategy as strategy_routes


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self._rows

    def close(self):
        return None


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return _FakeCursor(self._rows)


class _FakeStrategyService:
    def get_strategy(self, strategy_id, user_id=None):
        return {"id": strategy_id, "user_id": user_id}


def test_get_strategy_logs_returns_newest_first(app, monkeypatch):
    rows = [
        {"id": 3, "strategy_id": 9, "level": "info", "message": "newest", "timestamp": None},
        {"id": 2, "strategy_id": 9, "level": "warn", "message": "middle", "timestamp": None},
        {"id": 1, "strategy_id": 9, "level": "error", "message": "oldest", "timestamp": None},
    ]
    monkeypatch.setattr(strategy_routes, "get_strategy_service", lambda: _FakeStrategyService())
    monkeypatch.setattr(strategy_routes, "get_db_connection", lambda: _FakeDb(rows))

    with app.test_request_context("/strategies/logs?id=9"):
        g.user_id = 123
        response = strategy_routes.get_strategy_logs.__wrapped__()

    payload = response.get_json()
    assert payload["code"] == 1
    assert [item["message"] for item in payload["data"]] == ["newest", "middle", "oldest"]


def test_get_strategy_logs_returns_system_timezone(app, monkeypatch):
    rows = [
        {
            "id": 1,
            "strategy_id": 9,
            "level": "info",
            "message": "started",
            "timestamp": datetime(2026, 5, 16, 17, 18, 29),
        },
    ]
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setattr(strategy_routes, "get_strategy_service", lambda: _FakeStrategyService())
    monkeypatch.setattr(strategy_routes, "get_db_connection", lambda: _FakeDb(rows))

    with app.test_request_context("/strategies/logs?id=9"):
        g.user_id = 123
        response = strategy_routes.get_strategy_logs.__wrapped__()

    payload = response.get_json()
    assert payload["data"][0]["timestamp"] == "2026-05-17T01:18:29+08:00"
