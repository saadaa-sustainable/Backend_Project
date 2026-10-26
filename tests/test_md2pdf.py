"""The four rendering defects that reached a finished PDF before.

Each was found by looking at output, not by an error, so each gets a
test rather than a comment.
"""
import importlib.util
import pathlib

import pytest

spec = importlib.util.spec_from_file_location(
    "md2pdf", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "md2pdf.py")
md2pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md2pdf)


def test_table_header_is_a_header_not_a_blank_stripe():
    html = md2pdf.convert("| A | B |\n|---|---|\n| 1 | 2 |\n")
    assert "<th>A</th><th>B</th>" in html
    assert "<td>1</td><td>2</td>" in html
    assert "<th></th>" not in html and "<td></td>" not in html
    assert html.count("<tr>") == 2


def test_a_pipe_line_without_a_separator_is_not_a_table():
    """And does not hang the converter.

    This one HUNG rather than failing. A '|' line with no separator row
    beneath it matched no block branch, and the paragraph branch refused
    to collect lines starting with '|', so the cursor never advanced and
    convert() spun forever. Every branch must consume at least one line.
    """
    html = md2pdf.convert("| not a table, just a pipe\n")
    assert "<table>" not in html
    assert "<p>| not a table, just a pipe</p>" in html


def test_every_branch_consumes_at_least_one_line():
    """Progress guarantee, over inputs that match no block cleanly."""
    for src in ("| a\n", ">\n", "|\n", "   \n|x\n", "| a\n| b\n", "- \n"):
        md2pdf.convert(src)  # must terminate


def test_backticks_inside_a_fence_stay_literal():
    html = md2pdf.convert("```text\nspend = `a` + **b**\n```\n")
    assert "<pre><code" in html
    # No chip, no bold: the sample must read exactly as written.
    assert "<code>a</code>" not in html
    assert "<strong>" not in html
    assert "`a`" in html and "**b**" in html


def test_a_wrapped_bullet_stays_inside_its_item():
    html = md2pdf.convert("- first line\n  continues here\n- second\n")
    assert html.count("<li>") == 2
    assert "<li>first line continues here</li>" in html
    assert "<p>continues here</p>" not in html


def test_an_ordered_list_is_not_split_by_its_own_wrapping():
    html = md2pdf.convert("1. one\n   still one\n2. two\n3. three\n")
    assert html.count("<ol>") == 1
    assert html.count("<li>") == 3
    assert "<li>one still one</li>" in html


def test_inline_code_is_escaped_not_executed():
    html = md2pdf.convert("Use `<script>` carefully.\n")
    assert "<code>&lt;script&gt;</code>" in html


@pytest.mark.parametrize("level", [1, 2, 3])
def test_headings_render_at_their_level(level):
    html = md2pdf.convert("#" * level + " Title\n")
    assert f"<h{level}>Title</h{level}>" in html


def test_links_and_bold_survive_together():
    html = md2pdf.convert("See **[the guide](https://x.test/a)** now.\n")
    assert '<a href="https://x.test/a">the guide</a>' in html
    assert "<strong>" in html
