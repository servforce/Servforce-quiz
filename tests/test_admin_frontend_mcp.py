from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_router_registers_mcp_route() -> None:
    source = (ROOT / "static" / "admin" / "modules" / "router.js").read_text(encoding="utf-8")
    nav_source = (ROOT / "static" / "admin" / "modules" / "state.js").read_text(encoding="utf-8")
    status_source = (ROOT / "static" / "admin" / "modules" / "pages" / "status.js").read_text(encoding="utf-8")

    assert 'mcp: { fragment: "/static/admin/pages/mcp.html"' in source
    assert '/admin/mcp' in nav_source
    assert 'label: "MCP"' in nav_source
    assert 'copyMcpUrl' in status_source


def test_admin_mcp_page_fragment_contains_actions() -> None:
    source = (ROOT / "static" / "admin" / "pages" / "mcp.html").read_text(encoding="utf-8")

    assert "复制 MCP 地址" in source
    assert "打开 MCP 文档" in source
