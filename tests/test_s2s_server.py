"""Unit tests for s2s-postback-server/server.py: safe_float parsing and the
/postback endpoint's secret check, HTML escaping, and health probe."""
import server
from fastapi.testclient import TestClient


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
