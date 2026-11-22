"""Chat endpoints: conversations and their messages, stored in the database."""

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.db import SessionLocal, get_db
from app.models import ChatConversation, ChatMessage, ChatRole, Ticket, utcnow
from app.services import tools, tracing
from app.services.chat import EMPTY_REPLY, ToolRun, stream_reply
from app.services.tracing import TraceRecorder

logger = logging.getLogger("shopdesk.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])
DB = Annotated[Session, Depends(get_db)]


# ---------- schemas ----------


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    arguments: str = Field(exclude=True)  # only used to build the label

    @computed_field
    @property
    def label(self) -> str:
        return tools.label(self.name, self.arguments)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: ChatRole
    content: str
    tool_calls: list[ToolCallOut]
    trace_id: int | None  # the reply's trace (assistant messages only)
    created_at: datetime


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    ticket_id: int | None  # opened from this ticket: its data goes with every message
    created_at: datetime
    updated_at: datetime


class ConversationOut(ConversationSummary):
    messages: list[ChatMessageOut]


class NewConversation(BaseModel):
    ticket_id: int | None = None


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class SendMessageResult(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut


# ---------- endpoints ----------


def _get(db: Session, conversation_id: int) -> ChatConversation:
    convo = db.get(ChatConversation, conversation_id)
    if not convo:
        raise NotFoundError(f"Conversation {conversation_id} not found.")
    return convo


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(db: DB):
    """The 50 most recently active conversations."""
    return db.scalars(select(ChatConversation).order_by(ChatConversation.updated_at.desc()).limit(50)).all()


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(db: DB, body: NewConversation | None = None):
    """Start an empty conversation, optionally about a ticket (the page the user was on)."""
    ticket_id = body.ticket_id if body else None
    if ticket_id is not None and not db.get(Ticket, ticket_id):
        raise NotFoundError(f"Ticket {ticket_id} not found.")
    convo = ChatConversation(ticket_id=ticket_id)
    db.add(convo)
    db.commit()
    return convo


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, db: DB):
    """A conversation with all its messages, oldest first."""
    return _get(db, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, db: DB):
    db.delete(_get(db, conversation_id))
    db.commit()


def _sse(event: str, data: dict) -> str:
    """One Server-Sent Event: an `event:` line, a `data:` line (JSON), then a blank line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "A stream of events (see below)."}},
)
def send_message(conversation_id: int, body: SendMessage, db: DB):
    """Send a message; the assistant's reply streams back as Server-Sent Events.

    - `delta`: `{"text": "..."}`, the next piece of the reply.
    - `tool`: `{"name": "...", "label": "..."}`, the assistant ran a tool (it may run several).
    - `done`: `{"user_message": ..., "assistant_message": ...}`, both saved. Always last on success.
    - `error`: `{"code": "...", "message": "..."}` if it fails mid-stream. Nothing is saved.

    Problems found before streaming starts (unknown conversation, no API key...) return a
    normal JSON error instead. If the client disconnects early, no messages are saved.
    A trace of the reply is saved in every case (see /api/traces).
    """
    convo = _get(db, conversation_id)
    text = body.content.strip()
    is_first = not convo.messages
    ticket_id = convo.ticket_id

    # Starts the model call now, so setup errors still become normal error responses.
    trace = TraceRecorder(question=text, model=get_settings().ai_model)
    chunks = stream_reply(convo.messages, text, trace, convo.ticket_id)
    db.close()  # the stream below can take a while; it saves with its own session

    def save_trace_only() -> None:
        with SessionLocal() as session:
            if tracing.save(session, trace, conversation_id):
                session.commit()

    def events() -> Iterator[str]:
        parts: list[str] = []
        try:
            for chunk in chunks:
                if isinstance(chunk, ToolRun):
                    label = tools.label(chunk.name, chunk.arguments)
                    yield _sse("tool", {"name": chunk.name, "label": label})
                else:
                    parts.append(chunk)
                    yield _sse("delta", {"text": chunk})
        except AppError as e:
            trace.fail(e.message)
            save_trace_only()
            yield _sse("error", {"code": e.code, "message": e.message})
            return
        except Exception as e:
            logger.exception("Chat stream failed for conversation %s", conversation_id)
            trace.fail(f"{type(e).__name__}: {e}")
            save_trace_only()
            message = "Something went wrong. Please try again."
            yield _sse("error", {"code": "internal_error", "message": message})
            return
        except GeneratorExit:  # the client went away (Stop button): keep the trace, as "stopped"
            save_trace_only()
            raise

        # Save the finished turn. Nothing is written while the model is still talking.
        with SessionLocal() as session:
            convo = session.get(ChatConversation, conversation_id)
            if convo is None:  # deleted while we were streaming
                yield _sse("error", {"code": "not_found", "message": "This conversation was deleted."})
                return
            if is_first:
                title = f"#{ticket_id}: {text}" if ticket_id else text
                convo.title = title[:80]  # the first message names the conversation
            user_msg = ChatMessage(role=ChatRole.user, content=text)
            reply = "".join(parts).strip() or EMPTY_REPLY
            assistant_msg = ChatMessage(role=ChatRole.assistant, content=reply)
            convo.messages.extend([user_msg, assistant_msg])
            convo.updated_at = utcnow()  # adding messages doesn't touch the conversation row itself
            trace.finish()
            tracing.save(session, trace, conversation_id, assistant_msg)
            session.commit()
            result = SendMessageResult(user_message=user_msg, assistant_message=assistant_msg)
        yield _sse("done", result.model_dump(mode="json"))

    # X-Accel-Buffering: no stops nginx (Docker setup) from holding the stream back.
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
