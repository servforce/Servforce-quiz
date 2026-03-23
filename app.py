from __future__ import annotations

import os

from web.app_factory import create_app
from web.runtime_setup import RuntimeBootstrapError
from web.runtime_support import *  # noqa: F401,F403


if __name__ == "__main__":
    try:
        app = create_app()
    except RuntimeBootstrapError as exc:
        raise SystemExit(str(exc)) from exc
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
