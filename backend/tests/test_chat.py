from app.routers import chat as chat_router
from app.services.orchestrate_service import _fix_mangled_listing_urls


def test_fix_mangled_listing_urls_repairs_missing_singapore_segment():
    # Confirmed live: the LLM occasionally drops "/singapore/" when composing
    # its reply, which turns a real listing URL into a genuine 404.
    mangled = "See [this flat](https://www.99.co/sale/property/419a-northshore-drive-hdb-N7w5PZXcdnRZbjM6crNW7Z?utm_medium=referral)."
    fixed = _fix_mangled_listing_urls(mangled)
    assert "https://www.99.co/singapore/sale/property/419a-northshore-drive-hdb-N7w5PZXcdnRZbjM6crNW7Z" in fixed


def test_fix_mangled_listing_urls_leaves_correct_urls_unchanged():
    correct = "See [this flat](https://www.99.co/singapore/sale/property/614a-edgefield-plains-hdb-4a7oH86utxUkJeTtjvuvSQ?utm_medium=referral)."
    assert _fix_mangled_listing_urls(correct) == correct


def test_send_chat_message_returns_reply_and_thread_id(client, monkeypatch):
    monkeypatch.setattr(
        chat_router,
        "send_chat_message",
        lambda message, thread_id: ("Here are some flats for you.", "thread-123"),
    )

    response = client.post(
        "/chat/message",
        json={"message": "4-room flat near Bishan MRT under 850k", "thread_id": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Here are some flats for you."
    assert body["thread_id"] == "thread-123"


def test_send_chat_message_returns_502_on_upstream_error(client, monkeypatch):
    def raise_error(message, thread_id):
        raise RuntimeError("Agent 'supervisor_agent' not found in the active workspace")

    monkeypatch.setattr(chat_router, "send_chat_message", raise_error)

    response = client.post("/chat/message", json={"message": "hello"})

    assert response.status_code == 502
    assert "supervisor_agent" in response.json()["detail"]
