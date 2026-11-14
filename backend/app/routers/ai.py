"""AI endpoints. For now: a status check and a plain prompt round-trip to verify the setup.

The data-aware chatbot will live here later.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.services import ai

router = APIRouter(prefix="/api/ai", tags=["ai"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


class AIStatus(BaseModel):
    enabled: bool
    provider: str = "groq"
    model: str


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    system: str | None = Field(default=None, max_length=4000)


class PromptResponse(BaseModel):
    reply: str
    model: str
    finish_reason: str | None
    usage: dict[str, int]


@router.get("/status", response_model=AIStatus)
def ai_status(settings: SettingsDep):
    """Whether AI is configured (GROQ_API_KEY set) and which model is used. Never calls the provider."""
    return AIStatus(enabled=settings.ai_enabled, model=settings.ai_model)


@router.post("/prompt", response_model=PromptResponse)
def ai_prompt(body: PromptRequest, settings: SettingsDep):
    """Send a single prompt to the model. Useful to check the API key and model work end to end."""
    messages: list[ai.Message] = []
    if body.system:
        messages.append({"role": "system", "content": body.system})
    messages.append({"role": "user", "content": body.prompt})

    result = ai.complete(messages, settings=settings)
    return PromptResponse(
        reply=result.content or "",
        model=result.model,
        finish_reason=result.finish_reason,
        usage=result.usage,
    )
