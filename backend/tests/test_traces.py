"""Traces: every reply records its model calls, tool runs, timings and tokens."""

import pytest

from app.core.errors import UpstreamError
from app.services import ai


def end(prompt: int, completion: int, reasoning: int, why: str, finish: str) -> ai.StreamEnd:
    usage = {"prompt_tokens": prompt, "completion_tokens": completion, "reasoning_tokens": reasoning}
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
        [overview, end(900, 40, 30, "They want ticket counts; the overview has them.", "tool_calls")],
        ["There are ", "N open tickets.", end(1500, 20, 5, "Answer from the result.", "stop")],
    ]
    cid, events = ask(client, "How many open tickets?")
    assert events[-1] == "done"

    trace = latest_trace(client)
    assert (trace["status"], trace["error"], trace["steps"], trace["conversation_id"]) == ("ok", None, 2, cid)
    assert trace["question"] == "How many open tickets?"
    # Tokens are summed over both model calls.
    assert (trace["prompt_tokens"], trace["completion_tokens"], trace["reasoning_tokens"]) == (2400, 60, 35)
    assert trace["total_tokens"] == 2460
    assert trace["first_token_ms"] is not None and trace["duration_ms"] >= trace["first_token_ms"]

    first, second = trace["model_calls"]
    assert first["request"]["tool_choice"] == "auto"
    assert first["request"]["tools"] == ["get_store_overview", "get_sales"]
    assert [m["role"] for m in first["request"]["messages"]] == ["system", "user"]
    assert first["tool_calls"] == [{"name": "get_store_overview", "arguments": "{}"}]
    assert (first["finish_reason"], first["reasoning"]) == (
        "tool_calls",
        "They want ticket counts; the overview has them.",
    )
    # The second call was sent the tool request and its result: the prompt grows each pass.
    assert [m["role"] for m in second["request"]["messages"]] == ["system", "user", "assistant", "tool"]
    assert (second["response_text"], second["finish_reason"]) == ("There are N open tickets.", "stop")

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
