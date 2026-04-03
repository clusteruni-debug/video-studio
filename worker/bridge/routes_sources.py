"""Content sourcing routes — Reddit posts, news headlines, auto-generation.

Extracted from server.py to keep the main bridge under the 660-line limit.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request as flask_request

sources_bp = Blueprint("sources", __name__)

# Set by server.py at registration time
_execute_draft_fn = None


def init_source_routes(execute_draft_fn):
    global _execute_draft_fn
    _execute_draft_fn = execute_draft_fn


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------

@sources_bp.route("/api/sources/reddit", methods=["GET"])
def reddit_posts_route():
    """Fetch popular Reddit posts from a subreddit."""
    subreddit = flask_request.args.get("subreddit", "todayilearned")
    sort = flask_request.args.get("sort", "hot")
    try:
        limit = min(int(flask_request.args.get("limit", "10")), 25)
    except (ValueError, TypeError):
        limit = 10
    try:
        from worker.sources.reddit import fetch_reddit_posts
        posts = fetch_reddit_posts(subreddit, sort=sort, limit=limit)
        return jsonify({"ok": True, "posts": posts})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@sources_bp.route("/api/sources/reddit/auto", methods=["POST"])
def reddit_auto_generate_route():
    """Auto-select best Reddit post and generate a draft using reddit_translation."""
    data = flask_request.get_json(silent=True) or {}
    subreddit = data.get("subreddit", "todayilearned")
    try:
        from worker.sources.reddit import fetch_reddit_posts, select_best_post, post_to_prompt
        posts = fetch_reddit_posts(subreddit, limit=15)
        best = select_best_post(posts)
        if not best:
            return jsonify({"ok": False, "error": "No suitable posts found"}), 404

        prompt = post_to_prompt(best)
        result = _execute_draft_fn({
            "prompt": prompt,
            "lang": data.get("lang", "ko"),
            "tts_provider": data.get("tts_provider", "edge"),
            "voice_gender": data.get("voice_gender", "female"),
            "template_type": "reddit_translation",
            "tone": data.get("tone", "casual_heyo"),
            "subtitle_style": data.get("subtitle_style", ""),
            "target_duration": data.get("target_duration", "30s"),
            "custom_instruction": data.get("custom_instruction", ""),
        })
        if not result.get("ok"):
            return jsonify(result), 500

        result["source_post"] = {
            "title": best["title"],
            "subreddit": best["subreddit"],
            "score": best["score"],
            "url": best["url"],
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

@sources_bp.route("/api/sources/news", methods=["GET"])
def news_headlines_route():
    """Fetch news headlines (requires NEWSAPI_KEY)."""
    query = flask_request.args.get("q", "")
    country = flask_request.args.get("country", "kr")
    category = flask_request.args.get("category", "general")
    try:
        from worker.sources.news import fetch_news_headlines
        articles = fetch_news_headlines(query=query, country=country, category=category)
        return jsonify({"ok": True, "articles": articles})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@sources_bp.route("/api/sources/news/auto", methods=["POST"])
def news_auto_generate_route():
    """Auto-select top news headline and generate a draft using news_explainer."""
    data = flask_request.get_json(silent=True) or {}
    query = data.get("q", "")
    country = data.get("country", "kr")
    category = data.get("category", "general")
    try:
        from worker.sources.news import fetch_news_headlines, headline_to_prompt
        articles = fetch_news_headlines(query=query, country=country, category=category, page_size=5)
        if not articles:
            return jsonify({"ok": False, "error": "No headlines found"}), 404

        best = articles[0]
        prompt = headline_to_prompt(best)
        result = _execute_draft_fn({
            "prompt": prompt,
            "lang": data.get("lang", "ko"),
            "tts_provider": data.get("tts_provider", "edge"),
            "voice_gender": data.get("voice_gender", "female"),
            "template_type": "news_explainer",
            "tone": data.get("tone", "casual_heyo"),
            "subtitle_style": data.get("subtitle_style", ""),
            "target_duration": data.get("target_duration", "30s"),
            "custom_instruction": data.get("custom_instruction", ""),
        })
        if not result.get("ok"):
            return jsonify(result), 500

        result["source_article"] = {
            "title": best["title"],
            "source": best["source"],
            "url": best["url"],
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
