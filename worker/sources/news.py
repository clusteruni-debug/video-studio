"""News content sourcing — fetch headlines for video generation.

Supports the free NewsAPI.org tier (100 requests/day) and a simple
RSS fallback for Korean news.
"""

from __future__ import annotations

import json
import os
from urllib import request as urllib_request

def _get_newsapi_key() -> str:
    return os.environ.get("NEWSAPI_KEY", "")


def fetch_news_headlines(
    query: str = "",
    country: str = "kr",
    category: str = "general",
    page_size: int = 10,
) -> list[dict]:
    """Fetch top headlines from NewsAPI.

    Returns a list of dicts with: title, description, source, url, published_at.
    Requires ``NEWSAPI_KEY`` environment variable.
    """
    api_key = _get_newsapi_key()
    if not api_key:
        raise RuntimeError("NEWSAPI_KEY environment variable is not set")

    params = f"country={country}&category={category}&pageSize={page_size}"
    if query:
        params += f"&q={query}"
    url = f"https://newsapi.org/v2/top-headlines?{params}"

    req = urllib_request.Request(
        url,
        headers={
            "X-Api-Key": api_key,
            "User-Agent": "VideoStudio/1.0",
        },
    )

    with urllib_request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    articles: list[dict] = []
    for article in data.get("articles", []):
        articles.append({
            "title": article.get("title", ""),
            "description": article.get("description", ""),
            "source": article.get("source", {}).get("name", ""),
            "url": article.get("url", ""),
            "published_at": article.get("publishedAt", ""),
            "image_url": article.get("urlToImage", ""),
        })
    return articles


def headline_to_prompt(article: dict) -> str:
    """Convert a news article into a prompt for the news_explainer template."""
    title = article["title"]
    desc = article.get("description", "") or ""
    source = article.get("source", "")
    return f"[{source}] {title}\n\n{desc}"
