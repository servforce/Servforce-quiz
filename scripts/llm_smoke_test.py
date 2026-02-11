from __future__ import annotations

import sys

from services.llm_client import call_llm_text


def main() -> int:
    out = (call_llm_text("ping") or "").strip()
    if not out:
        print("LLM smoke test failed: empty response. Check DOUBAO_API_KEY/ARK_API_KEY and DOUBAO_MODEL.")
        return 2
    print("ok:", out[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

