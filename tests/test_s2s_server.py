"""Unit tests for s2s-postback-server/server.py: safe_float parsing, lead
persistence, the daily-report scheduling helpers, and the /postback endpoint's
secret check, HTML escaping, and health probe."""
import time
from datetime import datetime, timezone

import pytest
import server
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def temp_lead_db(tmp_path, monkeypatch):
    """Redirects the leads DB to a scratch file for every test in this module,
    so tests never touch the real data/leads.db. Lifespan (and its background
    daily_report_loop task) intentionally isn't triggered here - TestClient is
    used without `with`, so init_db() is called explicitly instead."""
    db_file = tmp_path / "leads.db"
    monkeypatch.setattr(server, "DB_FILE", str(db_file))
    server.init_db()
    yield db_file


def test_safe_float_valid_numbers():
    assert server.safe_float("12.5") == 12.5
    assert server.safe_float("0") == 0.0


def test_safe_float_malformed_returns_default_without_raising():
    assert server.safe_float("not-a-number") == 0.0
    assert server.safe_float("") == 0.0
    assert server.safe_float(None) == 0.0
    assert server.safe_float("abc", default=-1) == -1


def test_health_endpoint_never_touches_telegram(monkeypatch):
    called = {"sent": False}

    async def fake_send(text):
        called["sent"] = True

    monkeypatch.setattr(server, "send_to_telegram", fake_send)
    client = TestClient(server.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert called["sent"] is False


def test_postback_rejects_missing_or_wrong_secret(monkeypatch):
    monkeypatch.setattr(server, "POSTBACK_SECRET", "correct-secret")
    client = TestClient(server.app)

    resp = client.get("/postback")  # no secret param at all
    assert resp.status_code == 403

    resp = client.get("/postback", params={"secret": "wrong"})
    assert resp.status_code == 403


def test_postback_accepts_correct_secret_and_escapes_html(monkeypatch):
    monkeypatch.setattr(server, "POSTBACK_SECRET", "correct-secret")

    captured = {}

    async def fake_send(text):
        captured["text"] = text

    monkeypatch.setattr(server, "send_to_telegram", fake_send)

    client = TestClient(server.app)
    resp = client.get("/postback", params={
        "secret": "correct-secret",
        "click_id": "<script>alert(1)</script>",
        "country": "US & <UK>",
        "payout": "5.00",
    })

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    # The raw payload must never appear unescaped in the outgoing Telegram message.
    assert "<script>" not in captured["text"]
    assert "&lt;script&gt;" in captured["text"]


def test_postback_malformed_payout_does_not_crash(monkeypatch):
    monkeypatch.setattr(server, "POSTBACK_SECRET", "correct-secret")

    async def fake_send(text):
        pass

    monkeypatch.setattr(server, "send_to_telegram", fake_send)

    client = TestClient(server.app)
    resp = client.get("/postback", params={"secret": "correct-secret", "payout": "garbage"})
    assert resp.status_code == 200


def test_postback_persists_lead(monkeypatch):
    monkeypatch.setattr(server, "POSTBACK_SECRET", "correct-secret")

    async def fake_send(text):
        pass

    monkeypatch.setattr(server, "send_to_telegram", fake_send)

    client = TestClient(server.app)
    resp = client.get("/postback", params={
        "secret": "correct-secret", "click_id": "555", "payout": "7.5", "country": "FR",
    })
    assert resp.status_code == 200

    stats = server.get_lead_stats_since(0)
    assert stats["count"] == 1
    assert stats["charged_total"] == 7.5
    assert stats["hold_total"] == 0


def test_save_lead_and_get_stats_since():
    now = int(time.time())
    server.save_lead("111", 5.0, 0.0, True, "US", "Android", "push", "wifi", "AT&T")
    server.save_lead("222", 0.0, 2.5, False, "DE", "iOS", "push", "4g", "T-Mobile")

    stats = server.get_lead_stats_since(now - 10)
    assert stats["count"] == 2
    assert stats["charged_total"] == 5.0
    assert stats["hold_total"] == 2.5


def test_get_lead_stats_since_excludes_leads_before_cutoff():
    server.save_lead("old", 1.0, 0.0, True, "US", "Android", "push", "wifi", "AT&T")
    stats = server.get_lead_stats_since(int(time.time()) + 1000)  # cutoff in the future excludes everything
    assert stats == {"count": 0, "charged_total": 0, "hold_total": 0}


def test_compute_next_run_later_today():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert server.compute_next_run(now, target_hour=21) == datetime(2026, 1, 1, 21, 0, tzinfo=timezone.utc)


def test_compute_next_run_rolls_to_tomorrow_if_past():
    now = datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc)
    assert server.compute_next_run(now, target_hour=21) == datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)


def test_compute_next_run_at_exact_target_hour_rolls_to_tomorrow():
    # Firing "now" would re-trigger immediately on every loop iteration around the
    # target hour, so an exact match must roll to the next day, not fire in place.
    now = datetime(2026, 1, 1, 21, 0, tzinfo=timezone.utc)
    assert server.compute_next_run(now, target_hour=21) == datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)


def test_format_daily_report_contains_stats():
    text = server.format_daily_report({"count": 5, "charged_total": 12.5, "hold_total": 3.0})
    assert "5" in text
    assert "12.50" in text
    assert "3.00" in text


def test_stats_rejects_missing_or_wrong_secret(monkeypatch):
    monkeypatch.setattr(server, "POSTBACK_SECRET", "correct-secret")
    client = TestClient(server.app)

    resp = client.get("/stats")
    assert resp.status_code == 403

    resp = client.get("/stats", params={"secret": "wrong"})
    assert resp.status_code == 403


def test_stats_returns_aggregated_leads_with_correct_secret(monkeypatch):
    monkeypatch.setattr(server, "POSTBACK_SECRET", "correct-secret")
    server.save_lead("111", 5.0, 0.0, True, "US", "Android", "push", "wifi", "AT&T")
    server.save_lead("222", 0.0, 2.5, False, "DE", "iOS", "push", "4g", "T-Mobile")

    client = TestClient(server.app)
    resp = client.get("/stats", params={"secret": "correct-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["charged_total"] == 5.0
    assert body["hold_total"] == 2.5


def test_stats_hours_window_excludes_old_leads(monkeypatch):
    monkeypatch.setattr(server, "POSTBACK_SECRET", "correct-secret")
    old_ts = int(time.time()) - 100_000
    conn_db = server.DB_FILE
    import sqlite3
    conn = sqlite3.connect(conn_db)
    conn.execute(
        "INSERT INTO leads (click_id, payout, hold_payout, is_charged, country, os_sys, traffic_type, connection_type, carrier, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("old", 9.0, 0.0, 1, "US", "Android", "push", "wifi", "AT&T", old_ts),
    )
    conn.commit()
    conn.close()

    client = TestClient(server.app)
    resp = client.get("/stats", params={"secret": "correct-secret", "hours": 1})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
