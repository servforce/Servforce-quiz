from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _fragments_from_mapping(source: str, prefix: str) -> list[str]:
    pattern = re.compile(rf'"/static/{re.escape(prefix)}/([^"\n]+\.html)"')
    return pattern.findall(source)


def test_admin_route_fragments_exist() -> None:
    source = (ROOT / "static" / "admin" / "modules" / "router.js").read_text(encoding="utf-8")
    names = _fragments_from_mapping(source, "admin/pages")

    assert names
    for name in names:
        assert (ROOT / "static" / "admin" / "pages" / name).exists(), name


def test_public_view_fragments_exist() -> None:
    source = (ROOT / "static" / "public" / "modules" / "view-loader.js").read_text(encoding="utf-8")
    names = _fragments_from_mapping(source, "public/views")

    assert names
    for name in names:
        assert (ROOT / "static" / "public" / "views" / name).exists(), name


def test_css_build_script_produces_bundles() -> None:
    subprocess.run(
        ["node", "static/scripts/build-admin-css.cjs"],
        cwd=ROOT,
        check=True,
    )

    assert (ROOT / "static" / "admin.css").exists()
    assert (ROOT / "static" / "public.css").exists()


def test_admin_candidates_page_uses_resume_job_polling() -> None:
    source = (ROOT / "static" / "admin" / "modules" / "pages" / "candidates.js").read_text(encoding="utf-8")

    assert "/api/admin/candidates/resume/upload-job" in source
    assert "/resume/reparse-job" in source
    assert "/api/admin/jobs/" in source
    assert "scheduleCandidateResumeUploadPolling" in source
    assert "scheduleCandidateResumeReparsePolling" in source


def test_admin_assignments_page_exposes_pagination_controls() -> None:
    source = (ROOT / "static" / "admin" / "pages" / "assignments.html").read_text(encoding="utf-8")

    assert "首页" in source
    assert "上一页" in source
    assert "下一页" in source
    assert "末页" in source


def test_admin_assignments_module_uses_page_query_param() -> None:
    source = (ROOT / "static" / "admin" / "modules" / "pages" / "assignments.js").read_text(encoding="utf-8")

    assert 'query.set("page"' in source
    assert "scheduleAssignmentsReloadFromFirstPage" in source


def test_admin_quiz_analytics_route_and_nav_exist() -> None:
    router_source = (ROOT / "static" / "admin" / "modules" / "router.js").read_text(encoding="utf-8")
    state_source = (ROOT / "static" / "admin" / "modules" / "state.js").read_text(encoding="utf-8")

    assert '"/static/admin/pages/quiz-analytics.html"' in router_source
    assert 'path === "/admin/quiz-analytics"' in router_source
    assert 'name: "quiz-analytics"' in router_source
    assert 'href: "/admin/quiz-analytics"' in state_source
    assert 'label: "测验分析"' in state_source
