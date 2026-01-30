from __future__ import annotations

import json
import sys
from urllib.request import Request, urlopen

from config import LLM_API_KEY, LLM_BASE_URL, LLM_PROVIDER, OLLAMA_BASE_URL, OLLAMA_MODEL, QWEN_MODEL


def ollama_chat() -> str:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [{"role": "user", "content": "ping"}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    return str(((obj.get("message") or {}).get("content") or "")).strip()


def openai_compat_chat() -> str:
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is empty")
    try:
        from openai import OpenAI  # type: ignore
    except ModuleNotFoundError as e:
        raise RuntimeError("Missing dependency: openai. Please install requirements.txt") from e
    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    r = client.chat.completions.create(
        model=QWEN_MODEL,
        messages=[{"role": "user", "content": "ping"}],
        temperature=0,
    )
    return (r.choices[0].message.content or "").strip()


def main() -> int:
    print("provider:", LLM_PROVIDER)
    if LLM_PROVIDER == "ollama":
        print("ollama:", OLLAMA_BASE_URL, "model:", OLLAMA_MODEL)
        print("reply:", ollama_chat())
        return 0
    print("base_url:", LLM_BASE_URL, "model:", QWEN_MODEL, "key_len:", len(LLM_API_KEY))
    print("reply:", openai_compat_chat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
