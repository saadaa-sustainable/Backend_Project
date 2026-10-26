"""md2pdf.py -- render a repo Markdown doc to a print-quality PDF.

Why a converter here rather than a dependency: the docs use a small,
known subset of Markdown (headings, GFM tables, fenced code, bold,
inline code, links, ordered and bullet lists) and the PDF has to be
right on the first pass, because nobody reads a 30-page PDF to check it.
The defects this is written against, all found by LOOKING at earlier
output rather than by any error:

  * a GFM table rendered an empty `| | |` header stripe when the header
    row was taken for a body row;
  * inline-code backticks were still processed INSIDE a fenced block, so
    a code sample grew <code> chips;
  * a bullet wrapped across two source lines escaped its <li> and became
    a stray paragraph;
  * an ordered list was split in half by a block between its items, and
    restarted numbering at 1.

Each has a test in tests/test_md2pdf.py.

Usage:
    .venv/bin/python scripts/md2pdf.py docs/first-click-guide.md
    .venv/bin/python scripts/md2pdf.py docs/first-click-guide.md --out /tmp/x.pdf
"""
from __future__ import annotations

import argparse
import html
import pathlib
import re
import sys

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #1a1a1a; margin: 0; }
h1 { font-size: 21pt; line-height: 1.25; margin: 0 0 4pt; letter-spacing: -0.01em; }
h2 { font-size: 14pt; margin: 20pt 0 6pt; padding-bottom: 3pt;
     border-bottom: 1px solid #d8d8d8; break-after: avoid; break-inside: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 4pt; break-after: avoid; break-inside: avoid; }
p, ul, ol, table, pre { margin: 0 0 8pt; }
/* A heading must not sit alone at the foot of a page. */
h2 + *, h3 + * { break-before: avoid; }
ul, ol { padding-left: 18pt; }
li { margin: 0 0 3pt; break-inside: avoid; }
li > p { margin: 0; }
code { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
       font-size: 9pt; background: #f2f2f4; padding: 1px 4px; border-radius: 3px; }
pre { background: #f7f7f9; border: 1px solid #e3e3e8; border-radius: 4px;
      padding: 8pt 10pt; overflow-x: auto; break-inside: avoid; }
/* The chip styling must not reappear on every token inside a block. */
pre code { background: none; padding: 0; border-radius: 0; font-size: 8.8pt;
           white-space: pre-wrap; word-break: break-word; }
table { border-collapse: collapse; width: 100%; font-size: 9.2pt;
        break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th, td { border: 1px solid #dcdce2; padding: 4pt 6pt; text-align: left;
         vertical-align: top; }
th { background: #f2f2f4; font-weight: 600; }
blockquote { margin: 0 0 8pt; padding: 4pt 10pt; border-left: 3px solid #c9c9d1;
             background: #fafafc; color: #3a3a3a; }
hr { border: 0; border-top: 1px solid #dcdce2; margin: 14pt 0; }
a { color: #1a4fd6; text-decoration: none; word-break: break-word; }
strong { font-weight: 650; }
"""

_FENCE = re.compile(r"^```+\s*([A-Za-z0-9_+-]*)\s*$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _inline(text: str) -> str:
    """Escape, then apply inline markup. Code spans are protected first so
    their contents never receive bold/link processing."""
    out = html.escape(text, quote=False)
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    out = re.sub(r"`([^`]+)`", stash, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', out)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{spans[int(m.group(1))]}</code>", out)


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def convert(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        # Fenced code -- taken verbatim, no inline processing at all.
        if m := _FENCE.match(line):
            lang = m.group(1)
            i += 1
            body: list[str] = []
            while i < n and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # closing fence
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(body))}</code></pre>")
            continue

        if m := _HEADING.match(line):
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            out.append("<hr>")
            i += 1
            continue

        # GFM table: a header row, a separator row, then body rows. The
        # separator is what identifies it -- without that check the header
        # was emitted as a body row and the table grew a blank stripe.
        if line.lstrip().startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            header = _cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            head = "".join(f"<th>{_inline(c)}</th>" for c in header)
            body = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                for r in rows
            )
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            continue

        if line.lstrip().startswith(">"):
            body = []
            while i < n and lines[i].lstrip().startswith(">"):
                body.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(body))}</blockquote>")
            continue

        # Lists. A continuation line -- any non-blank line that does not
        # start a new item or block -- belongs to the item above it, which
        # is what stops a wrapped bullet escaping its <li>.
        if _BULLET.match(line) or _ORDERED.match(line):
            ordered = bool(_ORDERED.match(line))
            items: list[str] = []
            while i < n:
                cur = lines[i]
                m2 = _ORDERED.match(cur) if ordered else _BULLET.match(cur)
                if m2:
                    items.append(m2.group(2) if ordered else m2.group(1))
                    i += 1
                    continue
                other = _BULLET.match(cur) if ordered else _ORDERED.match(cur)
                if (not cur.strip()) or other or _HEADING.match(cur) \
                   or _FENCE.match(cur) or cur.lstrip().startswith("|"):
                    break
                items[-1] += " " + cur.strip()
                i += 1
            tag = "ol" if ordered else "ul"
            body = "".join(f"<li>{_inline(x)}</li>" for x in items)
            out.append(f"<{tag}>{body}</{tag}>")
            continue

        # Paragraph. The first line is taken UNCONDITIONALLY, which is
        # what guarantees progress: a line starting with '|' that is not
        # a table (no separator row beneath it) matches no branch above,
        # and a loop that only accepts non-'|' lines would collect
        # nothing, never advance i, and hang the converter outright.
        para: list[str] = [lines[i].strip()]
        i += 1
        while i < n and lines[i].strip() and not (
            _HEADING.match(lines[i]) or _FENCE.match(lines[i])
            or _BULLET.match(lines[i]) or _ORDERED.match(lines[i])
            or lines[i].lstrip().startswith(("|", ">"))
        ):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")

    return "\n".join(out)


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="Defaults to the source path with a .pdf suffix.")
    args = ap.parse_args()

    md = args.source.read_text()
    out = args.out or args.source.with_suffix(".pdf")
    title = next((l.lstrip("# ").strip() for l in md.split("\n")
                  if l.startswith("# ")), args.source.stem)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page()
        pg.set_content(page(title, convert(md)), wait_until="load")
        pg.pdf(path=str(out), format="A4", print_background=True,
               margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
               display_header_footer=True,
               header_template="<div></div>",
               footer_template=(
                   '<div style="width:100%;font-size:7.5pt;color:#888;'
                   'padding:0 16mm;font-family:-apple-system,sans-serif;">'
                   f'<span>{html.escape(title)}</span>'
                   '<span style="float:right">'
                   '<span class="pageNumber"></span> / <span class="totalPages"></span>'
                   '</span></div>'))
        browser.close()
    print(f"[OK] {out}  ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
