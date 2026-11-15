"""Web search tool backed by DuckDuckGo's public HTML results."""

from abc import ABC, abstractmethod
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from pydantic import BaseModel, Field

from app.tools.base import BaseTool, RiskLevel, ToolResult


class SearchEngineAdapter(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        pass


class _DuckDuckGoResultsParser(HTMLParser):
    """Extracts only title, destination URL, and excerpt from search result cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: List[Dict[str, str]] = []
        self._div_depth = 0
        self._result_depth: Optional[int] = None
        self._current: Optional[Dict[str, str]] = None
        self._capture: Optional[str] = None
        self._capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div":
            self._div_depth += 1
            if "result" in classes:
                self._current = {"title": "", "url": "", "snippet": ""}
                self._result_depth = self._div_depth

        if not self._current or self._capture:
            if self._capture:
                self._capture_depth += 1
            return

        if tag == "a" and "result__a" in classes:
            self._current["url"] = self._destination_url(attributes.get("href") or "")
            self._capture = "title"
            self._capture_depth = 1
        elif tag in ("a", "div", "span") and "result__snippet" in classes:
            self._capture = "snippet"
            self._capture_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture:
            self._capture_depth -= 1
            if self._capture_depth <= 0:
                self._capture = None

        if tag == "div" and self._current and self._result_depth == self._div_depth:
            if self._current["title"].strip() and self._current["url"].startswith(("http://", "https://")):
                self.results.append(
                    {key: value.strip() for key, value in self._current.items()}
                )
            self._current = None
            self._result_depth = None
        if tag == "div":
            self._div_depth = max(0, self._div_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._current and self._capture:
            self._current[self._capture] += data

    @staticmethod
    def _destination_url(href: str) -> str:
        absolute_url = urljoin("https://html.duckduckgo.com", href)
        parsed = urlparse(absolute_url)
        if parsed.path.endswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return unquote(target)
        return absolute_url


class DefaultSearchAdapter(SearchEngineAdapter):
    """Searches the public web and returns actual result excerpts, never canned sources."""

    endpoint = "https://html.duckduckgo.com/html/"

    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        if not query.strip():
            raise ValueError("Search query cannot be empty.")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
            headers={"User-Agent": "ORIGIN-AI-Research/1.0"},
        ) as client:
            response = await client.get(self.endpoint, params={"q": query})
            response.raise_for_status()

        parser = _DuckDuckGoResultsParser()
        parser.feed(response.text)
        results = []
        for result in parser.results:
            snippet = result["snippet"]
            results.append(
                {
                    "title": result["title"],
                    "url": result["url"],
                    "snippet": snippet,
                    "content": snippet,
                    "source": urlparse(result["url"]).netloc,
                }
            )
            if len(results) >= max_results:
                break
        return results


search_engine: SearchEngineAdapter = DefaultSearchAdapter()


class WebSearchInput(BaseModel):
    query: str = Field(description="Search topic or research question")
    max_results: int = Field(default=5, ge=1, le=10, description="Maximum sources to retrieve")


class WebSearchTool(BaseTool):
    tool_id = "web_search"
    name = "Web Research & Search"
    description = "Searches the public web and returns source titles, URLs, and search excerpts."
    input_schema = WebSearchInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 25

    async def run(
        self,
        input_params: WebSearchInput,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        try:
            results = await search_engine.search(input_params.query, input_params.max_results)
            return ToolResult(
                success=True,
                data={"query": input_params.query, "results": results},
                metadata={"total_sources": len(results)},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Web search failed for '{input_params.query}': {exc}")
