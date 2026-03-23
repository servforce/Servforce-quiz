from __future__ import annotations

from web.routes.public_exam_routes import register_public_exam_routes
from web.routes.public_resume import register_public_resume_routes
from web.routes.public_verify import register_public_verify_routes


def register_public_routes(app):
    register_public_verify_routes(app)
    register_public_resume_routes(app)
    register_public_exam_routes(app)
