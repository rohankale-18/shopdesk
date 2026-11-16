"""Traces: what happened behind each assistant reply (model calls, tool runs, timings, tokens)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Json, computed_field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.db import get_db
from app.models import ChatTrace

router = APIRouter(prefix="/api/traces", tags=["traces"])
DB = Annotated[Session, Depends(get_db)]


class ToolRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: int
    name: str
    arguments: str  # as the model sent it (may not even be valid JSON)
    result: Json[Any]
    is_error: bool
    duration_ms: int


class ModelCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: int
    request: Json[Any]  # {"messages": [...], "tools": [...], "tool_choice": "..."}
    response_text: str
    reasoning: str
    tool_calls: Json[list[dict[str, Any]]]
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int
    first_token_ms: int | None


class TraceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    message_id: int | None
    question: str
    model: str
    status: str
    error: str | None
    started_at: datetime
    duration_ms: int
    first_token_ms: int | None
    steps: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    tool_runs: list[ToolRunOut]

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class TraceDetail(TraceSummary):
    model_calls: list[ModelCallOut]


@router.get("", response_model=list[TraceSummary])
def list_traces(db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    """The most recent replies, newest first."""
    return db.scalars(select(ChatTrace).order_by(ChatTrace.id.desc()).limit(limit)).all()


@router.get("/{trace_id}", response_model=TraceDetail)
def get_trace(trace_id: int, db: DB):
    """One reply in full: every model call (with the exact prompt) and every tool run."""
    trace = db.scalar(
        select(ChatTrace).where(ChatTrace.id == trace_id).options(selectinload(ChatTrace.model_calls))
    )
    if trace is None:
        raise NotFoundError(f"Trace {trace_id} not found.")
    return trace
