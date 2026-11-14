from types import SimpleNamespace

from app.core.config import get_settings
from app.services import ai


def test_ai_status_disabled_without_key(client):
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["provider"] == "groq"
    assert body["model"]


def test_ai_prompt_returns_503_without_key(client):
    r = client.post("/api/ai/prompt", json={"prompt": "hi"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "service_unavailable"


def test_ai_prompt_uses_groq_client(client, monkeypatch):
    calls = {}

    def fake_create(**kwargs):
        calls.update(kwargs)
        msg = SimpleNamespace(content="pong", tool_calls=None)
        usage = SimpleNamespace(
            model_dump=lambda include=None: {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")], model=kwargs["model"], usage=usage
        )

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    monkeypatch.setattr(ai, "get_client", lambda settings=None: fake)

    r = client.post("/api/ai/prompt", json={"prompt": "ping", "system": "Be brief."})
    assert r.status_code == 200
    assert r.json()["reply"] == "pong"
    assert r.json()["usage"]["total_tokens"] == 4
    assert calls["model"] == get_settings().ai_model
    assert calls["messages"][0] == {"role": "system", "content": "Be brief."}
