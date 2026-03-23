from __future__ import annotations

from web.routes.admin_assignments import register_admin_assignment_routes
from web.routes.admin_candidates import register_admin_candidate_routes
from web.routes.admin_exams import register_admin_exam_routes
from web.routes.admin_shell import register_admin_shell_routes


def register_admin_routes(app):
    register_admin_shell_routes(app)
    register_admin_exam_routes(app)
    register_admin_candidate_routes(app)
    register_admin_assignment_routes(app)
