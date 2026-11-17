"""Tracing: record everything behind one assistant reply, then save it.

While the agent loop runs, a `TraceRecorder` collects each model call and tool run in
memory: what was sent, what came back, how long it took, how many tokens it cost.
`save()` writes it to the database at the end, whether the reply finished, failed or
was stopped. The Traces page in the app reads it back.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatConversation, ChatMessage, ChatModelCall, ChatToolRun, ChatTrace, utcnow
from app.services import ai


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


@dataclass
class ModelCallRecord:
    step: int
    request: str  # JSON snapshot, taken before the call: the loop keeps adding to the messages
    started: float = field(default_factory=time.perf_counter)
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    end: ai.StreamEnd = field(default_factory=ai.StreamEnd)
    first_token_ms: int | None = None
    duration_ms: int = 0


@dataclass
class ToolRunRecord:
    step: int
    name: str
    arguments: str
    result: dict[str, Any]
    duration_ms: int


@dataclass
class TraceRecorder:
    question: str
    model: str
    started_at: datetime = field(default_factory=utcnow)
    started: float = field(default_factory=time.perf_counter)
    first_token_ms: int | None = None
    model_calls: list[ModelCallRecord] = field(default_factory=list)
    tool_runs: list[ToolRunRecord] = field(default_factory=list)
    status: str = "stopped"  # until the reply finishes ("ok") or fails ("error")
    error: str | None = None

    # ----- called by the agent loop -----

    def model_call(
        self, step: int, messages: list[ai.Message], tools: list[dict], tool_choice: str
    ) -> ModelCallRecord:
        request = {
            "messages": messages,
            "tools": [t["function"]["name"] for t in tools],
            "tool_choice": tool_choice,
        }
        call = ModelCallRecord(step=step, request=json.dumps(request))
        self.model_calls.append(call)
        return call

    def on_piece(self, call: ModelCallRecord, piece: str | ai.ToolCall | ai.StreamEnd) -> None:
        if isinstance(piece, ai.StreamEnd):
            call.end = piece
            call.duration_ms = _ms_since(call.started)
        elif isinstance(piece, ai.ToolCall):
            call.tool_calls.append({"name": piece.name, "arguments": piece.arguments})
        else:
            if call.first_token_ms is None:
                call.first_token_ms = _ms_since(call.started)
            if self.first_token_ms is None:
                self.first_token_ms = _ms_since(self.started)
            call.text += piece

    def tool_run(self, step: int, name: str, arguments: str, result: dict[str, Any], started: float) -> None:
        self.tool_runs.append(ToolRunRecord(step, name, arguments, result, _ms_since(started)))

    # ----- called by the router -----

    def finish(self) -> None:
        self.status = "ok"

    def fail(self, error: str) -> None:
        self.status, self.error = "error", error


def save(
    session: Session, trace: TraceRecorder, conversation_id: int, message: ChatMessage | None = None
) -> ChatTrace | None:
    """Add the trace to the session (the caller commits). Skipped if the conversation is gone."""
    if session.get(ChatConversation, conversation_id) is None:
        return None
    if message is not None:
        session.flush()  # gives the message its id
    calls = trace.model_calls
    row = ChatTrace(
        conversation_id=conversation_id,
        message_id=message.id if message else None,
        question=trace.question,
        model=trace.model,
        status=trace.status,
        error=trace.error,
        started_at=trace.started_at,
        duration_ms=_ms_since(trace.started),
        first_token_ms=trace.first_token_ms,
        steps=len(calls),
        prompt_tokens=sum(c.end.usage.get("prompt_tokens", 0) for c in calls),
        completion_tokens=sum(c.end.usage.get("completion_tokens", 0) for c in calls),
        reasoning_tokens=sum(c.end.usage.get("reasoning_tokens", 0) for c in calls),
        model_calls=[
            ChatModelCall(
                step=c.step,
                request=c.request,
                response_text=c.text,
                reasoning=c.end.reasoning,
                tool_calls=json.dumps(c.tool_calls),
                finish_reason=c.end.finish_reason,
                prompt_tokens=c.end.usage.get("prompt_tokens", 0),
                completion_tokens=c.end.usage.get("completion_tokens", 0),
                reasoning_tokens=c.end.usage.get("reasoning_tokens", 0),
                queue_ms=c.end.usage.get("queue_ms"),
                input_ms=c.end.usage.get("input_ms"),
                output_ms=c.end.usage.get("output_ms"),
                duration_ms=c.duration_ms or _ms_since(c.started),  # unfinished (stopped / failed) calls
                first_token_ms=c.first_token_ms,
            )
            for c in calls
        ],
        tool_runs=[
            ChatToolRun(
                step=r.step,
                name=r.name,
                arguments=r.arguments,
                result=json.dumps(r.result),
                is_error="error" in r.result,
                duration_ms=r.duration_ms,
            )
            for r in trace.tool_runs
        ],
    )
    session.add(row)
    return row
