"""Тесты HTTP-слоя: раньше api.py не импортировался ни одним тестом."""

from fastapi.testclient import TestClient

from qualifier.api import app

client = TestClient(app)


def test_health_in_mock_mode():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["mock_mode"] is True


def test_chat_then_push_to_crm():
    r = client.post("/api/chat", json={
        "message": "Нужен автоклавный газобетон D500, 180 куб. Телефон: +7 (902) 600-30-40"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["profile"]["project"]
    assert data["turn_count"] == 1

    push = client.post("/api/push-to-crm", json={"session_id": data["session_id"]})
    assert push.status_code == 200
    assert "Газобетон" in push.json()["crm"]["pipeline"]


def test_push_unknown_session_returns_404():
    r = client.post("/api/push-to-crm", json={"session_id": "no-such-session"})
    assert r.status_code == 404


def test_telegram_card_escapes_html():
    from qualifier.models import LeadProfile
    from qualifier.telegram import TelegramNotifier

    profile = LeadProfile(client_name="<b>Иван</b>", summary="a < b & c")
    card = TelegramNotifier(mock_mode=True).format_lead_card(profile)
    assert "&lt;b&gt;Иван&lt;/b&gt;" in card
    assert "a &lt; b &amp; c" in card
