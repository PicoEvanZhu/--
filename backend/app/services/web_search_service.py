from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html import unescape
from threading import Lock
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests

_DDG_SEARCH_URL = "https://duckduckgo.com/html/"
_SEARCH_TTL_SECONDS = 15 * 60
_MAX_CACHE_SIZE = 128
_search_cache_lock = Lock()
_search_cache: Dict[str, Dict[str, object]] = {}


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"


def _clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _decode_result_url(url: str) -> Optional[str]:
    candidate = str(url or "").strip()
    if not candidate:
        return None
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"

    parsed = urlparse(candidate)
    query = parse_qs(parsed.query)
    uddg = query.get("uddg")
    if uddg:
        decoded = unquote(uddg[0]).strip()
        if decoded.startswith("http://") or decoded.startswith("https://"):
            return decoded

    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate
    return None


def _parse_duckduckgo_results(html: str, max_results: int) -> List[WebSearchResult]:
    blocks = re.findall(
        r'<div class="result results_links.*?<div class="clear"></div>\s*</div>\s*</div>',
        html,
        flags=re.S,
    )

    results: List[WebSearchResult] = []
    seen_urls = set()
    for block in blocks:
        title_match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
        if not title_match:
            continue
        raw_url, raw_title = title_match.groups()
        decoded_url = _decode_result_url(raw_url)
        if not decoded_url or decoded_url in seen_urls:
            continue

        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, flags=re.S)
        if not snippet_match:
            snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</div>', block, flags=re.S)

        title = _clean_html_text(raw_title)
        snippet = _clean_html_text(snippet_match.group(1) if snippet_match else "")
        if not title:
            continue

        seen_urls.add(decoded_url)
        results.append(WebSearchResult(title=title, url=decoded_url, snippet=snippet))
        if len(results) >= max_results:
            break

    return results


def search_web(query: str, max_results: int = 5, timeout: float = 10.0) -> List[WebSearchResult]:
    normalized_query = re.sub(r"\s+", " ", str(query or "")).strip()
    if not normalized_query:
        return []

    now = time.time()
    with _search_cache_lock:
        cached = _search_cache.get(normalized_query)
        if cached and float(cached.get("expires_at") or 0) > now:
            cached_results = cached.get("results") or []
            return [item for item in cached_results if isinstance(item, WebSearchResult)]

    response = requests.get(
        _DDG_SEARCH_URL,
        params={"q": normalized_query, "kl": "cn-zh"},
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://duckduckgo.com/"},
        timeout=timeout,
    )
    response.raise_for_status()
    results = _parse_duckduckgo_results(response.text, max_results=max_results)

    with _search_cache_lock:
        _search_cache[normalized_query] = {
            "expires_at": now + _SEARCH_TTL_SECONDS,
            "results": results,
        }
        if len(_search_cache) > _MAX_CACHE_SIZE:
            oldest_key = next(iter(_search_cache.keys()), None)
            if oldest_key is not None:
                _search_cache.pop(oldest_key, None)

    return results
