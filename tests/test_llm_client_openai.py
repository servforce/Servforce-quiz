import importlib
import json

import config as config_module
from services import llm_client as llm_client_module


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _reload_llm_modules():
    importlib.reload(config_module)
    importlib.reload(llm_client_module)
    return llm_client_module


def test_llm_client_uses_openai_env_vars(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "demo-model")
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_BASE_URL", raising=False)
    monkeypatch.delenv("DOUBAO_MODEL", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    llm = _reload_llm_modules()
    captured = {}

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"output_text": "ok"})

    monkeypatch.setattr(llm, "urlopen", fake_urlopen)

    text = llm.call_llm_text("hello")

    assert text == "ok"
    assert captured["url"] == "https://example.test/v1/responses"
    assert captured["auth"] == "Bearer test-key"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"]["model"] == "demo-model"
    assert captured["body"]["input"][0]["content"][0]["type"] == "input_text"


def test_llm_client_missing_openai_api_key_points_to_new_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "demo-model")
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    llm = _reload_llm_modules()

    try:
        llm._responses_api_request(  # noqa: SLF001
            input_messages=[{"role": "user", "content": [{"type": "input_text", "text": "x"}]}],
            model="demo-model",
            temperature=0.0,
            top_p=1.0,
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)


def test_extract_llm_usage_supports_chat_completions_fallback():
    pt, ct, tt = llm_client_module._extract_llm_usage(  # noqa: SLF001
        {"usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}
    )
    assert (pt, ct, tt) == (11, 7, 18)


def test_llm_vision_uses_responses_image_and_text_parts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "vision-model")

    llm = _reload_llm_modules()
    captured = {}

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"output_text": "vision-ok"})

    monkeypatch.setattr(llm, "urlopen", fake_urlopen)

    text = llm.call_llm_vision_text(
        image_url="data:image/png;base64,abc",
        prompt="describe",
        system="system-note",
    )

    assert text == "vision-ok"
    parts = captured["body"]["input"][0]["content"]
    assert parts[0] == {"type": "input_image", "image_url": "data:image/png;base64,abc"}
    assert parts[1]["type"] == "input_text"
    assert "system-note" in parts[1]["text"]
    assert "describe" in parts[1]["text"]
