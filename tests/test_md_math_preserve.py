import html

import markdown as mdlib

from app import _protect_math_for_markdown


def test_md_filter_preserves_tex_row_separators() -> None:
    src = (
        "$$\n"
        "\\begin{cases}\n"
        "x_{1}+x_{2}+x_{3} = 3 \\\\\n"
        "2x_{1}+2x_{2}+x_{4} = 4 \\\\\n"
        "x_1, \\cdots, x_4 \\ge 0\n"
        "\\end{cases}\n"
        "$$\n"
    )

    protected, math_repls = _protect_math_for_markdown(src)
    escaped = html.escape(protected, quote=False)
    rendered = mdlib.markdown(
        escaped,
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

    # If Python-Markdown consumes trailing backslashes, it may emit <br /> and the TeX loses `\\\\`.
    assert "<br" not in rendered.lower()
    assert "= 3 \\\\" in rendered
    assert "= 4 \\\\" in rendered
