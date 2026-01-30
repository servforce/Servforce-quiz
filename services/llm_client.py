"""
LLM client helpers used by grading and evaluation.

Supports:
- OpenAI-compatible endpoints (DashScope / 讯飞 MaaS / self-hosted gateways)
- Local Ollama (free, no API key)
"""

from __future__ import annotations

import json
import os
import time
from urllib.request import Request, urlopen

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    QWEN_MODEL,
    logger,
)

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI  # type: ignore
        except ModuleNotFoundError as e:
            raise RuntimeError("Missing dependency: openai. Please install requirements.txt") from e
        _openai_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _openai_client


def _supports_response_format_json() -> bool:
    return os.getenv("LLM_RESPONSE_FORMAT_JSON", "").strip().lower() in {"1", "true", "yes"}


def _ollama_chat(prompt: str, *, system: str, model: str, format_json: bool) -> str:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload: dict[str, object] = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if format_json:
        payload["format"] = "json"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    return str(((obj.get("message") or {}).get("content") or "")).strip()


def call_llm_json(prompt: str, model: str = QWEN_MODEL) -> str:
    """
    Structured output call used by short-answer grading.
    Expected to return a JSON object string: {"score":0..max,"reason":"..."}.
    """
    try:
        start = time.time()
        system = "你是严格的阅卷老师，必须按评分标准评分。请输出 JSON：{\"score\":0..max,\"reason\":\"...\"}。"

        if LLM_PROVIDER == "ollama":
            out = _ollama_chat(prompt, system=system, model=OLLAMA_MODEL, format_json=True)
            logger.debug("LLM(ollama) ok in %.2fs", time.time() - start)
            return out

        if not LLM_API_KEY:
            logger.error("LLM_API_KEY is empty (LLM_PROVIDER=openai_compat)")
            return ""

        kwargs: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "top_p": 1,
            "presence_penalty": 0,
            "frequency_penalty": 0,
            "n": 1,
            "seed": 42,
        }
        if _supports_response_format_json():
            kwargs["response_format"] = {"type": "json_object"}

        response = _get_openai_client().chat.completions.create(**kwargs)  # type: ignore[arg-type]
        logger.debug("LLM(openai_compat) ok in %.2fs", time.time() - start)
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return ""


def call_llm_text(prompt: str, model: str = QWEN_MODEL) -> str:
    """
    Free-text call used by remark generation.
    """
    try:
        start = time.time()
        system = "你是一名资深面试官与能力评估专家。"

        if LLM_PROVIDER == "ollama":
            out = _ollama_chat(prompt, system=system, model=OLLAMA_MODEL, format_json=False)
            logger.debug("LLM(ollama,text) ok in %.2fs", time.time() - start)
            return out

        if not LLM_API_KEY:
            logger.error("LLM_API_KEY is empty (LLM_PROVIDER=openai_compat)")
            return ""

        response = _get_openai_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            top_p=1,
            presence_penalty=0,
            frequency_penalty=0,
            n=1,
            seed=42,
        )
        logger.debug("LLM(openai_compat,text) ok in %.2fs", time.time() - start)
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"LLM call failed (text): {e}")
        return ""
