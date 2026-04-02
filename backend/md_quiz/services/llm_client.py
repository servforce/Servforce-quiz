"""
LLM client helpers used by grading, evaluation and resume parsing.

All vendors are accessed via the official OpenAI Python SDK against an
OpenAI-compatible Responses API.
"""

from __future__ import annotations

import os
import time
from io import BytesIO
from typing import Any

import httpx
from openai import OpenAI

from backend.md_quiz.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, logger
from backend.md_quiz.services.audit_context import get_audit_context, incr_audit_meta_int
from backend.md_quiz.services.system_metrics import incr_llm_tokens_and_alert, record_llm_usage


_OPENAI_CLIENT: OpenAI | None = None


def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            dumped = obj.model_dump(mode="json")
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    return {}


def _extract_llm_usage(obj: Any) -> tuple[int | None, int | None, int | None]:
    usage = None
    if isinstance(obj, dict):
        usage = obj.get("usage")
    else:
        usage = getattr(obj, "usage", None)
        if usage is None:
            usage = _as_dict(obj).get("usage")
    if usage is None:
        return None, None, None

    if not isinstance(usage, dict):
        usage = _as_dict(usage)
    if not isinstance(usage, dict):
        return None, None, None

    def _int(v: Any) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    inp = _int(usage.get("input_tokens"))
    out = _int(usage.get("output_tokens"))
    tot = _int(usage.get("total_tokens"))
    if inp is None:
        inp = _int(usage.get("prompt_tokens"))
    if out is None:
        out = _int(usage.get("completion_tokens"))
    if tot is None:
        tot = _int(usage.get("total_tokens"))
    return inp, out, tot


def _response_model_name(obj: Any) -> str | None:
    model = getattr(obj, "model", None)
    if isinstance(model, str) and model.strip():
        return model.strip()
    data = _as_dict(obj)
    model = data.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return None


def _accumulate_llm_usage(obj: Any) -> None:
    """
    Track total token usage in the current audit context meta without writing system_log rows.
    """
    try:
        _ptk, _ctk, ttk = _extract_llm_usage(obj)
    except Exception:
        ttk = None
    incr_audit_meta_int("llm_total_tokens_sum", ttk)
    try:
        incr_llm_tokens_and_alert(ttk)
    except Exception:
        pass
    try:
        record_llm_usage(total_tokens=ttk, ctx=get_audit_context(), model=_response_model_name(obj))
    except Exception:
        pass


def _supports_response_format_json() -> bool:
    return os.getenv("LLM_RESPONSE_FORMAT_JSON", "").strip().lower() in {"1", "true", "yes"}


def _env_timeout(name: str, default: int) -> int:
    v = str(os.getenv(name, "") or "").strip()
    if not v:
        return int(default)
    try:
        n = int(float(v))
    except Exception:
        return int(default)
    return max(5, min(600, n))


def _env_max_retries() -> int:
    try:
        max_retries = int(os.getenv("LLM_RETRY_MAX", "2") or "2")
    except Exception:
        max_retries = 2
    return max(0, min(6, max_retries))


def _request_timeout(timeout_seconds: int) -> httpx.Timeout:
    total = float(max(5, int(timeout_seconds or 60)))
    connect = min(20.0, total)
    return httpx.Timeout(total, connect=connect, read=total, write=total)


def _get_openai_client() -> OpenAI:
    global _OPENAI_CLIENT
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is empty")
    if _OPENAI_CLIENT is None:
        _OPENAI_CLIENT = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL.rstrip("/"),
            max_retries=_env_max_retries(),
        )
    return _OPENAI_CLIENT


def _responses_api_request(
    *,
    input_messages: list[dict[str, Any]],
    model: str,
    temperature: float,
    top_p: float,
    timeout_seconds: int = 60,
    response_format_json: bool = False,
    instructions: str | None = None,
) -> Any:
    client = _get_openai_client().with_options(
        timeout=_request_timeout(timeout_seconds),
        max_retries=_env_max_retries(),
    )
    payload: dict[str, Any] = {
        "model": model,
        "input": input_messages,
        "temperature": temperature,
        "top_p": top_p,
    }
    if str(instructions or "").strip():
        payload["instructions"] = str(instructions or "").strip()
    if response_format_json:
        payload["text"] = {"format": {"type": "json_object"}}
    return client.responses.create(**payload)


def _extract_output_text(obj: Any) -> str:
    """
    Try a few common OpenAI Responses-compatible shapes.
    """
    t = getattr(obj, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t.strip()

    data = _as_dict(obj)
    if not data:
        return ""

    t = data.get("output_text")
    if isinstance(t, str) and t.strip():
        return t.strip()

    out = data.get("output")
    if isinstance(out, list):
        parts: list[str] = []
        for item in out:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if str(c.get("type") or "") in {"output_text", "text"} and isinstance(c.get("text"), str):
                    parts.append(str(c.get("text") or ""))
        txt = "".join(parts).strip()
        if txt:
            return txt

    try:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            msg = (choices[0] or {}).get("message") or {}
            if isinstance(msg, dict):
                return str(msg.get("content") or "").strip()
    except Exception:
        pass
    return ""


def _to_text_parts(prompt: str) -> list[dict[str, Any]]:
    return [{"type": "input_text", "text": str(prompt or "")}]


def call_llm_json(prompt: str, model: str | None = None) -> str:
    """
    Structured output call used by short-answer grading.
    Expected to return a JSON object string with score + explanation.
    """
    try:
        start = time.time()
        system = (
            "你是一名公正的阅卷老师，必须严格依据评分标准评分，但要允许部分得分。\n"
            "要求：\n"
            "1) score 必须是 0..max 的整数（可取中间分，不要只给 0 或满分）。\n"
            "2) 若答案只覆盖部分要点，请给对应比例的分数。\n"
            "3) 只输出一个 JSON 对象，不要输出多余文本。\n"
            "4) 字段：\n"
            "   - score: 0..max 的整数\n"
            "   - reason: 1-3 句简短理由\n"
            "   - relevance: 0..3（0=完全无关/无意义）\n"
            "   - contradiction: true/false（关键事实说反/矛盾时为 true，且应 score=0）\n"
            '示例：{"score":3,"reason":"...","relevance":2,"contradiction":false}\n'
        )
        use_model = (model or "").strip() or OPENAI_MODEL
        obj = _responses_api_request(
            input_messages=[{"role": "user", "content": _to_text_parts(str(prompt or ""))}],
            instructions=system,
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_JSON", 90),
            response_format_json=_supports_response_format_json(),
        )
        dt = time.time() - start
        logger.debug("LLM(json) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj)
    except Exception as e:
        logger.error("LLM call failed (json): %s", e)
        return ""


def call_llm_text(prompt: str, model: str | None = None) -> str:
    """
    Free-text call used by remark generation.
    """
    try:
        start = time.time()
        system = "你是一名资深面试官与能力评估专家。"
        use_model = (model or "").strip() or OPENAI_MODEL
        obj = _responses_api_request(
            input_messages=[{"role": "user", "content": _to_text_parts(str(prompt or ""))}],
            instructions=system,
            model=use_model,
            temperature=0.2,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_TEXT", 90),
            response_format_json=False,
        )
        dt = time.time() - start
        logger.debug("LLM(text) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj)
    except Exception as e:
        logger.error("LLM call failed (text): %s", e)
        return ""


def call_llm_structured(prompt: str, *, system: str, model: str | None = None) -> str:
    txt, _err = call_llm_structured_ex(prompt, system=system, model=model)
    return txt


def call_llm_structured_ex(
    prompt: str,
    *,
    system: str,
    model: str | None = None,
) -> tuple[str, str]:
    """
    Generic structured call returning a JSON string (best-effort).
    Used by various extractors.
    """
    try:
        start = time.time()
        use_model = (model or "").strip() or OPENAI_MODEL
        obj = _responses_api_request(
            input_messages=[{"role": "user", "content": _to_text_parts(str(prompt or ""))}],
            instructions=system,
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_STRUCTURED", 120),
            response_format_json=_supports_response_format_json(),
        )
        dt = time.time() - start
        logger.debug("LLM(structured) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj), ""
    except Exception as e:
        logger.error("LLM call failed (structured): %s", e)
        return "", f"{type(e).__name__}: {e}"


def call_llm_file_structured_ex(
    *,
    file_bytes: bytes,
    filename: str,
    prompt: str,
    system: str,
    model: str | None = None,
) -> tuple[str, str]:
    """
    Structured Responses call using an attached file input.
    """
    uploaded_file_id = ""
    try:
        start = time.time()
        use_model = (model or "").strip() or OPENAI_MODEL
        client = _get_openai_client().with_options(
            timeout=_request_timeout(_env_timeout("LLM_TIMEOUT_STRUCTURED", 120)),
            max_retries=_env_max_retries(),
        )
        file_obj = BytesIO(bytes(file_bytes or b""))
        file_obj.name = str(filename or "resume.bin")
        uploaded = client.files.create(file=file_obj, purpose="user_data")
        uploaded_file_id = str(getattr(uploaded, "id", "") or "").strip()
        if not uploaded_file_id:
            raise RuntimeError("Files API returned empty file id")
        parts: list[dict[str, Any]] = [
            {
                "type": "input_file",
                "file_id": uploaded_file_id,
            },
            {"type": "input_text", "text": str(prompt or "")},
        ]
        obj = _responses_api_request(
            input_messages=[{"role": "user", "content": parts}],
            instructions=system,
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_STRUCTURED", 120),
            response_format_json=_supports_response_format_json(),
        )
        dt = time.time() - start
        logger.debug("LLM(file-structured) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj), ""
    except Exception as e:
        logger.error("LLM call failed (file-structured): %s", e)
        return "", f"{type(e).__name__}: {e}"
    finally:
        if uploaded_file_id:
            try:
                _get_openai_client().files.delete(uploaded_file_id)
            except Exception:
                logger.warning("Failed to cleanup uploaded LLM file: %s", uploaded_file_id)


def call_llm_vision_text(
    *,
    image_url: str,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
) -> str:
    """
    Vision call using Responses API "input_image" + "input_text".
    """
    try:
        start = time.time()
        use_model = (model or "").strip() or OPENAI_MODEL
        parts: list[dict[str, Any]] = [
            {"type": "input_image", "image_url": str(image_url or "")},
            {"type": "input_text", "text": str(prompt or "")},
        ]
        obj = _responses_api_request(
            input_messages=[{"role": "user", "content": parts}],
            instructions=(str(system or "").strip() or None),
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_VISION", 120),
            response_format_json=False,
        )
        dt = time.time() - start
        logger.debug("LLM(vision) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj)
    except Exception as e:
        logger.error("LLM call failed (vision): %s", e)
        return ""


def call_llm_vision_structured_ex(
    *,
    image_url: str,
    prompt: str,
    system: str,
    model: str | None = None,
) -> tuple[str, str]:
    """
    Structured Responses call using an image input.
    """
    try:
        start = time.time()
        use_model = (model or "").strip() or OPENAI_MODEL
        parts: list[dict[str, Any]] = [
            {"type": "input_image", "image_url": str(image_url or "")},
            {"type": "input_text", "text": str(prompt or "")},
        ]
        obj = _responses_api_request(
            input_messages=[{"role": "user", "content": parts}],
            instructions=system,
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_VISION", 120),
            response_format_json=_supports_response_format_json(),
        )
        dt = time.time() - start
        logger.debug("LLM(vision-structured) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj), ""
    except Exception as e:
        logger.error("LLM call failed (vision-structured): %s", e)
        return "", f"{type(e).__name__}: {e}"
