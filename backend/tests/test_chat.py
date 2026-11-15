import json
from datetime import date

import pytest

from app.core.errors import UpstreamError
from app.services import ai
from app.services.chat import SYSTEM_PROMPT, calendar, system_prompt


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
        {"role": "system", "content": system_prompt()},
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


# ---------- the agent loop (tools) ----------


@pytest.fixture()
def scripted_model(monkeypatch):
    """A fake model that plays back a script: one list of pieces (text or ToolCall) per call.

    Returns the recorded calls as (messages, kwargs) pairs.
    """
    calls: list[tuple[list[dict], dict]] = []
    script: list[list] = []

    def stream(messages, **kwargs):
        calls.append((list(messages), kwargs))  # copy: the loop keeps appending to the list
        return iter(script[min(len(calls), len(script)) - 1])

    monkeypatch.setattr(ai, "stream", stream)
    return script, calls


def ask_overview(call_id="call_1"):
    return ai.ToolCall(id=call_id, name="get_store_overview", arguments="{}")


def test_agent_runs_the_tool_and_answers_with_its_result(client, scripted_model):
    script, calls = scripted_model
    script += [[ask_overview()], ["There are ", "N open tickets."]]
    cid = new_chat(client)
    events = send(client, cid, "How many open tickets are there?")

    assert [name for name, _ in events] == ["tool", "delta", "delta", "done"]
    assert events[0][1] == {"name": "get_store_overview", "label": "Looked up store overview"}

    # First call: the model gets the tool list. Second call: it gets its request and our result.
    first_messages, first_kwargs = calls[0]
    assert "get_store_overview" in [t["function"]["name"] for t in first_kwargs["tools"]]
    second_messages = calls[1][0]
    request, result = second_messages[-2:]
    assert request["role"] == "assistant"
    assert request["tool_calls"][0]["function"]["name"] == "get_store_overview"
    assert result["role"] == "tool" and result["tool_call_id"] == "call_1"
    dashboard = client.get("/api/stats/overview").json()
    assert json.loads(result["content"])["tickets_now"]["open_tickets"] == dashboard["open_tickets"]

    # The tool call is saved with the reply, so the chip survives a reload.
    reply = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
    assert reply["content"] == "There are N open tickets."
    assert reply["tool_calls"] == [{"name": "get_store_overview", "label": "Looked up store overview"}]


def test_agent_answers_without_tools_when_none_needed(client, scripted_model):
    script, calls = scripted_model
    script += [["Hi! How can I help?"]]
    cid = new_chat(client)
    events = send(client, cid, "Hi!")

    assert [name for name, _ in events] == ["delta", "done"]
    assert len(calls) == 1
    assert events[-1][1]["assistant_message"]["tool_calls"] == []


def test_unknown_tool_goes_back_to_the_model_as_an_error(client, scripted_model):
    script, calls = scripted_model
    script += [[ai.ToolCall(id="c1", name="delete_everything", arguments="{}")], ["I can't do that."]]
    cid = new_chat(client)
    events = send(client, cid, "Delete everything")

    assert events[-1][0] == "done"
    tool_result = json.loads(calls[1][0][-1]["content"])
    assert "error" in tool_result


def test_agent_stops_after_max_steps(client, scripted_model):
    from app.services.chat import EMPTY_REPLY, MAX_STEPS

    script, calls = scripted_model
    script += [[ask_overview()]]  # a model that never stops asking
    cid = new_chat(client)
    events = send(client, cid, "Loop forever")

    assert len(calls) == MAX_STEPS
    assert calls[-1][1]["tool_choice"] == "none"  # the last call must answer
    assert [name for name, _ in events].count("tool") == MAX_STEPS - 1
    assert events[-1][1]["assistant_message"]["content"] == EMPTY_REPLY


def test_system_prompt_ends_with_the_calendar():
    prompt = system_prompt(date(2026, 11, 15))  # a Sunday
    assert prompt.startswith(SYSTEM_PROMPT)
    assert prompt.endswith(
        "Today is Sunday, 15 November 2026 (UTC). Use these dates as given:"
        "\n- This week: 2026-11-09 to 2026-11-15"
        "\n- Last week: 2026-11-02 to 2026-11-08"
        "\n- Week before last: 2026-10-26 to 2026-11-01"
        "\n- This month: 2026-11-01 to 2026-11-15"
        "\n- Last month: 2026-10-01 to 2026-10-31"
    )


def test_calendar_on_a_monday_in_january():
    text = calendar(date(2027, 1, 4))  # Monday: this week is just today; last month is last year
    assert "This week: 2027-01-04 to 2027-01-04" in text
    assert "Last week: 2026-12-28 to 2027-01-03" in text
    assert "Last month: 2026-12-01 to 2026-12-31" in text


def test_two_tools_in_one_turn(client, scripted_model):
    script, calls = scripted_model
    sales = ai.ToolCall(
        id="c1", name="get_sales", arguments='{"start_date": "2026-05-01", "end_date": "2026-05-31"}'
    )
    script += [[sales, ask_overview("c2")], ["Both answers."]]
    cid = new_chat(client)
    events = send(client, cid, "Revenue in May, and how many open tickets?")

    tool_events = [data["label"] for name, data in events if name == "tool"]
    assert tool_events == ["Looked up sales, 2026-05-01 to 2026-05-31", "Looked up store overview"]
    # The model's second call gets one result per request, matched by id.
    results = [m for m in calls[1][0] if m["role"] == "tool"]
    assert [r["tool_call_id"] for r in results] == ["c1", "c2"]
    assert "period" in json.loads(results[0]["content"])
    saved = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["tool_calls"]
    assert [t["label"] for t in saved] == tool_events
