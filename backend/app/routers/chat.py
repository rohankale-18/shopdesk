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

from app.core.errors import AppError, NotFoundError
from app.db import SessionLocal, get_db
from app.models import ChatConversation, ChatMessage, ChatRole, ChatToolCall, utcnow
from app.services import tools
from app.services.chat import EMPTY_REPLY, ToolRun, stream_reply

logger = logging.getLogger("shopdesk.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])
DB = Annotated[Session, Depends(get_db)]


# ---------- schemas ----------


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str

    @computed_field
    @property
    def label(self) -> str:
        return tools.label(self.name)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: ChatRole
    content: str
    tool_calls: list[ToolCallOut]
    created_at: datetime


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationOut(ConversationSummary):
    messages: list[ChatMessageOut]


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
def create_conversation(db: DB):
    """Start an empty conversation."""
    convo = ChatConversation()
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
    normal JSON error instead. If the client disconnects early, nothing is saved.
    """
    convo = _get(db, conversation_id)
    text = body.content.strip()
    is_first = not convo.messages

    # Starts the model call now, so setup errors still become normal error responses.
    chunks = stream_reply(convo.messages, text)
    db.close()  # the stream below can take a while; it saves with its own session

    def events() -> Iterator[str]:
        parts: list[str] = []
        runs: list[ToolRun] = []
        try:
            for chunk in chunks:
                if isinstance(chunk, ToolRun):
                    runs.append(chunk)
                    yield _sse("tool", {"name": chunk.name, "label": tools.label(chunk.name)})
                else:
                    parts.append(chunk)
                    yield _sse("delta", {"text": chunk})
        except AppError as e:
            yield _sse("error", {"code": e.code, "message": e.message})
            return
        except Exception:
            logger.exception("Chat stream failed for conversation %s", conversation_id)
            message = "Something went wrong. Please try again."
            yield _sse("error", {"code": "internal_error", "message": message})
            return

        # Save the finished turn. Nothing is written while the model is still talking.
        with SessionLocal() as session:
            convo = session.get(ChatConversation, conversation_id)
            if convo is None:  # deleted while we were streaming
                yield _sse("error", {"code": "not_found", "message": "This conversation was deleted."})
                return
            if is_first:
                convo.title = text[:80]  # the first message names the conversation
            user_msg = ChatMessage(role=ChatRole.user, content=text)
            reply = "".join(parts).strip() or EMPTY_REPLY
            assistant_msg = ChatMessage(role=ChatRole.assistant, content=reply)
            assistant_msg.tool_calls = [
                ChatToolCall(name=r.name, arguments=r.arguments, result=json.dumps(r.result)) for r in runs
            ]
            convo.messages.extend([user_msg, assistant_msg])
            convo.updated_at = utcnow()  # adding messages doesn't touch the conversation row itself
            session.commit()
            result = SendMessageResult(user_message=user_msg, assistant_message=assistant_msg)
        yield _sse("done", result.model_dump(mode="json"))

    # X-Accel-Buffering: no stops nginx (Docker setup) from holding the stream back.
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
