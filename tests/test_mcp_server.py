from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from backend.md_quiz.app import create_app
from backend.md_quiz.storage.db import conn_scope, create_quiz_version, save_quiz_definition


def _reset_runtime_tables():
    from backend.md_quiz.storage.db import init_db

    init_db()
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM quiz_version_asset")
            cur.execute("DELETE FROM quiz_archive")
            cur.execute("DELETE FROM quiz_paper")
            cur.execute("DELETE FROM assignment_record")
            cur.execute("DELETE FROM quiz_version")
            cur.execute("DELETE FROM quiz_asset")
            cur.execute("DELETE FROM quiz_definition")
            cur.execute("DELETE FROM candidate")
            cur.execute("DELETE FROM process_heartbeat")
            cur.execute("DELETE FROM runtime_job")
            cur.execute("DELETE FROM runtime_daily_metric")
            cur.execute("DELETE FROM runtime_kv")


def _build_client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setenv("MCP_ENABLED", "1")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-mcp-token")
    _reset_runtime_tables()
    app = create_app()
    return TestClient(app)


def _seed_exam_with_answer_time(quiz_key: str) -> int:
    spec = {
        "id": quiz_key,
        "title": "答题时长演示",
        "description": "用于 MCP 测试。",
        "tags": ["timing", "answer-time"],
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "answer_time_seconds": 45,
                "options": [{"key": "A", "text": "选项A", "correct": True}],
            }
        ],
    }
    public_spec = {
        "id": quiz_key,
        "title": "答题时长演示",
        "description": "用于 MCP 测试。",
        "tags": ["timing", "answer-time"],
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "answer_time_seconds": 45,
                "options": [{"key": "A", "text": "选项A"}],
            }
        ],
    }
    version_id = create_quiz_version(
        quiz_key=quiz_key,
        version_no=1,
        title="答题时长演示",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="answertime01",
        content_hash=f"hash-{quiz_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title="答题时长演示",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="answertime01",
        last_sync_error="",
    )
    return version_id


def _httpx_factory_for(app):
    def _factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    return _factory


def _tool_structured(result):
    return result.structuredContent


def test_mcp_requires_bearer_token(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/mcp")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_mcp_tool_flow_and_safety(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_answer_time("mcp-demo")

    with client:
        async with streamablehttp_client(
            "http://testserver/mcp",
            headers={"Authorization": "Bearer test-mcp-token"},
            httpx_client_factory=_httpx_factory_for(client.app),
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert "candidate_ensure" in tool_names
                assert "assignment_create" in tool_names
                assert "candidate_delete" in tool_names

                ensure_result = await session.call_tool(
                    "candidate_ensure",
                    {"name": "测试候选人", "phone": "13912345678"},
                )
                ensure_payload = _tool_structured(ensure_result)
                candidate_id = int(ensure_payload["candidate"]["id"])
                assert ensure_payload["candidate"]["phone"] == "139****5678"

                candidate_result = await session.call_tool("candidate_get", {"candidate_id": candidate_id})
                candidate_payload = _tool_structured(candidate_result)
                assert candidate_payload["candidate"]["phone"] == "139****5678"
                assert candidate_payload["resume_parsed"]["details"]["status"] == ""

                assignment_result = await session.call_tool(
                    "assignment_create",
                    {
                        "quiz_key": "mcp-demo",
                        "candidate_id": candidate_id,
                        "invite_start_date": "2026-04-01",
                        "invite_end_date": "2026-04-02",
                    },
                )
                assignment_payload = _tool_structured(assignment_result)
                token = str(assignment_payload["token"])
                assert assignment_payload["invite_path"] == f"/t/{token}"

                assignment_detail = await session.call_tool("assignment_get", {"token": token})
                assignment_detail_payload = _tool_structured(assignment_detail)
                assert assignment_detail_payload["review_summary"]["answers_count"] == 0

                delete_preview = await session.call_tool("candidate_delete", {"candidate_id": candidate_id})
                delete_preview_payload = _tool_structured(delete_preview)
                assert delete_preview_payload["requires_confirmation"] is True

                bootstrap_response = client.get("/api/system/bootstrap")
                assert bootstrap_response.status_code == 200
                assert bootstrap_response.json()["mcp"]["path"] == "/mcp"
