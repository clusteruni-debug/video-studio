"""Text translation via LLM — leverages existing Gemini / Groq connections.

Translates text between languages using whichever LLM provider is available,
following the same preference chain as the scene-script generator.
"""

from __future__ import annotations

import json
import os
from urllib import request as urllib_request

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")


def translate_text(
    text: str,
    source_lang: str = "en",
    target_lang: str = "ko",
    style: str = "natural",
) -> str:
    """Translate *text* from *source_lang* to *target_lang*.

    *style* can be ``"natural"`` (default — fluent), ``"literal"``
    (word-for-word), or ``"commentary"`` (adds cultural context).
    """
    style_hint = {
        "natural": "Translate naturally and fluently.",
        "literal": "Translate as literally as possible while keeping grammar correct.",
        "commentary": "Translate naturally. Where cultural context is needed, add a brief note in parentheses.",
    }.get(style, "Translate naturally and fluently.")

    prompt = (
        f"Translate the following {source_lang} text to {target_lang}.\n"
        f"Style: {style_hint}\n"
        f"Return ONLY the translation, no explanation.\n\n"
        f"Text:\n{text}\n\n"
        f"Translation:"
    )

    # Try Groq first (faster), then Gemini
    result = _call_groq(prompt) if GROQ_API_KEY else None
    if not result:
        result = _call_gemini(prompt) if GEMINI_API_KEY else None
    if not result:
        raise RuntimeError("No LLM provider available for translation (set GROQ_API_KEY or GEMINI_API_KEY)")
    return result.strip()


def translate_segments(
    segments: list[dict],
    source_lang: str = "en",
    target_lang: str = "ko",
    style: str = "natural",
) -> list[dict]:
    """Translate a list of segments in a single LLM call (batch).

    Falls back to per-segment translation if batch parsing fails.
    Returns new dicts with ``original`` and ``translated`` keys added.
    """
    if not segments:
        return []

    # Try batch translation first (1 API call instead of N)
    batch_result = _translate_batch(segments, source_lang, target_lang, style)
    if batch_result and len(batch_result) == len(segments):
        results = []
        for seg, translated in zip(segments, batch_result):
            results.append({**seg, "original": seg["text"], "translated": translated})
        return results

    # Fallback: per-segment translation
    results = []
    for seg in segments:
        translated = translate_text(seg["text"], source_lang, target_lang, style)
        results.append({**seg, "original": seg["text"], "translated": translated})
    return results


def _translate_batch(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    style: str,
) -> list[str] | None:
    """Translate all segments in a single LLM call.  Returns list of
    translated strings or ``None`` on failure."""
    style_hint = {
        "natural": "Translate naturally and fluently.",
        "literal": "Translate as literally as possible while keeping grammar correct.",
        "commentary": "Translate naturally. Add brief cultural notes in parentheses where needed.",
    }.get(style, "Translate naturally and fluently.")

    numbered = "\n".join(f"[{i+1}] {seg['text']}" for i, seg in enumerate(segments))
    prompt = (
        f"Translate all numbered lines from {source_lang} to {target_lang}.\n"
        f"Style: {style_hint}\n"
        f"Return ONLY the translations, one per line, keeping the [N] numbering.\n\n"
        f"{numbered}"
    )

    raw = (_call_groq(prompt) if GROQ_API_KEY else None) or (_call_gemini(prompt) if GEMINI_API_KEY else None)
    if not raw:
        return None

    # Parse numbered lines back
    import re
    lines = raw.strip().split("\n")
    translations: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Strip [N] prefix
        cleaned = re.sub(r"^\[\d+\]\s*", "", line)
        if cleaned:
            translations.append(cleaned)

    return translations if len(translations) == len(segments) else None


def _call_groq(prompt: str) -> str | None:
    payload = json.dumps({
        "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode("utf-8")
    req = urllib_request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "VideoStudio/1.0",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[groq/translate] {type(e).__name__}: {e}")
        return None


def _call_gemini(prompt: str) -> str | None:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096},
    }).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "VideoStudio/1.0"},
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[gemini/translate] {type(e).__name__}")
        return None
