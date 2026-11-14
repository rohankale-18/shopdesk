import json

import pytest

from app.core.errors import UpstreamError
from app.services import ai
from app.services.chat import SYSTEM_PROMPT


@pytest.fixture()
def fake_model(monkeypatch):
    """Replace the Groq stream; records every message list the model receives.

    Reply N streams as two pieces: "reply" and " N".
    """
    calls: list[list[dict]] = []

    def stream(messages, **_):
        calls.append(messages)
        return iter(["reply", f" {len(calls)}"])

    monkeypatch.setattr(ai, "stream", stream)
    return calls


def new_chat(client) -> int:
    r = client.post("/api/chat/conversations")
    assert r.status_code == 201
    assert r.json()["messages"] == []
    return r.json()["id"]


def send(client, cid: int, content: str) -> list[tuple[str, dict]]:
    """Post a message and return the Server-Sent Events as (event, data) pairs."""
    r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": content})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    events, name = [], None
    for line in r.text.splitlines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((name, json.loads(line.removeprefix("data: "))))
    return events


def test_reply_streams_then_both_turns_are_saved(client, fake_model):
    cid = new_chat(client)
    events = send(client, cid, "  Where is my order?  ")

    assert events[:2] == [("delta", {"text": "reply"}), ("delta", {"text": " 1"})]
    name, done = events[-1]
    assert name == "done"
    assert done["user_message"]["content"] == "Where is my order?"
    reply = done["assistant_message"]
    assert (reply["role"], reply["content"]) == ("assistant", "reply 1")

    convo = client.get(f"/api/chat/conversations/{cid}").json()
    assert convo["title"] == "Where is my order?"
    assert [(m["role"], m["content"]) for m in convo["messages"]] == [
        ("user", "Where is my order?"),
        ("assistant", "reply 1"),
    ]


def test_model_gets_system_prompt_and_history(client, fake_model):
    cid = new_chat(client)
    send(client, cid, "first")
    send(client, cid, "second")

    assert fake_model[1] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply 1"},
        {"role": "user", "content": "second"},
    ]
    # The title stays the first message.
    assert client.get(f"/api/chat/conversations/{cid}").json()["title"] == "first"


def test_setup_error_is_a_normal_json_error(client):
    # No GROQ_API_KEY in tests, so the real ai.stream raises a 503 before streaming starts.
    cid = new_chat(client)
    r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hello"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "service_unavailable"
    assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []


def test_mid_stream_error_sends_error_event_and_saves_nothing(client, monkeypatch):
    def broken_stream(messages, **_):
        yield "partial"
        raise UpstreamError("The AI provider timed out. Try again.")

    monkeypatch.setattr(ai, "stream", broken_stream)
    cid = new_chat(client)
    events = send(client, cid, "hello")

    assert events[0] == ("delta", {"text": "partial"})
    timeout = {"code": "upstream_error", "message": "The AI provider timed out. Try again."}
    assert events[-1] == ("error", timeout)
    assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []


def test_list_newest_first_and_delete(client, fake_model):
    a, b = new_chat(client), new_chat(client)
    send(client, a, "bump a")

    ids = [c["id"] for c in client.get("/api/chat/conversations").json()]
    assert ids.index(a) < ids.index(b)

    assert client.delete(f"/api/chat/conversations/{a}").status_code == 204
    assert client.get(f"/api/chat/conversations/{a}").status_code == 404
    assert client.post(f"/api/chat/conversations/{a}/messages", json={"content": "x"}).status_code == 404


def test_empty_message_rejected(client):
    cid = new_chat(client)
    assert client.post(f"/api/chat/conversations/{cid}/messages", json={"content": ""}).status_code == 422


def test_chats_survive_reseed(client, fake_model):
    cid = new_chat(client)
    send(client, cid, "keep me")

    small = {"seed": 2, "customers": 3, "products": 3, "orders": 3, "tickets": 1}
    r = client.post("/api/admin/seed", json=small)
    assert r.status_code == 200
    assert len(client.get(f"/api/chat/conversations/{cid}").json()["messages"]) == 2


def test_reply_uses_plain_spaces_and_hyphens(client, monkeypatch):
    nnbsp, nb_hyphen = chr(0x202F), chr(0x2011)  # narrow no-break space, non-breaking hyphen
    raw = f"Numbers 1{nnbsp}to{nnbsp}20 for ORD{nb_hyphen}00000002"
    monkeypatch.setattr(ai, "stream", lambda messages, **_: iter([raw]))
    cid = new_chat(client)
    events = send(client, cid, "hi")
    assert events[0] == ("delta", {"text": "Numbers 1 to 20 for ORD-00000002"})
    assert events[-1][1]["assistant_message"]["content"] == "Numbers 1 to 20 for ORD-00000002"
