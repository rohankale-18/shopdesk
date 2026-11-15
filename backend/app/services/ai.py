"""Thin wrapper around the Groq chat-completions API.

Everything AI-related goes through here so the rest of the app never touches
the SDK directly.

- `complete()` returns the whole reply at once. It accepts `tools`, so tool
  calling over the ShopDesk data can be built on it.
- `stream()` yields the reply text piece by piece, for live chat UIs. Given
  `tools`, it also yields the tool calls the model asks for (see `ToolCall`).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import groq
from groq import Groq

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError, UpstreamError

logger = logging.getLogger("shopdesk.ai")

Message = dict[str, Any]  # {"role": "system" | "user" | "assistant" | "tool", "content": ...}


@dataclass
class Completion:
    content: str | None
    model: str
    finish_reason: str | None
    tool_calls: list[Any] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    raw_message: Any = None  # the SDK message, handy to append back into the history


@dataclass
class ToolCall:
    """The model asking us to run one of our tools. `arguments` is a JSON string, as sent."""

    id: str
    name: str
    arguments: str

    def as_message_part(self) -> dict[str, Any]:
        """How this call is written back into the history (inside the assistant message)."""
        function = {"name": self.name, "arguments": self.arguments}
        return {"id": self.id, "type": "function", "function": function}


@lru_cache
def _client(api_key: str, timeout: float, max_retries: int) -> Groq:
    return Groq(api_key=api_key, timeout=timeout, max_retries=max_retries)


def get_client(settings: Settings | None = None) -> Groq:
    settings = settings or get_settings()
    if not settings.groq_api_key:
        raise ServiceUnavailableError(
            "AI is not configured. Set GROQ_API_KEY in backend/.env and restart the server."
        )
    return _client(settings.groq_api_key, settings.ai_timeout_seconds, settings.ai_max_retries)


@contextmanager
def _provider_errors() -> Iterator[None]:
    """Turn Groq SDK exceptions into our API errors (503 / 502 with a clear message)."""
    try:
        yield
    except groq.AuthenticationError as e:
        raise ServiceUnavailableError("The Groq API key was rejected. Check GROQ_API_KEY.") from e
    except groq.RateLimitError as e:
        raise UpstreamError("Groq rate limit reached. Wait a moment and try again.") from e
    except groq.APITimeoutError as e:
        raise UpstreamError("The AI provider timed out. Try again.") from e
    except groq.APIConnectionError as e:
        raise UpstreamError("Could not reach the AI provider.") from e
    except groq.APIStatusError as e:
        logger.warning("Groq error %s: %s", e.status_code, e.message)
        raise UpstreamError(
            f"The AI provider returned an error ({e.status_code}).",
            details={"provider_message": e.message},
        ) from e


def _request(
    messages: list[Message],
    settings: Settings,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": model or settings.ai_model,
        "messages": messages,
        "temperature": settings.ai_temperature if temperature is None else temperature,
        "max_tokens": max_tokens or settings.ai_max_tokens,
        **extra,
    }


def complete(
    messages: list[Message],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    settings: Settings | None = None,
    **extra: Any,
) -> Completion:
    """Run one chat completion and return the whole reply."""
    settings = settings or get_settings()
    client = get_client(settings)
    kwargs = _request(messages, settings, model, temperature, max_tokens, extra)
    if tools:
        kwargs["tools"] = tools

    with _provider_errors():
        resp = client.chat.completions.create(**kwargs)

    choice = resp.choices[0]
    usage_fields = {"prompt_tokens", "completion_tokens", "total_tokens"}
    usage = resp.usage.model_dump(include=usage_fields) if resp.usage else {}
    return Completion(
        content=choice.message.content,
        model=resp.model,
        finish_reason=choice.finish_reason,
        tool_calls=list(choice.message.tool_calls or []),
        usage=usage,
        raw_message=choice.message,
    )


def stream(
    messages: list[Message],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    settings: Settings | None = None,
    **extra: Any,
) -> Iterator[str | ToolCall]:
    """Start a streamed completion and return an iterator over the reply.

    The iterator yields text pieces (`str`) as they arrive. If the model asks for tools,
    it yields one `ToolCall` per tool at the end, once each call is complete.

    The request is sent *before* this returns, so setup problems (no API key, key
    rejected, rate limit) raise right away, while the caller can still answer with a
    normal error response. Problems after that raise from the iterator.
    """
    settings = settings or get_settings()
    client = get_client(settings)
    kwargs = _request(messages, settings, model, temperature, max_tokens, extra)
    if tools:
        kwargs["tools"] = tools

    with _provider_errors():
        chunks = client.chat.completions.create(**kwargs, stream=True)

    def pieces() -> Iterator[str | ToolCall]:
        # A tool call can arrive split over several chunks: the id and name first, then the
        # JSON arguments bit by bit. `index` says which call a piece belongs to.
        calls: dict[int, ToolCall] = {}
        with _provider_errors():
            for chunk in chunks:
                if not chunk.choices:  # e.g. the final usage-only chunk
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
                for part in delta.tool_calls or []:
                    call = calls.setdefault(part.index, ToolCall(id="", name="", arguments=""))
                    call.id = part.id or call.id
                    if part.function:
                        call.name += part.function.name or ""
                        call.arguments += part.function.arguments or ""
        yield from calls.values()

    return pieces()
