"""Render a meeting note for the browser. Obsidian syntax (wikilinks, block ids, tasks) is
translated to plain HTML; raw HTML in the note is not allowed through."""

from __future__ import annotations

import re
from urllib.parse import quote

from markdown_it import MarkdownIt

from ..vault import split_frontmatter

_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
_chat_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").disable("image")
)


def chat_to_html(markdown: str, sources: list[dict]) -> str:
    """Render model output safely, allowing only links to verified meeting sources."""
    urls = {
        str(s["number"]): "/meetings/view/?id=" + quote(s["meeting_id"], safe="") for s in sources
    }
    markdown = re.sub(
        r"\[(\d+)\]",
        lambda m: f"[{m[1]}]({urls[m[1]]})" if m[1] in urls else m[0],
        markdown,
    )
    tokens = _chat_md.parse(markdown)
    for token in tokens:
        links = []
        for child in token.children or []:
            if child.type == "link_open":
                allowed = child.attrGet("href") in urls.values()
                links.append(allowed)
                if not allowed:
                    child.tag, child.attrs = "span", {}
            elif child.type == "link_close" and links and not links.pop():
                child.tag = "span"
    return _chat_md.renderer.render(tokens, _chat_md.options, {})


_BLOCK_LINK = re.compile(r"\[\[#\^(t\d+)(?:\\?\|([^\]]+))?\]\]")
# a wikilink becomes bold text; one that is already bold (**[[Name]]**) is not doubled
_ALIASED = re.compile(r"(\*\*)?\[\[([^\]|]+)\\?\|([^\]]+)\]\](\*\*)?")
_WIKILINK = re.compile(r"(\*\*)?\[\[([^\]]+)\]\](\*\*)?")
_TASK = re.compile(r"^(\s*)- \[( |x)\] ", re.MULTILINE)
# a transcript paragraph ending in " ^t12" (must not run across paragraphs)
_BLOCK_ID = re.compile(r"<p>((?:(?!<p>).)*?) \^(t\d+)</p>", re.DOTALL)


def _bold(text: str, before: str | None, after: str | None) -> str:
    if before or after:  # already inside bold markup: keep the asterisks as they are
        return f"{before or ''}{text}{after or ''}"
    return f"**{text}**"


def note_to_html(markdown: str) -> str:
    _meta, body = split_frontmatter(markdown)
    body = _BLOCK_LINK.sub(lambda m: f"[{m.group(2) or m.group(1)}](#{m.group(1)})", body)
    body = _ALIASED.sub(lambda m: _bold(m.group(3), m.group(1), m.group(4)), body)
    body = _WIKILINK.sub(lambda m: _bold(m.group(2), m.group(1), m.group(3)), body)
    body = _TASK.sub(lambda m: f"{m.group(1)}- {'☑' if m.group(2) == 'x' else '☐'} ", body)
    html = _md.render(body)
    return _BLOCK_ID.sub(r'<p id="\2">\1</p>', html)
