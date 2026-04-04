from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_app_registers_mcp_nav_and_route():
    source = (ROOT / "static" / "admin" / "app.js").read_text(encoding="utf-8")

    assert '/admin/mcp' in source
    assert 'label: "MCP"' in source
    assert 'name: "mcp"' in source
    assert "copyMcpUrl" in source


def test_admin_index_contains_mcp_page_content():
    source = (ROOT / "static" / "admin" / "index.html").read_text(encoding="utf-8")

    assert "route.name === 'mcp'" in source
    assert "复制 MCP 地址" in source
    assert "打开 MCP 文档" in source
