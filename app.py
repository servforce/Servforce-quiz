from __future__ import annotations

import os

from web.app_factory import create_app
from web.runtime_setup import RuntimeBootstrapError
from web.runtime_support import *  # noqa: F401,F403


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


if __name__ == "__main__":
    try:
        app = create_app()
    except RuntimeBootstrapError as exc:
        raise SystemExit(str(exc)) from exc
    debug = _env_bool("APP_DEBUG", True)
    app.run(
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=debug,
        use_reloader=_env_bool("APP_USE_RELOADER", debug),
    )
