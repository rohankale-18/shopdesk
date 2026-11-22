"""Traces: every reply records its model calls, tool runs, timings and tokens."""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.core.errors import UpstreamError
from app.db import init_db
from app.services import ai, tools


def end(prompt: int, completion: int, reasoning: int, why: str, finish: str) -> ai.StreamEnd:
    usage = {"prompt_tokens": prompt, "completion_tokens": completion, "reasoning_tokens": reasoning}
    usage |= {"queue_ms": 30, "input_ms": 50, "output_ms": 200}
    return ai.StreamEnd(finish_reason=finish, reasoning=why, usage=usage)


@pytest.fixture()
def script(monkeypatch):
    """A fake model that plays one list of pieces per call (like the real stream, ending in StreamEnd)."""
    replies: list[list] = []

    def stream(messages, **_):
        return iter(replies.pop(0))

    monkeypatch.setattr(ai, "stream", stream)
    return replies


def ask(client, content: str) -> tuple[int, list[str]]:
    cid = client.post("/api/chat/conversations").json()["id"]
    r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": content})
    names = [line.removeprefix("event: ") for line in r.text.splitlines() if line.startswith("event: ")]
    return cid, names


def latest_trace(client) -> dict:
    summary = client.get("/api/traces").json()[0]
    return client.get(f"/api/traces/{summary['id']}").json()


def test_a_reply_with_a_tool_is_traced_in_full(client, script):
    overview = ai.ToolCall(id="c1", name="get_store_overview", arguments="{}")
    script += [
        [overview, end(1400, 40, 30, "They want ticket counts; the overview has them.", "tool_calls")],
        ["There are ", "N open tickets.", end(1600, 20, 5, "Answer from the result.", "stop")],
    ]
    cid, events = ask(client, "How many open tickets?")
    assert events[-1] == "done"

    trace = latest_trace(client)
    assert (trace["status"], trace["error"], trace["steps"], trace["conversation_id"]) == ("ok", None, 2, cid)
    assert trace["question"] == "How many open tickets?"
    # Tokens are summed over both model calls.
    assert (trace["prompt_tokens"], trace["completion_tokens"], trace["reasoning_tokens"]) == (3000, 60, 35)
    assert trace["total_tokens"] == 3060
    assert trace["first_token_ms"] is not None and trace["duration_ms"] >= trace["first_token_ms"]

    first, second = trace["model_calls"]
    assert first["request"]["tool_choice"] == "auto"
    assert first["request"]["tools"] == list(tools.TOOLS)
    assert [m["role"] for m in first["request"]["messages"]] == ["system", "user"]
    assert first["tool_calls"] == [{"name": "get_store_overview", "arguments": "{}"}]
    assert (first["finish_reason"], first["reasoning"]) == (
        "tool_calls",
        "They want ticket counts; the overview has them.",
    )
    # The second call was sent the tool request and its result: the prompt grows each pass.
    assert [m["role"] for m in second["request"]["messages"]] == ["system", "user", "assistant", "tool"]
    assert (second["response_text"], second["finish_reason"]) == ("There are N open tickets.", "stop")

    # Groq's own timings are kept per call.
    assert (first["queue_ms"], first["input_ms"], first["output_ms"]) == (30, 50, 200)

    (run,) = trace["tool_runs"]
    assert (run["step"], run["name"], run["is_error"]) == (1, "get_store_overview", False)
    assert "tickets_now" in run["result"]

    # The saved reply links to its trace, and its chips come from the trace.
    reply = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
    assert reply["trace_id"] == trace["id"] and trace["message_id"] == reply["id"]
    assert [t["label"] for t in reply["tool_calls"]] == ["Looked up store overview"]


def test_a_failed_reply_is_traced_without_a_message(client, monkeypatch):
    def broken(messages, **_):
        yield "partial"
        raise UpstreamError("The AI provider timed out. Try again.")

    monkeypatch.setattr(ai, "stream", broken)
    cid, events = ask(client, "hello")
    assert events[-1] == "error"

    trace = latest_trace(client)
    assert (trace["status"], trace["error"], trace["message_id"]) == (
        "error",
        "The AI provider timed out. Try again.",
        None,
    )
    assert trace["model_calls"][0]["response_text"] == "partial"
    assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []


def test_a_tool_error_is_flagged(client, script):
    bad = ai.ToolCall(
        id="c1", name="get_sales", arguments='{"start_date": "2026-02-30", "end_date": "2026-03-01"}'
    )
    script += [[bad, end(1, 1, 0, "", "tool_calls")], ["That date doesn't exist.", end(1, 1, 0, "", "stop")]]
    ask(client, "Sales on 30 February?")
    (run,) = latest_trace(client)["tool_runs"]
    assert run["is_error"] is True
    assert "real date" in run["result"]["error"]


def test_list_is_newest_first_and_deleting_a_conversation_deletes_its_traces(client, script):
    script += [["one", end(1, 1, 0, "", "stop")], ["two", end(1, 1, 0, "", "stop")]]
    first, _ = ask(client, "first")
    ask(client, "second")
    assert [t["question"] for t in client.get("/api/traces").json()[:2]] == ["second", "first"]

    first_trace = client.get("/api/traces").json()[1]["id"]
    client.delete(f"/api/chat/conversations/{first}")
    assert client.get(f"/api/traces/{first_trace}").status_code == 404
    assert client.get("/api/traces").json()[0]["question"] == "second"
    assert client.get("/api/traces/999999").status_code == 404


def test_init_db_adds_new_columns_to_an_old_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # chat_model_calls as it was before Groq's timings were saved
        conn.execute(text("CREATE TABLE chat_model_calls (id INTEGER PRIMARY KEY, step INTEGER)"))
    init_db(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("chat_model_calls")}
    assert {"queue_ms", "input_ms", "output_ms"} <= columns
    engine.dispose()


def test_a_trace_flags_numbers_no_tool_returned(client, script):
    overview = ai.ToolCall(id="c1", name="get_store_overview", arguments="{}")
    open_now = client.get("/api/stats/overview").json()["open_tickets"]
    script += [
        [overview, end(1400, 40, 30, "Overview has tickets.", "tool_calls")],
        [f"{open_now} tickets are open, 9876 were resolved last month.", end(1600, 20, 5, "", "stop")],
    ]
    ask(client, "How many tickets are open, and how many were resolved last month?")
    assert latest_trace(client)["unsupported_numbers"] == ["9876"]  # the real count passes


def test_numbers_from_page_context_and_tool_descriptions_are_grounded(client, script):
    """A ticket chat's context is data the model was given, and so is a rule in a tool description."""
    shipped = tools.run("get_ticket", '{"ticket_id": 2}')["order"]["shipped"]["days_ago"]
    reply = (
        f"It shipped {shipped} days ago, so it's late (after {tools.LATE_AFTER_DAYS} days). 4321 is made up."
    )
    script += [[reply, end(1400, 20, 5, "", "stop")]]
    cid = client.post("/api/chat/conversations", json={"ticket_id": 2}).json()["id"]
    client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "What's this about?"}).read()
    assert latest_trace(client)["unsupported_numbers"] == ["4321"]
