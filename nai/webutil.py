# -*- coding: utf-8 -*-
"""NAI web utilities: text search + page fetch (no browser, stdlib only).

Adds two tools the model / batch engine can call:
  web_search(query, n) -> top results as plain text (title + url + snippet)
  web_fetch(url)       -> readable page text (tags stripped)

Works over plain HTTP with a normal User-Agent; timeout-bounded. Fails with a
ToolError instead of hanging. Used by tools.web_search / tools.web_fetch and by
batch_search (which fans out several queries in parallel threads).
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 NAI/1.0"
TIMEOUT = 12
MAX_PAGE = 24000


class ToolError(Exception):
    pass


def _http_get(url: str, timeout: int = TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        charset = r.headers.get_content_charset() or "utf-8"
        try:
            return data.decode(charset, "replace")
        except (LookupError, ValueError):
            return data.decode("utf-8", "replace")


class _TextExtract(HTMLParser):
    """Strip tags/scripts/style, keep readable text with paragraph breaks."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.skip += 1
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def extract_text(html: str) -> str:
    p = _TextExtract()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    t = "".join(p.parts)
    t = re.sub(r"\n{2,}", "\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    try:
        from html import unescape
        s = unescape(s)
    except Exception:
        pass
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _resolve_ddg(href: str) -> str:
    # duckduckgo lite wraps real urls as /l/?uddg=<url> — decode them.
    if "uddg=" in href:
        try:
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                return urllib.parse.unquote(m.group(1))
        except Exception:
            pass
    return href


def web_search(query: str, n: str = "6"):
    try:
        n = max(1, min(int(n), 10))
    except (TypeError, ValueError):
        n = 6
    q = urllib.parse.urlencode({"q": query})
    url = f"https://html.duckduckgo.com/html/?{q}"
    try:
        html = _http_get(url)
    except Exception as e:
        raise ToolError(f"web search failed: {e}")
    titles = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    out = []
    for i, (href, title) in enumerate(titles[:n]):
        title = _clean(title)
        snip = _clean(snips[i]) if i < len(snips) else ""
        out.append(f"{i + 1}. {title}\n   url: {_resolve_ddg(href)}\n   {snip}")
    if not out:
        return f"(no web results for {query!r})"
    return "\n\n".join(out)


def web_fetch(url: str):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html = _http_get(url)
    except Exception as e:
        raise ToolError(f"web fetch failed: {e}")
    text = extract_text(html)
    if len(text) > MAX_PAGE:
        text = text[:MAX_PAGE] + "\n...(page too large, truncated)"
    return text or "(page returned no readable text)"
