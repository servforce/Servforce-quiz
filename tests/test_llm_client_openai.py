import importlib

import backend.md_quiz.config as config_module
import backend.md_quiz.services.llm_client as llm_client_module


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.output_text = payload.get("output_text")
        self.usage = payload.get("usage")
        self.model = payload.get("model")

    def model_dump(self, mode: str = "json"):  # noqa: ARG002
        return dict(self._payload)


class _FakeResponsesResource:
    def __init__(self, captured: dict, payload: dict):
        self._captured = captured
        self._payload = payload

    def create(self, **kwargs):
        self._captured["request"] = kwargs
        return _FakeResponse(self._payload)


class _FakeFilesResource:
    def __init__(self, captured: dict):
        self._captured = captured

    def create(self, *, file, purpose: str, **kwargs):  # noqa: ARG002
        self._captured["file_upload_purpose"] = purpose
        self._captured["file_upload_name"] = getattr(file, "name", "")
        self._captured["file_upload_bytes"] = file.read()

        class _Uploaded:
            id = "file-test-123"

        return _Uploaded()

    def delete(self, file_id: str):
        self._captured["file_deleted"] = file_id
        return {"id": file_id, "deleted": True}


class _FakeOpenAI:
    def __init__(self, *, api_key: str, base_url: str, max_retries: int):
        self._captured = {
            "api_key": api_key,
            "base_url": base_url,
            "max_retries": max_retries,
        }
        self._payload = {"output_text": "ok", "model": "demo-model"}
        self.responses = _FakeResponsesResource(self._captured, self._payload)
        self.files = _FakeFilesResource(self._captured)

    def with_options(self, **kwargs):
        self._captured["options"] = kwargs
        return self


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
    monkeypatch.setenv("LLM_RETRY_MAX", "2")

    llm = _reload_llm_modules()
    monkeypatch.setattr(llm, "OpenAI", lambda **kwargs: _FakeOpenAI(**kwargs))
    llm._OPENAI_CLIENT = None  # noqa: SLF001

    text = llm.call_llm_text("hello")

    assert text == "ok"
    client = llm._OPENAI_CLIENT  # noqa: SLF001
    assert isinstance(client, _FakeOpenAI)
    assert client._captured["api_key"] == "test-key"
    assert client._captured["base_url"] == "https://example.test/v1"
    assert client._captured["max_retries"] == 2
    assert client._captured["request"]["model"] == "demo-model"
    assert client._captured["request"]["instructions"] == "你是一名资深面试官与能力评估专家。"
    assert client._captured["request"]["input"][0]["content"][0]["type"] == "input_text"


def test_llm_json_uses_llm_timeout_json_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "demo-model")
    monkeypatch.setenv("LLM_TIMEOUT_JSON", "123")

    llm = _reload_llm_modules()
    client = _FakeOpenAI(api_key="test-key", base_url="https://example.test/v1", max_retries=2)
    monkeypatch.setattr(llm, "_get_openai_client", lambda: client)

    text = llm.call_llm_json("grade this answer")

    assert text == "ok"
    timeout = client._captured["options"]["timeout"]
    assert timeout.connect == 20.0
    assert timeout.read == 123.0
    assert timeout.write == 123.0


def test_llm_client_missing_openai_api_key_points_to_new_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "demo-model")
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    llm = _reload_llm_modules()
    llm._OPENAI_CLIENT = None  # noqa: SLF001

    try:
        llm._get_openai_client()  # noqa: SLF001
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
    client = _FakeOpenAI(api_key="test-key", base_url="https://example.test/v1", max_retries=2)
    client._payload = {"output_text": "vision-ok", "model": "vision-model"}
    client.responses = _FakeResponsesResource(client._captured, client._payload)
    monkeypatch.setattr(llm, "_get_openai_client", lambda: client)

    text = llm.call_llm_vision_text(
        image_url="data:image/png;base64,abc",
        prompt="describe",
        system="system-note",
    )

    assert text == "vision-ok"
    parts = client._captured["request"]["input"][0]["content"]
    assert parts[0] == {"type": "input_image", "image_url": "data:image/png;base64,abc"}
    assert parts[1] == {"type": "input_text", "text": "describe"}
    assert client._captured["request"]["instructions"] == "system-note"


def test_llm_file_structured_uses_input_file_part(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "structured-model")

    llm = _reload_llm_modules()
    client = _FakeOpenAI(api_key="test-key", base_url="https://example.test/v1", max_retries=2)
    client._payload = {"output_text": '{"name":"张三"}', "model": "structured-model"}
    client.responses = _FakeResponsesResource(client._captured, client._payload)
    monkeypatch.setattr(llm, "_get_openai_client", lambda: client)

    raw, err = llm.call_llm_file_structured_ex(
        file_bytes=b"resume-bytes",
        filename="resume.docx",
        prompt="extract fields",
        system="system-note",
    )

    assert err == ""
    assert raw == '{"name":"张三"}'
    parts = client._captured["request"]["input"][0]["content"]
    assert parts[0]["type"] == "input_file"
    assert parts[0]["file_id"] == "file-test-123"
    assert parts[1] == {"type": "input_text", "text": "extract fields"}
    assert client._captured["request"]["instructions"] == "system-note"
    assert client._captured["file_upload_purpose"] == "user_data"
    assert client._captured["file_upload_name"] == "resume.docx"
    assert client._captured["file_upload_bytes"] == b"resume-bytes"
    assert client._captured["file_deleted"] == "file-test-123"
