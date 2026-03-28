"""Reddit content sourcing — fetch popular posts for video generation.

Uses the public Reddit JSON API (no authentication required).
Rate-limited by Reddit to ~60 req/min per IP.
"""

from __future__ import annotations

import json
import re
from urllib import request as urllib_request

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_]{1,50}$")

# Subreddits known for good short-form storytelling content
RECOMMENDED_SUBS = [
    "todayilearned",
    "tifu",
    "AmItheAsshole",
    "MaliciousCompliance",
    "pettyrevenge",
    "ProRevenge",
    "relationship_advice",
    "Showerthoughts",
    "explainlikeimfive",
    "unpopularopinion",
]


def fetch_reddit_posts(
    subreddit: str = "todayilearned",
    sort: str = "hot",
    limit: int = 10,
    time_filter: str = "day",
) -> list[dict]:
    """Fetch posts from a subreddit using the public JSON API.

    Returns a list of post dicts with: id, title, selftext, score,
    num_comments, subreddit, url, created_utc.
    """
    if not _SAFE_NAME.match(subreddit):
        raise ValueError(f"Invalid subreddit name: {subreddit}")
    if sort not in ("hot", "new", "top", "rising"):
        sort = "hot"
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}&t={time_filter}"
    req = urllib_request.Request(url, headers={"User-Agent": "VideoStudio/1.0"})

    with urllib_request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    posts: list[dict] = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        posts.append({
            "id": post.get("id", ""),
            "title": post.get("title", ""),
            "selftext": post.get("selftext", ""),
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "subreddit": post.get("subreddit", subreddit),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "created_utc": post.get("created_utc", 0),
        })
    return posts


def select_best_post(
    posts: list[dict],
    min_score: int = 100,
    min_text_length: int = 200,
) -> dict | None:
    """Pick the best post for video generation based on engagement and content."""
    candidates = [
        p for p in posts
        if p["score"] >= min_score and len(p["selftext"]) >= min_text_length
    ]
    if not candidates:
        # Relax criteria: just pick highest score with some text
        candidates = [p for p in posts if len(p["selftext"]) > 50]
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p["score"], reverse=True)[0]


def post_to_prompt(post: dict) -> str:
    """Convert a Reddit post into a prompt for the reddit_translation template."""
    title = post["title"]
    body = post["selftext"]
    # Truncate very long posts for LLM context
    if len(body) > 2000:
        body = body[:2000] + "..."
    return f"[Reddit r/{post['subreddit']}] {title}\n\n{body}"
