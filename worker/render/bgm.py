"""BGM auto-matching and audio mixing with sidechain ducking.

Spec reference: docs/RENDERING-SPEC.md §4
"""

from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path

BGM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

# RENDERING-SPEC §4.1 — emotion → BGM mood mapping
EMOTION_MOOD_MAP: dict[str, str] = {
    "neutral": "calm",
    "shock": "tense",
    "surprise": "tense",
    "funny": "upbeat",
    "humor": "upbeat",
    "serious": "cinematic",
    "sad": "cinematic",
    "excitement": "upbeat",
}

# All valid mood subdirectories.
# `energetic` and `tech-house` are local-library aliases used for Shorts beds.
VALID_MOODS = {"calm", "tense", "upbeat", "cinematic", "energetic", "tech-house"}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

FREE_AUDIO_CANDIDATES: tuple[dict[str, object], ...] = (
    {
        "id": "mixkit-serene-view-arulo",
        "provider": "mixkit",
        "kind": "bgm",
        "title": "Serene View",
        "artist": "Arulo",
        "sourceUrl": "https://mixkit.co/free-stock-music/mood/calm/",
        "sourceLicense": "Mixkit Stock Music Free License; verify item page at download time.",
        "licenseUrl": "https://mixkit.co/license/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "calm",
        "templateFamilies": ["authentic_vlog", "tutorial_steps", "podcast_clip"],
        "durationSec": 114,
        "editNotes": "Use as a low bed under narration; duck aggressively and fade before hard cuts.",
        "riskLevel": "low",
        "riskNote": "Mixkit has separate item-type licenses; confirm Stock Music Free License on the download page.",
    },
    {
        "id": "mixkit-driving-ambition-ahjay-stelino",
        "provider": "mixkit",
        "kind": "bgm",
        "title": "Driving Ambition",
        "artist": "Ahjay Stelino",
        "sourceUrl": "https://mixkit.co/free-stock-music/mood/uplifting/",
        "sourceLicense": "Mixkit Stock Music Free License; verify item page at download time.",
        "licenseUrl": "https://mixkit.co/license/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "upbeat",
        "templateFamilies": ["ranking_list", "live_recap", "news_explainer"],
        "durationSec": 102,
        "editNotes": "Trim to the first clear beat for Shorts; cut rank/list transitions on 4/8-beat boundaries.",
        "riskLevel": "low",
        "riskNote": "Use only after confirming the exact item is stock music under the Mixkit Free License.",
    },
    {
        "id": "mixkit-silent-descent-eugenio-mininni",
        "provider": "mixkit",
        "kind": "bgm",
        "title": "Silent Descent",
        "artist": "Eugenio Mininni",
        "sourceUrl": "https://mixkit.co/free-stock-music/mood/melancholic/",
        "sourceLicense": "Mixkit Stock Music Free License; verify item page at download time.",
        "licenseUrl": "https://mixkit.co/license/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "cinematic",
        "templateFamilies": ["longform_deep_dive", "interview_documentary", "persona_story"],
        "durationSec": 160,
        "editNotes": "Use as a chapter bed; avoid loud sections under TTS and fade between chapters.",
        "riskLevel": "low",
        "riskNote": "Melancholic/cinematic tone can overpower short narration; keep voice-first mix.",
    },
    {
        "id": "mixkit-gimme-that-groove-michael-ramir",
        "provider": "mixkit",
        "kind": "bgm",
        "title": "Gimme that Groove!",
        "artist": "Michael Ramir C.",
        "sourceUrl": "https://mixkit.co/free-stock-music/mood/insistent/",
        "sourceLicense": "Mixkit Stock Music Free License; verify item page at download time.",
        "licenseUrl": "https://mixkit.co/license/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "upbeat",
        "templateFamilies": ["ranking_list", "kculture_fandom", "live_recap"],
        "durationSec": 88,
        "editNotes": "Use for fast list or event recaps; keep SFX sparse so the beat is not chaotic.",
        "riskLevel": "low",
        "riskNote": "Route through upbeat unless an energetic mood is explicitly supported by the renderer.",
    },
    {
        "id": "pixabay-documentary-background-the-mountain",
        "provider": "pixabay-audio",
        "kind": "bgm",
        "title": "Documentary Background",
        "artist": "The_Mountain",
        "sourceUrl": "https://pixabay.com/music/modern-classical-documentary-background-158070/",
        "sourceLicense": "Pixabay Content License; attribution not required; no standalone redistribution.",
        "licenseUrl": "https://pixabay.com/service/license-summary/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "cinematic",
        "templateFamilies": ["longform_deep_dive", "news_explainer", "interview_documentary"],
        "durationSec": 118,
        "editNotes": "Use as a documentary bed; loop only with crossfades and keep narration dominant.",
        "riskLevel": "medium",
        "riskNote": "Pixabay music can be legally usable but still Content ID flagged; retain download proof.",
    },
    {
        "id": "pixabay-lofi-chill-delosound",
        "provider": "pixabay-audio",
        "kind": "bgm",
        "title": "Lofi - Lofi Chill",
        "artist": "DELOSound",
        "sourceUrl": "https://pixabay.com/music/beats-lofi-lofi-chill-lofi-girl-438671/",
        "sourceLicense": "Pixabay Content License; attribution not required; no standalone redistribution.",
        "licenseUrl": "https://pixabay.com/service/license-summary/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "calm",
        "templateFamilies": ["authentic_vlog", "tutorial_steps", "podcast_clip"],
        "durationSec": 197,
        "editNotes": "Use for quiet vlog/tutorial beds; trim for Shorts and avoid brand-like wording in labels.",
        "riskLevel": "medium",
        "riskNote": "Original page title contains brand-like wording; do not imply affiliation and retain proof.",
    },
    {
        "id": "freesound-cafe-ambience-seoul-naotokui",
        "provider": "freesound",
        "kind": "ambience",
        "title": "Cafe ambience in Seoul",
        "artist": "naotokui",
        "sourceUrl": "https://freesound.org/people/naotokui/sounds/770433/",
        "sourceLicense": "Creative Commons 0 1.0",
        "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "calm",
        "templateFamilies": ["authentic_vlog", "interview_documentary", "live_recap"],
        "durationSec": 3398,
        "editNotes": "Extract 20-90 second room-tone loops; high-pass or lower gain if it muddies TTS.",
        "riskLevel": "low",
        "riskNote": "Prefer CC0 Freesound assets; still keep page proof because uploads are user-provided.",
    },
    {
        "id": "freesound-swooshes-susssounds",
        "provider": "freesound",
        "kind": "sfx-pack",
        "title": "Swooshes, whoosh, short, deep",
        "artist": "susssounds",
        "sourceUrl": "https://freesound.org/people/susssounds/sounds/752068/",
        "sourceLicense": "Creative Commons 0 1.0",
        "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "upbeat",
        "templateFamilies": ["ranking_list", "tutorial_steps", "kculture_fandom", "live_recap"],
        "durationSec": 55,
        "editNotes": "Slice individual whooshes for transitions; do not use as a bed loop.",
        "riskLevel": "low",
        "riskNote": "Normalize below narration; overusing whooshes makes Shorts feel templated.",
    },
    {
        "id": "wikimedia-cafe-ambiance-marble-toast",
        "provider": "wikimedia-commons",
        "kind": "ambience",
        "title": "Cafe ambiance.ogg",
        "artist": "Marble Toast",
        "sourceUrl": "https://commons.wikimedia.org/wiki/File:Cafe_ambiance.ogg",
        "sourceLicense": "Creative Commons 0 1.0",
        "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attributionRequired": False,
        "attribution": "",
        "mood": "calm",
        "templateFamilies": ["authentic_vlog", "podcast_clip", "interview_documentary"],
        "durationSec": 1200,
        "editNotes": "Trim to 30-120 seconds and fade around speech; useful for cafe/interview texture.",
        "riskLevel": "low",
        "riskNote": "Confirm the file page license before production because Commons files vary by item.",
    },
    {
        "id": "wikimedia-forest-ambience-nille",
        "provider": "wikimedia-commons",
        "kind": "ambience",
        "title": "forest ambience",
        "artist": "nille",
        "sourceUrl": "https://commons.wikimedia.org/wiki/File:20090610_0_ambience.ogg",
        "sourceLicense": "Public domain",
        "licenseUrl": "https://commons.wikimedia.org/wiki/File:20090610_0_ambience.ogg",
        "attributionRequired": False,
        "attribution": "",
        "mood": "calm",
        "templateFamilies": ["longform_deep_dive", "interview_documentary", "persona_story"],
        "durationSec": 123,
        "editNotes": "Use for reflective or documentary segments; keep very low under narration.",
        "riskLevel": "low",
        "riskNote": "Confirm the exact file page before production and keep a screenshot/export proof.",
    },
    {
        "id": "fma-circuit-1000-handz",
        "provider": "free-music-archive",
        "kind": "bgm",
        "title": "Circuit",
        "artist": "1000 Handz",
        "sourceUrl": "https://freemusicarchive.org/music/1000-handz/cc-by-free-to-use-melodic-rap-instrumentals/circuit-2/",
        "sourceLicense": "Creative Commons Attribution 4.0 International",
        "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "attributionRequired": True,
        "attribution": "Circuit by 1000 Handz, licensed under CC BY 4.0.",
        "mood": "upbeat",
        "templateFamilies": ["ranking_list", "persona_story", "live_recap"],
        "durationSec": 150,
        "editNotes": "Trim to a clean hook loop; paste attribution into the YouTube description.",
        "riskLevel": "medium",
        "riskNote": "Attribution is mandatory; avoid FMA tracks marked NC or ND for monetized/editing use.",
    },
    {
        "id": "fma-only-instrumental-broke-for-free",
        "provider": "free-music-archive",
        "kind": "bgm",
        "title": "Only Instrumental",
        "artist": "Broke For Free",
        "sourceUrl": "https://freemusicarchive.org/music/Broke_For_Free/Directionless_EP/Broke_For_Free_-_Directionless_EP_-_06_Only_Instrumental",
        "sourceLicense": "Creative Commons Attribution license; verify exact FMA track page before download.",
        "licenseUrl": "https://freemusicarchive.org/index.php/License_Guide",
        "attributionRequired": True,
        "attribution": "Only Instrumental by Broke For Free; include the exact license and FMA track link.",
        "mood": "calm",
        "templateFamilies": ["authentic_vlog", "tutorial_steps", "podcast_clip"],
        "durationSec": 158,
        "editNotes": "Use as a soft bed and duck under voice; keep attribution with final packet metadata.",
        "riskLevel": "medium",
        "riskNote": "FMA licenses vary by track; verify no NC/ND restriction on the exact page.",
    },
    {
        "id": "youtube-audio-library-attribution-not-required",
        "provider": "youtube-audio-library",
        "kind": "bgm-or-sfx",
        "title": "Operator-selected Audio Library track",
        "artist": "YouTube Audio Library",
        "sourceUrl": "https://www.youtube.com/audiolibrary",
        "sourceLicense": "YouTube Audio Library standard license; use Attribution not required filter where possible.",
        "licenseUrl": "https://support.google.com/youtube/answer/3376882",
        "attributionRequired": False,
        "attribution": "",
        "mood": "upbeat",
        "templateFamilies": ["news_explainer", "ranking_list", "kculture_fandom", "live_recap", "longform_deep_dive"],
        "durationSec": None,
        "editNotes": "Pick a track in Studio, copy license details, and store the exact title/artist/download date.",
        "riskLevel": "low",
        "riskNote": "This is a source workflow, not a preselected track; replace title/artist after download.",
        "requiresOperatorSelection": True,
    },
    {
        "id": "gongu-copyright-korean-music-source",
        "provider": "gongu-copyright",
        "kind": "bgm-source",
        "title": "Operator-selected Gongu/Copyright Korea music",
        "artist": "Korea Copyright Commission / listed creator",
        "sourceUrl": "https://gongu.copyright.or.kr/gongu/main/contents.do?menuNo=200093",
        "sourceLicense": "Gongu/Copyright Korea CCL work; replace with the exact item license and avoid NC/ND for monetized edited videos.",
        "licenseUrl": "https://gongu.copyright.or.kr/gongu/main/contents.do?menuNo=200093",
        "attributionRequired": True,
        "attribution": "Replace with exact Gongu title, creator, source URL, and CCL condition from the item page.",
        "mood": "cinematic",
        "templateFamilies": ["kculture_fandom", "longform_deep_dive", "interview_documentary", "persona_story"],
        "durationSec": None,
        "editNotes": "Use Korean public/shared music as a voice-first bed only after checking the exact CCL terms.",
        "riskLevel": "medium",
        "riskNote": "CCL conditions vary by item; do not use NC for monetized YouTube or ND when the edit transforms the work.",
        "requiresOperatorSelection": True,
    },
    {
        "id": "gongu-copyright-korean-sfx-source",
        "provider": "gongu-copyright",
        "kind": "sfx-source",
        "title": "Operator-selected Gongu/Copyright Korea SFX",
        "artist": "Korea Copyright Commission / listed creator",
        "sourceUrl": "https://gongu.copyright.or.kr/gongu/main/contents.do?menuNo=200093",
        "sourceLicense": "Gongu/Copyright Korea CCL work; replace with the exact item license and avoid NC/ND for monetized edited videos.",
        "licenseUrl": "https://gongu.copyright.or.kr/gongu/main/contents.do?menuNo=200093",
        "attributionRequired": True,
        "attribution": "Replace with exact Gongu title, creator, source URL, and CCL condition from the item page.",
        "mood": "upbeat",
        "templateFamilies": ["ranking_list", "tutorial_steps", "kculture_fandom", "live_recap"],
        "durationSec": None,
        "editNotes": "Use Korean UI clicks, chimes, ambience, or transition accents sparingly; slice short and keep under narration.",
        "riskLevel": "medium",
        "riskNote": "CCL conditions vary by item; retain source proof and avoid protected music hooks as SFX.",
        "requiresOperatorSelection": True,
    },
    {
        "id": "kogl-type1-public-audio-source",
        "provider": "kogl",
        "kind": "public-audio-source",
        "title": "Operator-selected KOGL Type 1 public audio/media",
        "artist": "Public institution / listed creator",
        "sourceUrl": "https://www.mcst.go.kr/kor/s_open/kogl/koglType.jsp",
        "sourceLicense": "KOGL Type 1 attribution; Type 2-4 add restrictions. Replace with the exact public work type before import.",
        "licenseUrl": "https://www.mcst.go.kr/kor/s_open/kogl/koglType.jsp",
        "attributionRequired": True,
        "attribution": "Replace with institution, work title, KOGL type, year, and source URL from the item page.",
        "mood": "calm",
        "templateFamilies": ["news_explainer", "kculture_fandom", "longform_deep_dive", "interview_documentary", "live_recap"],
        "durationSec": None,
        "editNotes": "Use KOGL public sounds/music/video as evidence or texture; prefer Type 1 for commercial edited YouTube output.",
        "riskLevel": "medium",
        "riskNote": "KOGL Type 2 forbids commercial use and Type 3/4 forbid derivatives; use Type 1 or expired public works for edited monetized videos.",
        "requiresOperatorSelection": True,
    },
)


def _tag_matches(values: object, target: str | None) -> bool:
    if not target:
        return True
    normalized = target.strip().lower().replace("-", "_")
    if isinstance(values, str):
        return values.strip().lower().replace("-", "_") == normalized
    if isinstance(values, (list, tuple, set)):
        return normalized in {str(item).strip().lower().replace("-", "_") for item in values}
    return False


def _candidate_rank(candidate: dict[str, object], mood: str | None, template_type: str | None) -> tuple[int, str]:
    score = 0
    if _tag_matches(candidate.get("templateFamilies"), template_type):
        score -= 20
    if _tag_matches(candidate.get("mood"), mood):
        score -= 10
    if candidate.get("riskLevel") == "low":
        score -= 3
    if candidate.get("requiresOperatorSelection"):
        score += 2
    return score, str(candidate.get("id") or "")


def free_audio_candidates(
    *,
    mood: str | None = None,
    template_type: str | None = None,
    kind: str | None = None,
    include_risky: bool = True,
    fallback_moods: list[str] | tuple[str, ...] | None = None,
    allow_template_fallback: bool = True,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Return zero-paid BGM/SFX/ambience candidates with source metadata.

    The catalog is intentionally source-first: it does not download assets or
    call any paid API. Operators still verify the exact asset page at download
    time, then persist the returned sidecar shape beside the local file.
    """
    def collect(mood_filter: str | None, template_filter: str | None, match_reason: str) -> list[dict[str, object]]:
        collected: list[dict[str, object]] = []
        for item in FREE_AUDIO_CANDIDATES:
            if mood_filter and not _tag_matches(item.get("mood"), mood_filter):
                continue
            if template_filter and not _tag_matches(item.get("templateFamilies"), template_filter):
                continue
            if kind and not _tag_matches(item.get("kind"), kind):
                continue
            if not include_risky and item.get("riskLevel") not in {"low", None}:
                continue
            payload = dict(item)
            payload["matchReason"] = match_reason
            if mood_filter and mood_filter != mood:
                payload["matchedMood"] = mood_filter
            collected.append(payload)
        collected.sort(key=lambda candidate: _candidate_rank(candidate, mood_filter or mood, template_type))
        return collected

    search_passes: list[tuple[str | None, str | None, str]] = [(mood, template_type, "exact")]
    seen_moods = {str(mood or "").strip().lower()}
    for fallback_mood in fallback_moods or ():
        normalized = str(fallback_mood or "").strip()
        if not normalized or normalized.lower() in seen_moods:
            continue
        seen_moods.add(normalized.lower())
        search_passes.append((normalized, template_type, "fallback-mood"))
    if allow_template_fallback and template_type:
        search_passes.append((None, template_type, "template-fallback"))

    candidates: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for mood_filter, template_filter, match_reason in search_passes:
        for candidate in collect(mood_filter, template_filter, match_reason):
            candidate_id = str(candidate.get("id") or "")
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            candidates.append(candidate)
            if limit is not None and len(candidates) >= max(0, int(limit)):
                break
        if limit is not None and len(candidates) >= max(0, int(limit)):
            break

    if limit is not None:
        return candidates[: max(0, int(limit))]
    return candidates


def free_audio_sidecar_template(candidate_id: str) -> dict[str, object] | None:
    """Build the metadata shape expected next to a downloaded BGM/SFX file."""
    candidate = next((item for item in FREE_AUDIO_CANDIDATES if item.get("id") == candidate_id), None)
    if not candidate:
        return None
    return {
        "provider": candidate.get("provider"),
        "title": candidate.get("title"),
        "artist": candidate.get("artist"),
        "sourceUrl": candidate.get("sourceUrl"),
        "sourceLicense": candidate.get("sourceLicense"),
        "licenseUrl": candidate.get("licenseUrl"),
        "attributionRequired": candidate.get("attributionRequired"),
        "attribution": candidate.get("attribution"),
        "mood": candidate.get("mood"),
        "kind": candidate.get("kind"),
        "durationSec": candidate.get("durationSec"),
        "templateFamilies": list(candidate.get("templateFamilies") or []),
        "downloadDate": "",
        "editNotes": candidate.get("editNotes"),
        "riskNote": candidate.get("riskNote"),
    }


def select_bgm(emotion: str, project_root: Path | str = ".") -> str | None:
    """Select a BGM track based on scene emotion.

    Parameters
    ----------
    emotion:
        Scene emotion string (e.g., "neutral", "shock", "funny").
    project_root:
        Project root directory containing assets/bgm/.

    Returns
    -------
    Path to the selected BGM track, or None if no tracks available.
    """
    root = Path(project_root)
    bgm_dir = root / "assets" / "bgm"
    if not bgm_dir.is_dir():
        return None

    # Map emotion to mood
    mood = EMOTION_MOOD_MAP.get(emotion.lower(), "calm")

    # Try mood-specific folder first
    mood_dir = bgm_dir / mood
    if mood_dir.is_dir():
        tracks = [f for f in mood_dir.iterdir() if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
        if tracks:
            return str(random.choice(tracks))

    # Fallback: any track from any mood folder
    all_tracks = [
        f for f in bgm_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS
    ]
    if all_tracks:
        return str(random.choice(all_tracks))

    return None


def mix_audio(
    narration_path: str,
    bgm_path: str,
    output_path: str,
    ffmpeg_path: str = "ffmpeg",
    ducking: bool = True,
) -> None:
    """Mix narration and BGM audio with sidechain ducking.

    RENDERING-SPEC §4.2–§4.3:
    - Narration segments: BGM -18dB
    - Non-narration segments: BGM -8dB
    - Fade-in: 0.5s, Fade-out: 1.0s

    Parameters
    ----------
    narration_path:
        Path to narration WAV/audio file.
    bgm_path:
        Path to BGM audio file.
    output_path:
        Where to write the mixed audio.
    ffmpeg_path:
        FFmpeg executable path.
    ducking:
        If True, use sidechain ducking. If False, use simple volume mixing.
    """
    narr = Path(narration_path)
    bgm = Path(bgm_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not narr.exists():
        raise FileNotFoundError(f"Narration file not found: {narration_path}")
    if not bgm.exists():
        raise FileNotFoundError(f"BGM file not found: {bgm_path}")

    # Get narration duration for fade-out timing
    duration = _get_audio_duration(str(narr), ffmpeg_path)

    if ducking:
        # Sidechain ducking (RENDERING-SPEC §4.3)
        filter_complex = (
            "[0:a]asplit=2[narr][sc];"
            "[sc]aformat=channel_layouts=mono,"
            "compand=attacks=0:decays=0.3:"
            "points=-80/-80|-45/-45|-27/-30|0/-30,"
            "aformat=channel_layouts=stereo[sidechain];"
            f"[1:a]afade=t=in:d=0.5,afade=t=out:st={max(0, duration - 1.0):.2f}:d=1.0[bgm_faded];"
            "[bgm_faded][sidechain]sidechaincompress="
            "threshold=0.02:ratio=6:attack=10:release=300:level_sc=1[bgm_ducked];"
            "[narr][bgm_ducked]amix=inputs=2:duration=first[out]"
        )
    else:
        # Simple mixing: BGM at -18dB (RENDERING-SPEC §4.2)
        filter_complex = (
            f"[1:a]volume=-18dB,"
            f"afade=t=in:d=0.5,afade=t=out:st={max(0, duration - 1.0):.2f}:d=1.0[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[out]"
        )

    cmd = [
        ffmpeg_path, "-y",
        "-i", str(narr),
        "-stream_loop", "-1",  # Loop BGM if shorter than narration
        "-i", str(bgm),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(out),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg mix failed: {result.stderr[:500]}")


def prepare_bgm_for_video(
    bgm_path: str,
    output_path: str,
    duration_sec: float,
    ffmpeg_path: str = "ffmpeg",
) -> None:
    """Prepare a BGM track for video mixing: loop/trim + fade.

    RENDERING-SPEC §4.2:
    - Non-narration volume: -8dB
    - Fade-in: 0.5s, Fade-out: 1.0s
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fade_out_start = max(0, duration_sec - 1.0)

    cmd = [
        ffmpeg_path, "-y",
        "-stream_loop", "-1",
        "-i", str(bgm_path),
        "-af", (
            f"volume=-8dB,"
            f"afade=t=in:d=0.5,"
            f"afade=t=out:st={fade_out_start:.2f}:d=1.0"
        ),
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        "-t", f"{duration_sec:.2f}",
        str(out),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg BGM prep failed: {result.stderr[:500]}")


def _get_audio_duration(audio_path: str, ffmpeg_path: str = "ffmpeg") -> float:
    """Get audio duration in seconds using ffprobe."""
    ffprobe_path = str(Path(ffmpeg_path).with_name(
        Path(ffmpeg_path).name.replace("ffmpeg", "ffprobe")
    ))
    try:
        result = subprocess.run(
            [ffprobe_path, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return float(result.stdout.strip())
    except (ValueError, OSError):
        return 60.0  # Safe default
