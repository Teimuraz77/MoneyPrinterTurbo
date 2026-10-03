"""Scrapers: RSS feeds (feedparser) and the NewsData.io free tier (a news *data* API, not generative)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import requests
from loguru import logger

USER_AGENT = "WWNN-ingest/0.1 (+self-hosted weekly news show)"


@dataclass
class RawItem:
    source: str
    url: str
    title: str
    description: str = ""
    published_at: str | None = None
    language: str | None = "en"


def _clean(text: str | None, limit: int = 1200) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def fetch_rss(name: str, url: str, timeout: float = 20.0) -> list[RawItem]:
    import feedparser

    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"rss {name}: {e}")
        return []
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries:
        link, title = e.get("link"), _clean(e.get("title"), 300)
        if not link or not title:
            continue
        items.append(RawItem(source=f"rss:{name}", url=link, title=title,
                             description=_clean(e.get("summary") or e.get("description")),
                             published_at=e.get("published") or e.get("updated")))
    logger.info(f"rss {name}: {len(items)} items")
    return items


def fetch_newsdata(api_key: str, query: str, language: str = "en", timeout: float = 20.0) -> list[RawItem]:
    """NewsData.io ``/api/1/latest``. Free tier: 200 credits/day, 10 articles/credit, 12 h delay."""
    if not api_key:
        return []
    try:
        r = requests.get("https://newsdata.io/api/1/latest",
                         params={"apikey": api_key, "q": query[:100], "language": language},
                         timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"newsdata: {e}")
        return []
    items = []
    for a in data.get("results") or []:
        if not a.get("link") or not a.get("title"):
            continue
        items.append(RawItem(source=f"newsdata:{a.get('source_id', 'unknown')}", url=a["link"],
                             title=_clean(a["title"], 300), description=_clean(a.get("description")),
                             published_at=a.get("pubDate"), language=language))
    logger.info(f"newsdata '{query}': {len(items)} items")
    return items
