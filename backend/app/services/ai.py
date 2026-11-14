"""Thin wrapper around the Groq chat-completions API.

Everything AI-related goes through here so the rest of the app never touches
the SDK directly. The chatbot will build on `complete()`: it accepts the full
OpenAI-style message list and optional `tools`, so tool calling over the
ShopDesk data can be added without changing this layer.
"""

import logging
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
    """Run one chat completion and map provider errors onto our API errors."""
    settings = settings or get_settings()
    client = get_client(settings)

    kwargs: dict[str, Any] = {
        "model": model or settings.ai_model,
        "messages": messages,
        "temperature": settings.ai_temperature if temperature is None else temperature,
        "max_tokens": max_tokens or settings.ai_max_tokens,
        **extra,
    }
    if tools:
        kwargs["tools"] = tools

    try:
        resp = client.chat.completions.create(**kwargs)
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
