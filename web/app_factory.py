from __future__ import annotations

from flask import Flask

from config import BASE_DIR, SECRET_KEY
from web.routes.admin import register_admin_routes
from web.routes.public import register_public_routes
from web.routes.shared import register_shared_routes
from web.runtime_setup import bootstrap_runtime


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.secret_key = SECRET_KEY

    bootstrap_runtime(app)
    register_shared_routes(app)
    register_admin_routes(app)
    register_public_routes(app)
    return app
