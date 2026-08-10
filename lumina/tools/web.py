"""Read-only web tools: search and page fetching (no approval required)."""

from __future__ import annotations

import html
import re

import httpx

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult


class WebTools:
    """web_search + web_fetch using DuckDuckGo's HTML endpoint (no API key)."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._client: httpx.AsyncClient | None = None
        self._setup()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=8.0),
                headers={"User-Agent": "Mozilla/5.0 (compatible; LuminaCode/1.0)"},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _setup(self) -> None:

        @self.registry.register(
            description="Search the web and return top result titles, URLs and snippets. "
            "Use for looking up docs, error messages and solutions.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (1-10)"},
                },
                "required": ["query"],
            },
        )
        async def web_search(query: str, max_results: int = 5) -> ToolResult:
            try:
                resp = await self._get_client().get(
                    "https://html.duckduckgo.com/html/", params={"q": query}
                )
                resp.raise_for_status()
                body = resp.text
                titles = re.findall(
                    r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', body, re.DOTALL
                )
                snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL)
                out: list[str] = []
                for i, (href, raw_title) in enumerate(titles[: max(1, min(max_results, 10))]):
                    title = _strip_tags(raw_title)
                    snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
                    out.append(f"{i + 1}. {title}\n   {html.unescape(href)}\n   {snippet}")
                return ToolResult(
                    tool_call_id="",
                    name="web_search",
                    content="\n\n".join(out) or "(no results)",
                )
            except httpx.HTTPError as exc:
                return ToolResult(
                    tool_call_id="", name="web_search", content=f"web_search failed: {exc}", is_error=True
                )

        @self.registry.register(
            description="Fetch a web page and return its visible text (scripts/styles stripped).",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL to fetch"},
                    "max_chars": {"type": "integer", "description": "Max chars returned"},
                },
                "required": ["url"],
            },
        )
        async def web_fetch(url: str, max_chars: int = 6000) -> ToolResult:
            if not url.startswith(("http://", "https://")):
                return ToolResult(
                    tool_call_id="",
                    name="web_fetch",
                    content="URL must start with http:// or https://",
                    is_error=True,
                )
            try:
                resp = await self._get_client().get(url)
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                if "html" in ctype.lower():
                    body = resp.text
                    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.DOTALL)
                    title = _strip_tags(m.group(1)) if m else ""
                    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", body)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    content = f"Title: {title}\n\n{text}" if title else text
                else:
                    content = resp.text
                truncated = len(content) > max_chars
                return ToolResult(
                    tool_call_id="",
                    name="web_fetch",
                    content=content[:max_chars] + ("…" if truncated else ""),
                )
            except httpx.HTTPError as exc:
                return ToolResult(
                    tool_call_id="", name="web_fetch", content=f"web_fetch failed: {exc}", is_error=True
                )


def _strip_tags(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()
