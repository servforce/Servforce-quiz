from __future__ import annotations

from web.runtime_support import *


def register_shared_routes(app: Flask) -> None:
    #
    @app.errorhandler(FileNotFoundError)
    def _handle_file_not_found(_e):
        return "Not Found", 404

    @app.template_filter("md")
    def _render_md(value: str) -> Markup:
        # Escape HTML tags/entities to avoid XSS, but keep quotes so code samples display normally.
        # Also protect TeX math so Markdown doesn't consume `\\\\` row separators (hard line breaks).
        protected, math_repls = _protect_math_for_markdown(value)
        text = html.escape(protected, quote=False)
        rendered = mdlib.markdown(
            text,
            extensions=[
                "markdown.extensions.fenced_code",
                "markdown.extensions.footnotes",
                "markdown.extensions.attr_list",
                "markdown.extensions.def_list",
                "markdown.extensions.tables",
                "markdown.extensions.abbr",
                "markdown.extensions.md_in_html",
                "markdown.extensions.sane_lists",
            ],
            output_format="html5",
        )
        for token, math_html in math_repls:
            rendered = rendered.replace(token, math_html)
        return Markup(rendered)

    @app.template_filter("title_clean")
    def _title_clean(value: str) -> str:
        # Remove parenthesized qualifiers in both full-width and half-width styles.
        s = str(value or "")
        s = re.sub(r"（[^）]*）", "", s)
        s = re.sub(r"\([^)]*\)", "", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return s

    @app.get("/exams/<exam_key>/assets/<path:relpath>")
    def public_exam_asset(exam_key: str, relpath: str):
        asset = _resolve_exam_asset_payload(exam_key, relpath)
        if not asset:
            abort(404)
        content, mime = asset
        return send_file(BytesIO(content), mimetype=mime)

    @app.get("/exams/versions/<int:version_id>/assets/<path:relpath>")
    def public_exam_version_asset(version_id: int, relpath: str):
        asset = _resolve_exam_asset_payload_by_version(version_id, relpath)
        if not asset:
            abort(404)
        content, mime = asset
        return send_file(BytesIO(content), mimetype=mime)

    @app.get("/")   # session 里是否已登录管理员，决定跳转到后台首页还是登录页
    def index():
        if session.get("admin_logged_in"):
            return redirect(url_for("admin_dashboard"))     # 跳转到admin_dashboard对应的页面去，反向寻到url
        return redirect(url_for("admin_login"))
