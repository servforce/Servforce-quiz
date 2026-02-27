"""
LLM client helpers used by grading and evaluation.

Doubao (Volcengine Ark) is used exclusively via the OpenAI-compatible Responses API.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import DOUBAO_API_KEY, DOUBAO_BASE_URL, DOUBAO_MODEL, logger
from services.audit_context import incr_audit_meta_int


def _extract_llm_usage(obj: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    try:
        usage = obj.get("usage")
    except Exception:
        usage = None
    if not isinstance(usage, dict):
        return None, None, None

    def _int(v):
        if v is None or v == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    # OpenAI Responses style: input_tokens/output_tokens/total_tokens.
    inp = _int(usage.get("input_tokens"))
    out = _int(usage.get("output_tokens"))
    tot = _int(usage.get("total_tokens"))
    # ChatCompletions style fallback.
    if inp is None:
        inp = _int(usage.get("prompt_tokens"))
    if out is None:
        out = _int(usage.get("completion_tokens"))
    if tot is None:
        tot = _int(usage.get("total_tokens"))
    return inp, out, tot


def _accumulate_llm_usage(obj: dict[str, Any]) -> None:
    """
    Track total token usage in the current audit context meta without writing system_log rows.
    """
    try:
        _ptk, _ctk, ttk = _extract_llm_usage(obj)
    except Exception:
        ttk = None
    incr_audit_meta_int("llm_total_tokens_sum", ttk)


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


def _doubao_responses(
    *,
    input_messages: list[dict[str, Any]],
    model: str,
    temperature: float,
    top_p: float,
    timeout_seconds: int = 60,
    response_format_json: bool = False,
) -> dict[str, Any]:
    if not DOUBAO_API_KEY:
        raise RuntimeError("DOUBAO_API_KEY/ARK_API_KEY is empty")

    url = f"{DOUBAO_BASE_URL.rstrip('/')}/responses"
    payload: dict[str, Any] = {
        "model": model,
        "input": input_messages,
        "temperature": temperature,
        "top_p": top_p,
    }
    # Best-effort: some OpenAI-compatible providers support response_format for JSON.
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {DOUBAO_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # Retry on transient errors (rate limit / gateway / network).
    try:
        max_retries = int(os.getenv("LLM_RETRY_MAX", "2") or "2")
    except Exception:
        max_retries = 2
    max_retries = max(0, min(6, max_retries))

    try:
        backoff = float(os.getenv("LLM_RETRY_BACKOFF", "0.9") or "0.9")
    except Exception:
        backoff = 0.9
    backoff = max(0.2, min(5.0, backoff))

    raw = ""
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            last_err = None
            break
        except HTTPError as e:
            last_err = e
            code = int(getattr(e, "code", 0) or 0)
            retryable = code in {429, 500, 502, 503, 504}
            try:
                body_txt = e.read().decode("utf-8", errors="replace")
            except Exception:
                body_txt = ""
            if attempt >= max_retries or not retryable:
                raise RuntimeError(f"Doubao HTTP {code}: {(body_txt or str(e))[:400]}") from e
            logger.warning(
                "LLM HTTP %s (attempt %s/%s): %s",
                code,
                attempt + 1,
                max_retries + 1,
                (body_txt or str(e))[:240],
            )
            time.sleep(backoff * (attempt + 1))
        except URLError as e:
            last_err = e
            if attempt >= max_retries:
                raise
            logger.warning(
                "LLM network error (attempt %s/%s): %s",
                attempt + 1,
                max_retries + 1,
                str(e)[:240],
            )
            time.sleep(backoff * (attempt + 1))
        except Exception as e:
            last_err = e
            if attempt >= max_retries:
                raise
            logger.warning(
                "LLM transient error (attempt %s/%s): %s",
                attempt + 1,
                max_retries + 1,
                str(e)[:240],
            )
            time.sleep(backoff * (attempt + 1))

    if last_err is not None:
        raise last_err
    try:
        return json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Doubao /responses returned non-JSON: {raw[:400]}") from e


def _extract_output_text(obj: dict[str, Any]) -> str:
    """
    Try a few common OpenAI Responses-compatible shapes.
    """
    if not isinstance(obj, dict):
        return ""
    t = obj.get("output_text")
    if isinstance(t, str) and t.strip():
        return t.strip()

    out = obj.get("output")
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

    # Some gateways may still return chat.completions-like shape.
    try:
        choices = obj.get("choices")
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
    Expected to return a JSON object string with score + explanation (and optional guard-rail fields).
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
            "示例：{\"score\":3,\"reason\":\"...\",\"relevance\":2,\"contradiction\":false}\n"
        )
        use_model = (model or "").strip() or DOUBAO_MODEL
        obj = _doubao_responses(
            input_messages=[
                {
                    "role": "user",
                    "content": _to_text_parts(system + "\n" + str(prompt or "")),
                },
            ],
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_JSON", 90),
            response_format_json=_supports_response_format_json(),
        )
        dt = time.time() - start
        logger.debug("LLM(doubao,json) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj)
    except Exception as e:
        logger.error("LLM call failed (doubao,json): %s", e)
        return ""


def call_llm_text(prompt: str, model: str | None = None) -> str:
    """
    Free-text call used by remark generation.
    """
    try:
        start = time.time()
        system = "你是一名资深面试官与能力评估专家。"
        use_model = (model or "").strip() or DOUBAO_MODEL
        obj = _doubao_responses(
            input_messages=[
                {
                    "role": "user",
                    "content": _to_text_parts(system + "\n" + str(prompt or "")),
                },
            ],
            model=use_model,
            temperature=0.2,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_TEXT", 90),
            response_format_json=False,
        )
        dt = time.time() - start
        logger.debug("LLM(doubao,text) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj)
    except Exception as e:
        logger.error("LLM call failed (doubao,text): %s", e)
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
        use_model = (model or "").strip() or DOUBAO_MODEL
        obj = _doubao_responses(
            input_messages=[
                {
                    "role": "user",
                    "content": _to_text_parts(str(system or "") + "\n" + str(prompt or "")),
                },
            ],
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_STRUCTURED", 120),
            response_format_json=_supports_response_format_json(),
        )
        dt = time.time() - start
        logger.debug("LLM(doubao,structured) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj), ""
    except Exception as e:
        logger.error("LLM call failed (doubao,structured): %s", e)
        return "", f"{type(e).__name__}: {e}"


def call_llm_vision_text(
    *,
    image_url: str,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
) -> str:
    """
    Vision call using the /responses "input_image" + "input_text" format (as in the user's curl example).

    Note: you still need to provide a reachable URL or data URL.
    """
    try:
        start = time.time()
        use_model = (model or "").strip() or DOUBAO_MODEL
        parts: list[dict[str, Any]] = [
            {"type": "input_image", "image_url": str(image_url or "")},
            {"type": "input_text", "text": ((str(system or "") + "\n") if system else "") + str(prompt or "")},
        ]
        obj = _doubao_responses(
            input_messages=[{"role": "user", "content": parts}],
            model=use_model,
            temperature=0.0,
            top_p=1.0,
            timeout_seconds=_env_timeout("LLM_TIMEOUT_VISION", 120),
            response_format_json=False,
        )
        dt = time.time() - start
        logger.debug("LLM(doubao,vision) ok in %.2fs", dt)
        _accumulate_llm_usage(obj)
        return _extract_output_text(obj)
    except Exception as e:
        logger.error("LLM call failed (doubao,vision): %s", e)
        return ""
