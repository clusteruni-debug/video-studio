"""Media routes — scene-level TTS regeneration, image generation, dubbing.

Extracted from server.py to keep the main bridge under the 660-line limit.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus, urlparse

from flask import Blueprint, jsonify, request as flask_request, send_file

logger = logging.getLogger(__name__)

from worker.tts.providers import generate_tts
from worker.bridge.image_router import route_image, search_pexels_video_candidates
from worker.bridge.layouts import DEFAULT_TTS_RATE, TEMPLATE_BGM_MOOD, TTS_QUALITY_CANDIDATES
from worker.bridge.templates import get_live_channel_operating_templates, operating_template_for
from worker.quality_gate_system import build_final_readiness_gate_system
from worker.media.adapters import (
    AdapterExecutionContext,
    parse_command_template_value,
    probe_command_template_adapter,
    probe_local_media_adapter,
    run_local_media_adapter,
)
from worker.render.bgm import free_audio_candidates, free_audio_sidecar_template
from worker.render.render_manifest import slugify

media_bp = Blueprint("media", __name__)

# These are set by server.py at registration time
_bridge_host: str = "127.0.0.1"
_bridge_port: int = 5161
_tts_dir: Path = Path("storage/tts")
_project_root: Path = Path.cwd()
_get_audio_duration = None
_image_url_for_client = None
_safe_resolve = None

# Normalize source names so round-trip regeneration works:
# route_image returns "klipy" but expects "tenor" as input.
_SOURCE_NORMALIZE: dict[str, str] = {"imagen3": "imagen", "klipy": "tenor"}
_LOCAL_VIDEO_PROVIDERS = {"wan", "ltx-video", "hunyuan-video"}

_FREE_ASSET_PROVIDERS: dict[str, dict] = {
    "pexels-video": {
        "label": "Pexels Video",
        "kind": "video",
        "officialUrl": "https://www.pexels.com/api/documentation/#videos-search",
        "manualUrl": "https://www.pexels.com/videos/",
        "requires": "PEXELS_API_KEY for in-app candidates; manual web search can be used without storing credentials.",
        "licenseNote": "Use only manually reviewed clips and keep creator/source URL with the scene.",
        "proofFields": ["sourceUrl", "creator", "selection rationale", "no repeated asset id"],
    },
    "pixabay-video": {
        "label": "Pixabay Video",
        "kind": "video",
        "officialUrl": "https://pixabay.com/api/docs/",
        "manualUrl": "https://pixabay.com/videos/",
        "requires": "API key only if automated later; this packet uses manual search links.",
        "licenseNote": "Record page URL and verify current Pixabay Content License on the asset page.",
        "proofFields": ["pageURL", "creator", "license checked", "no repeated asset id"],
    },
    "wikimedia-commons": {
        "label": "Wikimedia Commons",
        "kind": "video/image/audio",
        "officialUrl": "https://commons.wikimedia.org/wiki/Commons:Media_search",
        "manualUrl": "https://commons.wikimedia.org/wiki/Special:MediaSearch",
        "requires": "No paid key; attribution and license terms vary by file.",
        "licenseNote": "Prefer CC0/public-domain/compatible Creative Commons assets and copy attribution.",
        "proofFields": ["file page", "license", "attribution", "commercial reuse check"],
    },
    "mixkit": {
        "label": "Mixkit",
        "kind": "video/music/sfx",
        "officialUrl": "https://mixkit.co/license/",
        "manualUrl": "https://mixkit.co/",
        "requires": "Manual download; no paid API required.",
        "licenseNote": "Check the item type license before use because Mixkit has separate licenses.",
        "proofFields": ["asset URL", "item type", "license type", "download date"],
    },
    "youtube-audio-library": {
        "label": "YouTube Audio Library",
        "kind": "music/sfx",
        "officialUrl": "https://support.google.com/youtube/answer/3376882",
        "manualUrl": "https://www.youtube.com/audiolibrary",
        "requires": "YouTube Studio sign-in; no paid API required.",
        "licenseNote": "Use attribution-not-required when possible; otherwise copy attribution text.",
        "proofFields": ["track title", "artist", "license type", "attribution text if required"],
    },
    "freesound": {
        "label": "Freesound",
        "kind": "sfx/ambience",
        "officialUrl": "https://freesound.org/docs/api/",
        "manualUrl": "https://freesound.org/search/",
        "requires": "Manual search or API token; license varies by sound.",
        "licenseNote": "Prefer CC0 for production; otherwise keep exact Creative Commons attribution.",
        "proofFields": ["sound URL", "license", "creator", "attribution text"],
    },
    "gongu-copyright": {
        "label": "Gongu/Copyright Korea",
        "kind": "music/sfx/image/video",
        "officialUrl": "https://gongu.copyright.or.kr/gongu/main/contents.do?menuNo=200093",
        "manualUrl": "https://gongu.copyright.or.kr/",
        "requires": "Manual search/download; no paid API. Verify the exact CCL item page before import.",
        "licenseNote": "CCL conditions vary by item; prefer CC BY/CC0-compatible works and avoid NC/ND for monetized edited videos.",
        "proofFields": ["work page", "creator", "CCL condition", "attribution text", "commercial/derivative check"],
    },
    "kogl": {
        "label": "KOGL Public Works",
        "kind": "public image/video/audio",
        "officialUrl": "https://www.mcst.go.kr/kor/s_open/kogl/koglType.jsp",
        "manualUrl": "https://www.kogl.or.kr/",
        "requires": "Manual search/download; no paid API. Prefer Type 1 for edited monetized YouTube work.",
        "licenseNote": "KOGL Type 1 allows commercial reuse and derivative works with attribution; Types 2-4 add restrictions.",
        "proofFields": ["public work page", "institution", "KOGL type", "attribution text", "commercial/derivative check"],
    },
}

_TEMPLATE_ASSET_GUIDES: dict[str, dict] = {
    "news_explainer": {
        "family": "Korean news/explainer",
        "layout": "top hook, restrained lower-info captions, map/data cards, slower evidence cuts",
        "sourceMix": "current-event B-roll plus operator-made context graphics; stock never as first unrelated top result",
        "preferredSourceOrder": ["direct-upload", "kogl", "wikimedia-commons", "pexels-video", "pixabay-video", "grok", "image-ken-burns"],
        "providers": ["pexels-video", "pixabay-video", "wikimedia-commons", "kogl", "youtube-audio-library", "gongu-copyright"],
        "audioMood": "minimal news bed, low gain, narration-first",
        "searchHints": ["Seoul street night", "smartphone news reading", "city office desk", "subway crowd"],
        "avoid": ["generic handshake", "random drone city cut", "large decorative center captions"],
    },
    "ranking_list": {
        "family": "Korean ranking/listicle Shorts",
        "layout": "number badge per item, one distinct clip per rank, no reused B-roll unless callback",
        "sourceMix": "Pexels/Pixabay/Wikimedia candidates per item with manual relevance notes",
        "preferredSourceOrder": ["pexels-video", "pixabay-video", "wikimedia-commons", "direct-upload", "grok", "image-ken-burns"],
        "providers": ["pexels-video", "pixabay-video", "wikimedia-commons", "mixkit", "youtube-audio-library", "gongu-copyright"],
        "audioMood": "light pulse bed plus soft whoosh only at rank changes",
        "searchHints": ["product close up", "street food detail", "workspace hands", "travel landmark detail"],
        "avoid": ["same establishing shot for every rank", "unverified product/logo footage", "random fast zooms"],
    },
    "tutorial_steps": {
        "family": "Korean how-to/tutorial",
        "layout": "step chip, screen/hand action proof, top hook then lower-info instructions",
        "sourceMix": "direct screen capture or operator footage first, stock only for setup/context",
        "preferredSourceOrder": ["direct-upload", "wan", "ltx-video", "pexels-video", "pixabay-video", "wikimedia-commons"],
        "providers": ["pexels-video", "pixabay-video", "wikimedia-commons", "mixkit", "freesound", "youtube-audio-library", "gongu-copyright"],
        "audioMood": "quiet tutorial bed, UI clicks only where they clarify action",
        "searchHints": ["hands using phone", "laptop screen desk", "kitchen preparation", "tool close up"],
        "avoid": ["stock cut that does not show the actual step", "caption covering the action", "music louder than narration"],
    },
    "authentic_vlog": {
        "family": "Korean authentic vlog/diary",
        "layout": "handheld POV, sparse captions, ambient natural sound, fewer hard cuts",
        "sourceMix": "operator footage first; free stock only as texture or transition insert",
        "preferredSourceOrder": ["direct-upload", "pexels-video", "pixabay-video", "mixkit", "youtube-audio-library", "image-ken-burns"],
        "providers": ["pexels-video", "pixabay-video", "mixkit", "youtube-audio-library", "freesound", "gongu-copyright"],
        "audioMood": "warm lo-fi or natural ambience; keep TTS conversational if used",
        "searchHints": ["cafe table morning", "walking street pov", "home desk evening", "rain window"],
        "avoid": ["over-polished commercial stock", "huge center captions", "unmotivated cinematic transitions"],
    },
    "persona_story": {
        "family": "AI persona/story Shorts",
        "layout": "consistent character/place bible, 2-4 second motion beats, no text baked into generated clips",
        "sourceMix": "Grok app/web or local Wan/LTX/Hunyuan original hero clips plus stock texture inserts",
        "preferredSourceOrder": ["grok", "wan", "ltx-video", "hunyuan-video", "direct-upload", "pexels-video", "image-ken-burns"],
        "providers": ["pexels-video", "pixabay-video", "wikimedia-commons", "mixkit", "youtube-audio-library", "freesound"],
        "audioMood": "cinematic bed with restrained SFX; narration must explain story beats",
        "searchHints": ["cinematic alley rain", "neon room close up", "forest mist path", "old desk lamp"],
        "avoid": ["character morphing", "different outfit every scene", "watermark/logo/text artifacts"],
    },
    "kculture_fandom": {
        "family": "K-culture/fandom recap",
        "layout": "top hook, fast but readable caption rhythm, rights-safe event/city/stage context",
        "sourceMix": "owned/direct fan footage or official-permitted media; stock city/stage B-roll only as context",
        "preferredSourceOrder": ["direct-upload", "wikimedia-commons", "kogl", "pexels-video", "pixabay-video", "grok", "image-ken-burns"],
        "providers": ["wikimedia-commons", "kogl", "pexels-video", "pixabay-video", "mixkit", "youtube-audio-library", "gongu-copyright"],
        "audioMood": "copyright-safe pop/electronic bed from YouTube Audio Library or Mixkit",
        "searchHints": ["Seoul concert crowd", "night street neon", "stage lights", "fans queue"],
        "avoid": ["unlicensed idol/performance footage", "music that can trigger claims", "misleading fan-cam context"],
    },
    "podcast_clip": {
        "family": "Korean podcast/commentary clip",
        "layout": "speaker-first frame, waveform or quote card, lower-info captions only when helpful",
        "sourceMix": "owned talk clip first, then B-roll cutaways and SFX for emphasis",
        "preferredSourceOrder": ["direct-upload", "freesound", "youtube-audio-library", "pexels-video", "pixabay-video", "image-ken-burns"],
        "providers": ["freesound", "youtube-audio-library", "pexels-video", "pixabay-video", "mixkit"],
        "audioMood": "voice-first mix, soft room tone cleanup, very light stings",
        "searchHints": ["podcast microphone close up", "studio headphones", "talk show camera", "sound wave"],
        "avoid": ["B-roll more prominent than speaker", "stock people pretending to talk", "subtitle blocks over faces"],
    },
    "longform_deep_dive": {
        "family": "Korean long-form deep dive",
        "layout": "chapter/title cards, sourced data cards, restrained lower-info captions, slower evidence pacing",
        "sourceMix": "operator-made charts/source cards plus manually selected evidence B-roll; stock supports arguments only",
        "preferredSourceOrder": ["direct-upload", "wikimedia-commons", "kogl", "pexels-video", "pixabay-video", "mixkit", "youtube-audio-library"],
        "providers": ["wikimedia-commons", "kogl", "pexels-video", "pixabay-video", "mixkit", "youtube-audio-library", "freesound", "gongu-copyright"],
        "audioMood": "low cinematic or documentary bed; narration stays dominant",
        "searchHints": ["Korean city office documentary", "data analysis desk", "newspaper archive", "quiet street interview"],
        "avoid": ["shorts-style giant captions", "unrelated abstract stock", "reusing one generic city shot across chapters"],
    },
    "interview_documentary": {
        "family": "Korean interview/documentary",
        "layout": "speaker/hands/location proof, quote card only for owned source, lower captions away from faces",
        "sourceMix": "owned interview/location MP4 first; TTS summary with B-roll only when audio rights are unavailable",
        "preferredSourceOrder": ["direct-upload", "freesound", "kogl", "wikimedia-commons", "pexels-video", "pixabay-video", "youtube-audio-library"],
        "providers": ["freesound", "kogl", "wikimedia-commons", "pexels-video", "pixabay-video", "youtube-audio-library", "mixkit", "gongu-copyright"],
        "audioMood": "room tone plus subtle documentary bed; no speaker impersonation",
        "searchHints": ["bookstore interview hands", "small business owner desk", "documentary street detail", "old photo archive"],
        "avoid": ["stock actors as interview subject", "AI voice imitation", "caption blocks over mouth or hands"],
    },
    "live_recap": {
        "family": "Korean live/event recap",
        "layout": "route card, point-by-point chapter chips, motion-led atmosphere, compact safe-zone callouts",
        "sourceMix": "direct event footage first, rights-safe venue/city/stage-light B-roll as support",
        "preferredSourceOrder": ["direct-upload", "pexels-video", "pixabay-video", "mixkit", "wikimedia-commons", "kogl", "youtube-audio-library"],
        "providers": ["pexels-video", "pixabay-video", "mixkit", "wikimedia-commons", "kogl", "youtube-audio-library", "freesound", "gongu-copyright"],
        "audioMood": "copyright-safe pulse bed or ambient crowd texture under narration",
        "searchHints": ["Seoul popup event crowd", "stage lights no performer", "people queue entrance", "night city venue"],
        "avoid": ["unlicensed performance audio", "broadcast footage", "MV/drama/anime clips", "copyrighted fan-cam audio"],
    },
}

_TEMPLATE_LAYOUT_VARIANTS: dict[str, list[dict]] = {
    "news_explainer": [
        {
            "key": "headline-evidence",
            "label": "headline + evidence cuts",
            "scenePattern": "hook headline -> evidence B-roll -> lower fact card -> implication",
            "captionPlan": "top-hook only on the first beat, lower-info for facts",
            "assetPlan": "Wikimedia/Pexels context clips plus operator-made data card stills when evidence is abstract.",
        },
        {
            "key": "timeline-brief",
            "label": "timeline brief",
            "scenePattern": "before -> trigger -> now -> why it matters",
            "captionPlan": "short top labels for chapter beats, no large center caption blocks",
            "assetPlan": "city/context clips, screen capture of public source, and one manually drawn timeline card.",
        },
    ],
    "ranking_list": [
        {
            "key": "rank-countdown",
            "label": "rank countdown",
            "scenePattern": "rank 3 -> rank 2 -> rank 1 -> closing comparison",
            "captionPlan": "small rank badge plus lower-info reason",
            "assetPlan": "one distinct manually selected stock/direct MP4 per rank; never reuse a generic establishing shot.",
        },
        {
            "key": "one-question-three-answers",
            "label": "question + three answers",
            "scenePattern": "question hook -> answer A -> answer B -> answer C",
            "captionPlan": "top question, lower answer details",
            "assetPlan": "query each answer separately and record why the clip fits that exact answer.",
        },
    ],
    "tutorial_steps": [
        {
            "key": "hands-proof",
            "label": "hands-on proof",
            "scenePattern": "problem -> step 1 -> step 2 -> result",
            "captionPlan": "top step chip, lower-info only for the action detail",
            "assetPlan": "direct phone/screen recording first; stock only for setup or result context.",
        },
        {
            "key": "screen-walkthrough",
            "label": "screen walkthrough",
            "scenePattern": "before screen -> tap/click -> changed state -> summary",
            "captionPlan": "no caption over active UI controls; lower-info below the action area",
            "assetPlan": "operator screen capture, CC0 icon overlays, optional Freesound click SFX.",
        },
    ],
    "authentic_vlog": [
        {
            "key": "pov-diary",
            "label": "POV diary",
            "scenePattern": "arrival -> detail -> small action -> exit",
            "captionPlan": "mostly none; lower-info only for one reflective line",
            "assetPlan": "direct handheld MP4 first, stock texture only for a transition insert.",
        },
        {
            "key": "ambient-routine",
            "label": "ambient routine",
            "scenePattern": "wide context -> hands/detail -> ambient cutaway -> quiet finish",
            "captionPlan": "short lower-info captions, no decorative center text",
            "assetPlan": "direct upload plus Freesound room tone or YouTube Audio Library low-gain bed.",
        },
    ],
    "persona_story": [
        {
            "key": "character-continuity",
            "label": "character continuity",
            "scenePattern": "same character hook -> prop close-up -> same character payoff",
            "captionPlan": "top hook first, then lower-info or none",
            "assetPlan": "Grok app/web or local Wan/LTX/Hunyuan MP4 per scene with a shared character/prop bible.",
        },
        {
            "key": "object-mystery",
            "label": "object mystery",
            "scenePattern": "object reveal -> hands/space reaction -> consequence",
            "captionPlan": "center-short only for one short reveal; keep generated video text-free",
            "assetPlan": "generated hero clips plus Pexels texture inserts that do not replace the story action.",
        },
    ],
    "kculture_fandom": [
        {
            "key": "fan-process",
            "label": "fan process",
            "scenePattern": "queue/setup -> making/gesture -> crowd/context -> reaction",
            "captionPlan": "fast top-safe callouts, no copyrighted lyric text",
            "assetPlan": "owned fan footage, rights-safe city/stage-light stock, copyright-safe BGM.",
        },
        {
            "key": "trend-recap",
            "label": "trend recap",
            "scenePattern": "trend hook -> why it spread -> safe substitute visual -> take",
            "captionPlan": "top hook and small lower explanation",
            "assetPlan": "Wikimedia/stock context and generated substitute visuals instead of unlicensed MV/drama footage.",
        },
    ],
    "podcast_clip": [
        {
            "key": "speaker-first",
            "label": "speaker first",
            "scenePattern": "speaker hook -> quote emphasis -> B-roll support -> takeaway",
            "captionPlan": "lower-info captions around the mouth/face area, no face-covering blocks",
            "assetPlan": "owned long-form clip first; B-roll is secondary.",
        },
        {
            "key": "tts-commentary",
            "label": "TTS commentary",
            "scenePattern": "question -> summarized point -> supporting cutaway -> comment prompt",
            "captionPlan": "top question, lower-info for summarized points",
            "assetPlan": "Edge/Windows TTS plus manually selected B-roll and Freesound emphasis SFX.",
        },
    ],
    "longform_deep_dive": [
        {
            "key": "chapter-evidence",
            "label": "chapter evidence",
            "scenePattern": "cold open -> chapter card -> evidence cut -> source/data card -> implication",
            "captionPlan": "chapter cards and lower facts only; avoid Shorts-sized center captions",
            "assetPlan": "operator-made chart cards plus Wikimedia/Pexels/Pixabay evidence clips with provenance.",
        },
        {
            "key": "documentary-explainer",
            "label": "documentary explainer",
            "scenePattern": "human detail -> data context -> expert/source quote -> practical conclusion",
            "captionPlan": "small lower-info captions and occasional title cards",
            "assetPlan": "direct location footage, public-license context media, and YouTube Audio Library documentary bed.",
        },
    ],
    "interview_documentary": [
        {
            "key": "observed-interview",
            "label": "observed interview",
            "scenePattern": "opening action -> owned quote -> hands/location proof -> reflective close",
            "captionPlan": "lower captions away from face/mouth/hands",
            "assetPlan": "owned interview clip first; Freesound room tone and rights-safe B-roll only as support.",
        },
        {
            "key": "tts-summary-doc",
            "label": "TTS summary doc",
            "scenePattern": "source-safe summary -> document/photo proof -> location detail -> takeaway",
            "captionPlan": "chapter labels plus lower explanatory captions",
            "assetPlan": "Edge/Windows TTS summary, Wikimedia evidence assets, and no AI voice imitation.",
        },
    ],
    "live_recap": [
        {
            "key": "route-recap",
            "label": "route recap",
            "scenePattern": "arrival -> route map -> three moments -> exit tip",
            "captionPlan": "route/point chips at top, lower-info for practical notes",
            "assetPlan": "direct event MP4 plus rights-safe venue/city/stage-light B-roll.",
        },
        {
            "key": "fan-atmosphere",
            "label": "fan atmosphere",
            "scenePattern": "queue -> object/detail -> crowd ambience -> recap judgment",
            "captionPlan": "small safe-zone callouts, no lyric-like center text",
            "assetPlan": "direct crowd/context footage, Mixkit/Pexels substitutes, and YouTube Audio Library BGM.",
        },
    ],
}

_ASSET_ACQUISITION_METHODS: list[dict] = [
    {
        "method": "direct-upload",
        "role": "owned hero/video proof",
        "freePath": "Record phone/screen/camera MP4 and upload it to the scene.",
        "fallback": "If unavailable, use Grok/local generation for the hero and stock only as support.",
        "proofFields": ["file name", "ownership note", "first-two-second hook", "quality review"],
    },
    {
        "method": "grok-app-web",
        "role": "AI original hero clip",
        "freePath": "Use the logged-in Grok app/web UI to create a short MP4, then import the downloaded clip.",
        "fallback": "Local Wan/LTX/Hunyuan or direct upload.",
        "proofFields": ["prompt", "shot bible", "downloaded MP4 name", "continuity/artifact review"],
    },
    {
        "method": "local-video-model",
        "role": "offline AI original clip",
        "freePath": "Run operator-approved Wan/LTX/Hunyuan command locally and import the generated MP4.",
        "fallback": "Grok app/web handoff or direct footage.",
        "proofFields": ["request json", "prompt txt", "command log", "output MP4"],
    },
    {
        "method": "pexels-video",
        "role": "support B-roll",
        "freePath": "Search multiple candidates, preview motion, and choose manually.",
        "fallback": "Pixabay Video, Wikimedia Commons, direct upload.",
        "proofFields": ["video id", "source page", "creator", "selection rationale"],
    },
    {
        "method": "pixabay-video",
        "role": "support B-roll alternate",
        "freePath": "Use manual search or a future API key only for candidate retrieval.",
        "fallback": "Pexels Video, Mixkit, Wikimedia Commons.",
        "proofFields": ["page URL", "license checked", "creator", "download date"],
    },
    {
        "method": "wikimedia-commons",
        "role": "evidence/context asset",
        "freePath": "Use public-domain or compatible Creative Commons media with attribution.",
        "fallback": "Operator-created graphic/card when license is unclear.",
        "proofFields": ["file page", "license", "attribution", "commercial reuse check"],
    },
    {
        "method": "youtube-audio-library",
        "role": "copyright-safe BGM/SFX",
        "freePath": "Download from YouTube Studio Audio Library and keep title/artist/license.",
        "fallback": "Mixkit music or CC0 Freesound ambience.",
        "proofFields": ["track title", "artist", "license", "attribution text"],
    },
    {
        "method": "mixkit",
        "role": "BGM/SFX/stock substitute",
        "freePath": "Download manually and verify the item-specific Mixkit license.",
        "fallback": "YouTube Audio Library or Freesound CC0.",
        "proofFields": ["asset URL", "item type", "license type", "download date"],
    },
    {
        "method": "freesound",
        "role": "ambience/SFX",
        "freePath": "Prefer CC0 sounds for ambience, UI clicks, room tone, or whooshes.",
        "fallback": "YouTube Audio Library SFX or no SFX.",
        "proofFields": ["sound URL", "license", "creator", "attribution text"],
    },
]

_COMMON_ASSET_PRODUCTION_RECIPES: list[dict] = [
    {
        "key": "phone-vertical-hero",
        "label": "direct 9:16 phone MP4",
        "goal": "Create at least one owned moving hero clip instead of relying on stock.",
        "whenToUse": "Use for the first hook scene whenever the topic can be filmed or screen-recorded by the operator.",
        "steps": [
            "Record 6-12 seconds in vertical 9:16 with one clear subject and visible motion in the first two seconds.",
            "Capture one wide context shot and one close detail shot so the edit has a natural cut option.",
            "Upload the MP4 to the matching scene and fill source rationale, continuity, and quality review notes.",
        ],
        "freeTools": ["phone camera", "Windows screen recorder", "Video Studio scene upload"],
        "proofFields": ["file name", "ownership note", "first-two-second hook", "caption/subject clear review"],
        "qualityGate": "Fails if the clip is static, unrelated, heavily compressed, or has logos/watermarks/text baked in.",
    },
    {
        "key": "source-data-card",
        "label": "operator-made source/data card",
        "goal": "Replace abstract stock filler with a readable evidence card for facts, timelines, and chapters.",
        "whenToUse": "Use when the scene explains a number, date, quote, route, comparison, or chapter transition.",
        "steps": [
            "Create a simple 1080x1920 card with one number/date/quote and no more than two supporting labels.",
            "Keep the main subject area clear for captions and avoid the right/bottom Shorts danger zones.",
            "Export as image or short MP4 and record the source URL or calculation note behind the fact.",
        ],
        "freeTools": ["PowerPoint/Canva free/manual card", "local HTML/CSS capture", "FFmpeg color/text card"],
        "proofFields": ["source URL or calculation note", "card text", "safe-zone review"],
        "qualityGate": "Fails if the card becomes a dense slide or replaces needed motion for the entire video.",
    },
    {
        "key": "copyright-safe-audio-bed",
        "label": "free BGM/SFX collection",
        "goal": "Build a reusable local audio library with provenance instead of reusing one default track.",
        "whenToUse": "Use for every final packet that enables BGM or SFX.",
        "steps": [
            "Collect at least two candidate tracks for the template mood from YouTube Audio Library, Mixkit, Pixabay, or Freesound.",
            "Prefer attribution-not-required or CC0 assets; otherwise copy exact attribution text.",
            "Add a sidecar JSON with provider, title, sourceUrl, sourceLicense/license, artist/creator, and attribution.",
        ],
        "freeTools": ["YouTube Studio Audio Library", "Mixkit", "Pixabay Music/SFX", "Freesound CC0"],
        "proofFields": ["track title", "artist/creator", "source URL", "license/attribution", "download date"],
        "qualityGate": "Fails if BGM has no provenance, overpowers TTS, or the same single file is reused by default.",
    },
]

_TEMPLATE_ASSET_PRODUCTION_RECIPES: dict[str, list[dict]] = {
    "persona_story": [
        {
            "key": "grok-or-local-character-bible",
            "label": "Grok/local character continuity MP4",
            "goal": "Make the first hook feel like original AI-assisted footage rather than a stock montage.",
            "whenToUse": "Use for AI persona/story scenes and any generated character/object sequence.",
            "steps": [
                "Write a fixed character/place/prop bible before generating scene clips.",
                "Generate 4-8 second MP4 clips in Grok app/web or local Wan/LTX/Hunyuan with the same bible repeated.",
                "Reject clips with face/outfit/prop drift, baked-in text, watermarks, or abrupt morphing.",
            ],
            "freeTools": ["Grok app/web handoff", "local Wan", "local LTX", "local Hunyuan"],
            "proofFields": ["prompt", "character/place/prop bible", "downloaded MP4 name", "continuity/artifact review"],
            "qualityGate": "Fails if the first hook is stock-only or generated characters drift between scenes.",
        },
    ],
    "ranking_list": [
        {
            "key": "rank-distinct-candidate-cull",
            "label": "one distinct clip per rank",
            "goal": "Prevent the list from feeling recycled by assigning a different visual source to every rank.",
            "whenToUse": "Use for ranking, listicle, comparison, and recommendation Shorts.",
            "steps": [
                "Search each rank/item separately instead of reusing one generic query.",
                "Preview at least three candidates per rank and choose the one that shows the exact item/action/context.",
                "Record candidate URL/id, creator, and why the chosen clip matches that rank.",
            ],
            "freeTools": ["Pexels Video", "Pixabay Video", "Wikimedia Commons", "direct capture"],
            "proofFields": ["candidate count", "selected URL/id", "creator", "selection rationale"],
            "qualityGate": "Fails if the same visual ID/source path appears in multiple ranks without a deliberate callback note.",
        },
    ],
    "tutorial_steps": [
        {
            "key": "step-proof-screen-or-hands",
            "label": "screen/hand proof capture",
            "goal": "Show the actual operation, not lifestyle stock over instructions.",
            "whenToUse": "Use for tutorials, recipes, app walkthroughs, and tool explanations.",
            "steps": [
                "Record the real screen, phone, hands, tool, or ingredient action for each step.",
                "Place captions as top chips or lower-info so they never cover taps, controls, hands, or the result.",
                "Use stock only for intro/context, not as evidence that a step was done.",
            ],
            "freeTools": ["Windows screen recorder", "phone camera", "CC0 icons", "Freesound click SFX"],
            "proofFields": ["step visible", "caption does not cover action", "result visible", "source ownership"],
            "qualityGate": "Fails if a step cannot be verified visually in the clip.",
        },
    ],
    "authentic_vlog": [
        {
            "key": "pov-routine-shot-list",
            "label": "POV routine shot list",
            "goal": "Create human-feeling Korean vlog texture without over-polished stock.",
            "whenToUse": "Use for cafe, travel, routine, food, desk, and diary-style Shorts.",
            "steps": [
                "Capture arrival/wide context, hands/detail, small action, and exit/aftertaste shots.",
                "Keep ambient sound or low BGM; avoid heavy center captions and random zooms.",
                "Use stock only as one transition texture if direct footage is missing.",
            ],
            "freeTools": ["phone camera", "Freesound ambience", "YouTube Audio Library low BGM"],
            "proofFields": ["shot role", "where/why filmed", "ambient/BGM note", "caption minimality review"],
            "qualityGate": "Fails if the edit looks like a generic cafe commercial stock montage.",
        },
    ],
    "longform_deep_dive": [
        {
            "key": "chapter-evidence-pack",
            "label": "chapter evidence pack",
            "goal": "Make long-form sections feel sourced and structured instead of a fast stock montage.",
            "whenToUse": "Use for long-form explainers, documentaries, and data-backed narratives.",
            "steps": [
                "Create one chapter card and one data/source card per section before collecting B-roll.",
                "Pick B-roll only when it supports the chapter claim or human context.",
                "Use lower facts and chapter labels instead of Shorts-style giant center captions.",
            ],
            "freeTools": ["Wikimedia Commons", "operator-made chart card", "Pexels/Pixabay context clips", "YouTube Audio Library documentary bed"],
            "proofFields": ["chapter claim", "source URL", "chart/card note", "B-roll relevance note"],
            "qualityGate": "Fails if chapters have no source/data card or stock clips carry the argument alone.",
        },
    ],
    "interview_documentary": [
        {
            "key": "owned-interview-proof",
            "label": "owned interview/location proof",
            "goal": "Keep the subject credible by showing owned interview, hands, place, or work evidence.",
            "whenToUse": "Use for interviews, local business stories, expert commentary, and documentary profiles.",
            "steps": [
                "Use owned interview/location MP4 first; if audio rights are absent, summarize with TTS instead of impersonating.",
                "Add hands/location/object proof immediately after claims so speech is supported by image.",
                "Keep lower captions away from mouth, hands, and core action.",
            ],
            "freeTools": ["direct interview MP4", "Freesound room tone", "Wikimedia evidence media", "Edge/Windows TTS summary"],
            "proofFields": ["ownership or fallback reason", "timestamp/source note", "subject visibility", "no voice imitation"],
            "qualityGate": "Fails if stock actors pretend to be the interview subject or AI voice imitates a real speaker.",
        },
    ],
    "live_recap": [
        {
            "key": "event-route-recap-pack",
            "label": "event route recap pack",
            "goal": "Turn direct event footage into a coherent route/point recap without copyrighted performance material.",
            "whenToUse": "Use for popups, concerts, festivals, fan events, launch events, and local recaps.",
            "steps": [
                "Capture arrival, queue/entrance, route/map point, detail/object, crowd/context, and exit tip.",
                "Mute or replace copyrighted performance audio with a safe BGM/ambience bed.",
                "Use route/point chips and small safe-zone callouts rather than lyric-like captions.",
            ],
            "freeTools": ["phone camera", "Mixkit/Pexels venue context", "YouTube Audio Library pulse bed", "Freesound ambience"],
            "proofFields": ["event footage ownership", "audio rights note", "route/point labels", "license-safe BGM"],
            "qualityGate": "Fails if broadcast/MV/drama/anime/performance audio is used without rights.",
        },
    ],
}

_TEMPLATE_ASSET_PRODUCTION_RECIPES["news_explainer"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["longform_deep_dive"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["kculture_fandom"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["live_recap"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["podcast_clip"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["interview_documentary"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["vs_comparison"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["ranking_list"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["myth_buster"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["longform_deep_dive"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["before_after"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["authentic_vlog"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["community_read"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["authentic_vlog"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["reddit_translation"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["authentic_vlog"]
_TEMPLATE_ASSET_PRODUCTION_RECIPES["hot_take"] = _TEMPLATE_ASSET_PRODUCTION_RECIPES["ranking_list"]

_EVIDENCE_SOURCES: list[dict] = [
    {
        "key": "youtube-kr-shorts-workshop-2025",
        "label": "YouTube Korea Shorts creator workshop",
        "sourceType": "official-youtube-blog",
        "url": "https://blog.youtube/intl/ko-kr/creator-and-artist-stories/shorts-workshop-kr-2025/",
        "appliesTo": ["shorts", "template-layout", "sound-sync"],
        "operatorUse": "Treat Shorts as multi-scene motion stories up to 3 minutes, with sound/text used intentionally instead of static slideshow filler.",
    },
    {
        "key": "youtube-kr-year-on-youtube-2025",
        "label": "YouTube Korea 2025 trend recap",
        "sourceType": "official-youtube-blog",
        "url": "https://blog.youtube/intl/ko-kr/culture-and-trends/year-on-youtube-2025-korea/",
        "appliesTo": ["authentic-vlog", "kculture-fandom", "creator-led"],
        "operatorUse": "Favor authentic creator footage, K-culture context, and multi-format story hooks over generic stock montage.",
    },
    {
        "key": "youtube-shorts-editing-tips",
        "label": "YouTube Shorts editing tips",
        "sourceType": "official-youtube-help",
        "url": "https://support.google.com/youtube/answer/13380879?hl=en",
        "appliesTo": ["captions", "audio", "shorts"],
        "operatorUse": "Use text to clarify story or accessibility and choose audio for mood; do not let captions become decorative overlays.",
    },
    {
        "key": "youtube-audio-library",
        "label": "YouTube Audio Library",
        "sourceType": "official-youtube-help",
        "url": "https://support.google.com/youtube/answer/3376882?hl=en-EN",
        "appliesTo": ["bgm", "sfx", "license"],
        "operatorUse": "Use YouTube Studio Audio Library first for BGM/SFX and keep attribution/license metadata with the final packet.",
    },
    {
        "key": "pexels-video-api",
        "label": "Pexels Video API",
        "sourceType": "official-api-doc",
        "url": "https://www.pexels.com/api/documentation/",
        "appliesTo": ["pexels-video", "candidate-search", "stock-broll"],
        "operatorUse": "Search multiple vertical video candidates, keep Pexels link/creator, and manually select scene-fit clips.",
    },
    {
        "key": "pixabay-api",
        "label": "Pixabay API",
        "sourceType": "official-api-doc",
        "url": "https://pixabay.com/api/docs/",
        "appliesTo": ["pixabay-video", "stock-broll"],
        "operatorUse": "Use as a free stock fallback and keep page URL/source attribution whenever search results are displayed.",
    },
    {
        "key": "wikimedia-commons-licensing",
        "label": "Wikimedia Commons licensing",
        "sourceType": "official-policy",
        "url": "https://commons.wikimedia.org/wiki/Commons:Licensing",
        "appliesTo": ["wikimedia-commons", "evidence-media", "license"],
        "operatorUse": "Verify file-page license/attribution and commercial reuse compatibility before using Commons media.",
    },
    {
        "key": "xai-imagine-pricing",
        "label": "xAI Imagine API pricing",
        "sourceType": "official-pricing",
        "url": "https://docs.x.ai/developers/pricing",
        "appliesTo": ["grok", "paid-api-policy"],
        "operatorUse": "Do not wire Grok Imagine API into the zero-paid path; use only operator-owned Grok app/web MP4 handoff.",
    },
    {
        "key": "xai-imagine-overview",
        "label": "xAI Imagine overview",
        "sourceType": "official-api-doc",
        "url": "https://docs.x.ai/developers/model-capabilities/imagine",
        "appliesTo": ["grok", "handoff"],
        "operatorUse": "Use API docs only as capability reference; Video Studio imports MP4s from the signed-in app/web workflow.",
    },
    {
        "key": "wan21-github",
        "label": "Wan2.1 GitHub",
        "sourceType": "official-github",
        "url": "https://github.com/Wan-Video/Wan2.1",
        "appliesTo": ["wan", "local-video-model"],
        "operatorUse": "Use local Wan output as an original-motion substitute when Grok app/web clips are unavailable.",
    },
    {
        "key": "ltx-desktop-github",
        "label": "LTX Desktop GitHub",
        "sourceType": "official-github",
        "url": "https://github.com/Lightricks/LTX-Desktop",
        "appliesTo": ["ltx-video", "local-video-model"],
        "operatorUse": "Use local Windows/Linux CUDA mode only; API-only LTX mode is outside the zero-paid default.",
    },
    {
        "key": "hunyuan-video-github",
        "label": "HunyuanVideo GitHub",
        "sourceType": "official-github",
        "url": "https://github.com/Tencent-Hunyuan/HunyuanVideo",
        "appliesTo": ["hunyuan-video", "local-video-model"],
        "operatorUse": "Use as an offline/open-source video-model option when hardware and setup are available.",
    },
]

_KOREAN_TEMPLATE_PLAYBOOK: list[dict] = [
    {
        "templateType": "authentic_vlog",
        "family": "Korean vlog/diary Shorts",
        "pattern": "quiet human hook -> lived detail -> small discovery -> reflective close",
        "layout": "full-frame handheld motion, sparse lower-info captions, ambience-first audio",
        "primaryAssets": ["direct-upload", "phone/camera MP4", "owned ambience"],
        "freeAssetSubstitutes": ["Pexels/Pixabay transition texture", "Freesound room tone", "YouTube Audio Library low BGM"],
        "qualityGate": "Fails if stock clips look like ads or center captions cover the real action.",
    },
    {
        "templateType": "persona_story",
        "family": "AI persona/story Shorts",
        "pattern": "same character/place/prop hook -> conflict beat -> payoff",
        "layout": "scene 1 top hook, later lower-info or no caption; no baked-in text",
        "primaryAssets": ["Grok app/web MP4", "Wan/LTX/Hunyuan local MP4"],
        "freeAssetSubstitutes": ["Pexels texture inserts only", "Mixkit/Freesound atmosphere"],
        "qualityGate": "Fails if face/outfit/prop continuity drifts or only generic stock carries the story.",
    },
    {
        "templateType": "news_explainer",
        "family": "Korean news/explainer",
        "pattern": "headline hook -> evidence B-roll -> fact card -> implication",
        "layout": "top hook first, small lower facts, source/data cards for long-form",
        "primaryAssets": ["Wikimedia evidence media", "operator-made source card", "direct screen capture"],
        "freeAssetSubstitutes": ["Pexels/Pixabay context cuts", "YouTube Audio Library neutral bed"],
        "qualityGate": "Fails if Pexels top-1 is merely related or source/license proof is absent.",
    },
    {
        "templateType": "ranking_list",
        "family": "Korean ranking/listicle",
        "pattern": "question hook -> one distinct clip per rank -> closing comparison",
        "layout": "stable rank badge, lower reason line, controlled rhythm resets",
        "primaryAssets": ["distinct Pexels/Pixabay/Wikimedia clip per rank", "direct proof clip"],
        "freeAssetSubstitutes": ["operator-made still card only when a video clip is impossible"],
        "qualityGate": "Fails if the same visual URL/id repeats across ranks without callback rationale.",
    },
    {
        "templateType": "longform_deep_dive",
        "family": "Korean long-form deep dive",
        "pattern": "cold open -> chapter card -> evidence sequence -> source/data card -> conclusion",
        "layout": "chapter rhythm, lower facts, no Shorts-style giant captions",
        "primaryAssets": ["operator-made charts/source cards", "Wikimedia/Pexels evidence B-roll", "direct capture"],
        "freeAssetSubstitutes": ["Pixabay context footage", "YouTube Audio Library documentary bed"],
        "qualityGate": "Fails if it becomes a fast stock montage with no chapter/source evidence.",
    },
    {
        "templateType": "interview_documentary",
        "family": "Korean interview/documentary",
        "pattern": "observed action -> owned quote/context -> location proof -> takeaway",
        "layout": "speaker/hands/location visible, compact lower captions away from faces",
        "primaryAssets": ["owned interview/location MP4", "direct room tone"],
        "freeAssetSubstitutes": ["Freesound ambience", "Wikimedia evidence media", "Pexels context only"],
        "qualityGate": "Fails if stock actors pretend to be the subject or AI voice imitates a real speaker.",
    },
    {
        "templateType": "live_recap",
        "family": "Korean live/event recap",
        "pattern": "arrival hook -> route/context -> key moments -> practical close",
        "layout": "route/point chips, compact safe-zone callouts, motion-led atmosphere",
        "primaryAssets": ["direct event phone MP4", "owned crowd/venue clips"],
        "freeAssetSubstitutes": ["Mixkit/Pexels stage-light or city context", "YouTube Audio Library pulse bed"],
        "qualityGate": "Fails if it uses unlicensed performance audio or broadcast/MV/drama/anime inserts.",
    },
]

BGM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def init_media_routes(
    bridge_host: str, bridge_port: int, tts_dir: Path, project_root: Path,
    get_audio_duration, image_url_for_client, safe_resolve,
):
    global _bridge_host, _bridge_port, _tts_dir, _project_root
    global _get_audio_duration, _image_url_for_client, _safe_resolve
    _bridge_host = bridge_host
    _bridge_port = bridge_port
    _tts_dir = tts_dir
    _project_root = project_root
    _get_audio_duration = get_audio_duration
    _image_url_for_client = image_url_for_client
    _safe_resolve = safe_resolve


def _resolve_under_project(value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = _project_root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(_project_root.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _local_video_preview_url(source_path: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/local-video/preview?path={quote(source_path)}"


# ---------------------------------------------------------------------------
# Scene-level TTS regeneration
# ---------------------------------------------------------------------------

@media_bp.route("/api/regenerate-scene-tts", methods=["POST"])
def regenerate_scene_tts_route():
    """Regenerate TTS for a single scene after narration edit."""
    data = flask_request.get_json(silent=True) or {}
    narration = data.get("narration", "").strip()
    if not narration:
        return jsonify({"ok": False, "error": "narration is required"}), 400
    try:
        scene_num = max(1, min(int(data.get("scene_num", 1)), 100))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "invalid scene_num"}), 400
    lang = data.get("lang", "ko")
    tts_provider = data.get("tts_provider", "edge")
    voice_gender = data.get("voice_gender", "female")
    tts_rate = str(data.get("rate") or data.get("tts_rate") or DEFAULT_TTS_RATE)
    tts_pitch = str(data.get("pitch") or data.get("tts_pitch") or "+0Hz")

    regen_ts = str(int(time.time()))
    regen_dir = _tts_dir / regen_ts
    regen_dir.mkdir(parents=True, exist_ok=True)
    audio_path = regen_dir / f"scene_{scene_num}.mp3"

    try:
        generate_tts(
            text=narration, lang=lang, gender=voice_gender,
            provider=tts_provider, output_path=audio_path,
            rate=tts_rate, pitch=tts_pitch,
        )
        duration = _get_audio_duration(str(audio_path))
        tts_url = f"http://{_bridge_host}:{_bridge_port}/api/tts/{regen_ts}/scene_{scene_num}.mp3"
        return jsonify({
            "ok": True,
            "_tts_url": tts_url,
            "duration": round(duration, 1),
            "rate": tts_rate,
            "pitch": tts_pitch,
            "qualityCandidates": TTS_QUALITY_CANDIDATES,
            "operatorAction": "Regenerate 2-4 zero-paid voice/rate candidates and pick by phone/headphone listening before final render.",
        })
    except Exception as e:
        # Flask route handler: broad catch required to convert any downstream
        # failure into a 500 response; log for observability.
        logger.warning("%s failed: %s", flask_request.path, e)
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Image generation / search (single scene)
# ---------------------------------------------------------------------------

@media_bp.route("/api/generate-image", methods=["POST"])
def generate_image_route():
    """Generate or search for an image using the server-side route_image pipeline."""
    data = flask_request.get_json(silent=True) or {}
    image_prompt = data.get("image_prompt", "").strip()
    if not image_prompt:
        return jsonify({"ok": False, "error": "image_prompt is required"}), 400

    raw_source = data.get("image_source", "")
    normalized_source = _SOURCE_NORMALIZE.get(raw_source, raw_source)

    scene = {
        "image_prompt": image_prompt,
        "image_source": normalized_source,
        "emotion": data.get("emotion", "neutral"),
        "fallback_prompt": data.get("fallback_prompt", ""),
    }
    try:
        raw_url, source = route_image(scene)
        client_url = _image_url_for_client(raw_url)
        display_source = _SOURCE_NORMALIZE.get(source, source) if source else source
        if client_url:
            return jsonify({"ok": True, "image_url": client_url, "source": display_source})
        return jsonify({"ok": False, "error": "No image found for this prompt"}), 404
    except Exception as e:
        # Flask route handler: broad catch required to convert any downstream
        # failure into a 500 response; log for observability.
        logger.warning("%s failed: %s", flask_request.path, e)
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Free asset sourcing packet (template-aware, no external API call)
# ---------------------------------------------------------------------------


@media_bp.route("/api/live-channel/templates", methods=["GET"])
def live_channel_templates_route():
    """Return reusable live-channel operating templates without paid API calls."""
    return jsonify({
        "ok": True,
        "templates": get_live_channel_operating_templates(),
        "templateOrder": [
            "authentic_vlog_no_voice",
            "info_top_hook_lower_info",
            "ranking_chapter_card_compact",
            "longform_16x9_extension",
        ],
    })


def _asset_guide_for(template_type: str) -> dict:
    return _TEMPLATE_ASSET_GUIDES.get(template_type) or _TEMPLATE_ASSET_GUIDES["news_explainer"]


def _template_playbook_for(template_type: str) -> dict:
    for item in _KOREAN_TEMPLATE_PLAYBOOK:
        if item.get("templateType") == template_type:
            return item
    return _KOREAN_TEMPLATE_PLAYBOOK[0]


def _bgm_mood_for_template(template_type: str) -> str:
    return TEMPLATE_BGM_MOOD.get(str(template_type or "").strip(), "upbeat")


_TEMPLATE_AUDIO_FALLBACK_MOODS: dict[str, list[str]] = {
    "news_explainer": ["cinematic", "calm", "upbeat"],
    "ranking_list": ["upbeat", "cinematic", "calm"],
    "tutorial_steps": ["calm", "upbeat", "cinematic"],
    "authentic_vlog": ["calm", "upbeat", "cinematic"],
    "persona_story": ["cinematic", "calm", "upbeat"],
    "kculture_fandom": ["upbeat", "cinematic", "calm"],
    "podcast_clip": ["calm", "cinematic", "upbeat"],
    "longform_deep_dive": ["cinematic", "calm", "upbeat"],
    "interview_documentary": ["calm", "cinematic", "upbeat"],
    "live_recap": ["upbeat", "calm", "cinematic"],
}

_TEMPLATE_SFX_POLICIES: dict[str, str] = {
    "news_explainer": "Minimal stings only for source/chapter changes; never cover narration.",
    "ranking_list": "One restrained whoosh or click per rank change; avoid constant transition noise.",
    "tutorial_steps": "Short UI clicks only where they clarify a real action.",
    "authentic_vlog": "Prefer natural ambience over synthetic SFX.",
    "persona_story": "Use sparse cinematic hits for reveal beats, not every cut.",
    "kculture_fandom": "Use copyright-safe pops/whooshes only; never use protected song hooks.",
    "podcast_clip": "Voice-first mix; SFX only for quote emphasis or section breaks.",
    "longform_deep_dive": "Chapter stings and low ambience only; keep analysis calm.",
    "interview_documentary": "Room tone and location ambience beat decorative effects.",
    "live_recap": "Crowd/venue ambience and light beat-sync accents; no unlicensed performance audio.",
}


def _audio_fallback_moods_for_template(template_type: str, recommended_mood: str) -> list[str]:
    moods = _TEMPLATE_AUDIO_FALLBACK_MOODS.get(template_type, ["calm", "cinematic", "upbeat"])
    ordered: list[str] = []
    for mood in [recommended_mood, *moods]:
        normalized = str(mood or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered[1:]


def _template_audio_plan_for(template_type: str, variant_key: str | None = None) -> dict:
    """Build a template/variant audio plan for the free audio picker.

    This keeps Korean Shorts/longform workflows from collapsing into one global
    BGM mood and one fixed layout. The returned plan is advisory; candidates
    still require manual download and source/license sidecars before render.
    """
    template_type = str(template_type or "news_explainer").strip() or "news_explainer"
    recommended_mood = _bgm_mood_for_template(template_type)
    guide = _TEMPLATE_ASSET_GUIDES.get(template_type, {})
    variants = list(_TEMPLATE_LAYOUT_VARIANTS.get(template_type) or [])
    selected = next((item for item in variants if item.get("key") == variant_key), None)
    if selected is None and variants:
        selected = variants[0]
    source_routes = list(dict.fromkeys([
        *(guide.get("providers") or []),
        "youtube-audio-library",
        "mixkit",
        "pixabay-audio",
        "freesound",
    ]))
    variant_payloads: list[dict] = []
    for variant in variants[:4]:
        variant_payloads.append({
            "key": variant.get("key") or "",
            "label": variant.get("label") or variant.get("key") or "",
            "captionPlan": variant.get("captionPlan") or "",
            "assetPlan": variant.get("assetPlan") or "",
            "recommendedMood": recommended_mood,
            "bgmRule": guide.get("audioMood") or "voice-first low-gain BGM",
            "sfxRule": _TEMPLATE_SFX_POLICIES.get(template_type) or "Use SFX only when it clarifies the edit.",
            "sourceRoutes": source_routes[:5],
        })
    selected_payload = None
    if selected:
        selected_payload = next((item for item in variant_payloads if item["key"] == selected.get("key")), None)
    return {
        "templateType": template_type,
        "recommendedMood": recommended_mood,
        "fallbackMoods": _audio_fallback_moods_for_template(template_type, recommended_mood),
        "sourceRoutes": source_routes,
        "bgmRule": guide.get("audioMood") or "voice-first low-gain BGM",
        "sfxPolicy": _TEMPLATE_SFX_POLICIES.get(template_type) or "Use SFX only when it clarifies the edit.",
        "layoutVariants": variant_payloads,
        "selectedVariant": selected_payload,
        "avoid": guide.get("avoid") or [],
        "operatorAction": (
            "Pick audio by template variant, download from the source page, then import with provenance. "
            "Do not reuse one bed/SFX pack across unrelated templates unless the quality checklist records it as intentional."
        ),
    }


def _asset_production_recipes_for(template_type: str) -> list[dict]:
    seen: set[str] = set()
    recipes: list[dict] = []
    for recipe in [
        *_TEMPLATE_ASSET_PRODUCTION_RECIPES.get(template_type, []),
        *_COMMON_ASSET_PRODUCTION_RECIPES,
    ]:
        key = str(recipe.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        recipes.append(recipe)
    return recipes


def _bgm_metadata_for_track(track: Path) -> dict:
    sidecar_candidates = [
        track.with_suffix(f"{track.suffix}.json"),
        track.with_suffix(".json"),
        track.parent / "sources.json",
        track.parent.parent / "sources.json",
    ]
    for sidecar in sidecar_candidates:
        if not sidecar.exists():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and track.name in payload and isinstance(payload[track.name], dict):
            return payload[track.name]
        if isinstance(payload, dict) and track.stem in payload and isinstance(payload[track.stem], dict):
            return payload[track.stem]
        if isinstance(payload, dict) and any(key in payload for key in ("sourceUrl", "sourceLicense", "license", "attribution")):
            return payload
    return {}


def _bgm_provenance_ready(metadata: dict) -> bool:
    return bool(
        metadata.get("sourceUrl")
        and (metadata.get("sourceLicense") or metadata.get("license") or metadata.get("licenseUrl"))
    )


def _scan_local_bgm_library(recommended_mood: str) -> dict:
    bgm_dir = _project_root / "assets" / "bgm"
    by_mood: dict[str, dict] = {}
    tracks_payload: list[dict] = []
    if bgm_dir.is_dir():
        for track in sorted(bgm_dir.rglob("*")):
            if not track.is_file() or track.suffix.lower() not in BGM_EXTENSIONS:
                continue
            try:
                relative = track.resolve().relative_to(bgm_dir.resolve())
            except (OSError, ValueError):
                relative = Path(track.name)
            mood = relative.parts[0] if len(relative.parts) > 1 else "root"
            metadata = _bgm_metadata_for_track(track)
            provenance_ready = _bgm_provenance_ready(metadata)
            bucket = by_mood.setdefault(mood, {"total": 0, "withProvenance": 0, "missingProvenance": 0})
            bucket["total"] += 1
            if provenance_ready:
                bucket["withProvenance"] += 1
            else:
                bucket["missingProvenance"] += 1
            tracks_payload.append({
                "path": _project_relative(track),
                "mood": mood,
                "title": metadata.get("title") or metadata.get("sourceLabel") or track.stem,
                "provider": metadata.get("provider") or "local-bgm",
                "sourceUrl": metadata.get("sourceUrl") or "",
                "license": metadata.get("sourceLicense") or metadata.get("license") or metadata.get("licenseUrl") or "",
                "provenanceReady": provenance_ready,
            })

    recommended_tracks = [
        item for item in tracks_payload
        if item["mood"] == recommended_mood and item["provenanceReady"]
    ][:5]
    missing_samples = [
        item for item in tracks_payload
        if not item["provenanceReady"]
    ][:5]
    total = len(tracks_payload)
    with_provenance = sum(1 for item in tracks_payload if item["provenanceReady"])
    return {
        "recommendedMood": recommended_mood,
        "libraryPath": _project_relative(bgm_dir),
        "totalTracks": total,
        "tracksWithProvenance": with_provenance,
        "tracksMissingProvenance": total - with_provenance,
        "byMood": by_mood,
        "recommendedTracks": recommended_tracks,
        "missingProvenanceSamples": missing_samples,
        "status": "ready" if recommended_tracks else ("needs-metadata" if total else "empty"),
        "operatorAction": (
            f"Use a {recommended_mood} track with source/license metadata."
            if recommended_tracks
            else "Add source/license sidecars for local BGM or choose YouTube Audio Library/Mixkit/Freesound with copied provenance."
            if total
            else "Download a copyright-safe BGM/SFX asset and add a metadata sidecar before enabling BGM for final work."
        ),
    }


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "approved"}


def _positive_limit(value: object, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, maximum))


def _audio_candidate_payload(candidate: dict[str, object]) -> dict[str, object]:
    candidate_id = str(candidate.get("id") or "")
    payload = dict(candidate)
    sidecar = free_audio_sidecar_template(candidate_id)
    if sidecar:
        payload["sidecarTemplate"] = sidecar
    kind = str(candidate.get("kind") or "")
    target_role = "sfx" if kind in {"sfx", "sfx-pack"} else "bgm"
    payload["importPayloadTemplate"] = {
        "candidateId": candidate_id,
        "sourcePath": "",
        "targetRole": target_role,
        "mood": candidate.get("mood") or "",
        "operatorApproved": False,
    }
    return payload


def _audio_sidecar_from_request(data: dict) -> dict:
    candidate_id = str(data.get("candidateId") or data.get("candidate_id") or "").strip()
    sidecar = free_audio_sidecar_template(candidate_id) or {}
    field_map = {
        "provider": "provider",
        "title": "title",
        "artist": "artist",
        "creator": "artist",
        "sourceUrl": "sourceUrl",
        "source_url": "sourceUrl",
        "sourceLicense": "sourceLicense",
        "source_license": "sourceLicense",
        "license": "license",
        "licenseUrl": "licenseUrl",
        "license_url": "licenseUrl",
        "attribution": "attribution",
        "attributionRequired": "attributionRequired",
        "attribution_required": "attributionRequired",
        "mood": "mood",
        "kind": "kind",
        "durationSec": "durationSec",
        "duration_sec": "durationSec",
        "editNotes": "editNotes",
        "edit_notes": "editNotes",
        "riskNote": "riskNote",
        "risk_note": "riskNote",
        "downloadDate": "downloadDate",
        "download_date": "downloadDate",
        "operatorOwned": "operatorOwned",
        "operator_owned": "operatorOwned",
        "recordedAt": "recordedAt",
        "recorded_at": "recordedAt",
        "speaker": "speaker",
        "sourceOrigin": "sourceOrigin",
        "source_origin": "sourceOrigin",
    }
    for input_key, output_key in field_map.items():
        if input_key in data and data[input_key] not in (None, ""):
            sidecar[output_key] = data[input_key]
    if isinstance(data.get("templateFamilies"), list):
        sidecar["templateFamilies"] = data["templateFamilies"]
    if not sidecar.get("downloadDate"):
        sidecar["downloadDate"] = datetime.now().date().isoformat()
    return sidecar


def _free_audio_provenance_ready(metadata: dict) -> bool:
    return bool(
        str(metadata.get("sourceUrl") or "").strip()
        and str(metadata.get("sourceLicense") or metadata.get("license") or metadata.get("licenseUrl") or "").strip()
    )


def _operator_owned_voiceover_ready(metadata: dict) -> bool:
    return _truthy(metadata.get("operatorOwned") or metadata.get("operator_owned"))


def _audio_target_role(data: dict, sidecar: dict) -> str:
    raw = str(data.get("targetRole") or data.get("target_role") or data.get("role") or "").strip().lower()
    if raw in {"bgm", "sfx", "voiceover"}:
        return raw
    kind = str(sidecar.get("kind") or data.get("kind") or "").strip().lower()
    if kind in {"voiceover", "native", "uploaded-audio"}:
        return "voiceover"
    return "sfx" if kind in {"sfx", "sfx-pack"} else "bgm"


def _unique_audio_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find free destination for {path}")


def _audio_destination(source_path: Path, data: dict, sidecar: dict) -> tuple[str, Path]:
    role = _audio_target_role(data, sidecar)
    mood = slugify(str(data.get("mood") or sidecar.get("mood") or "calm")) or "calm"
    if role == "bgm":
        destination_dir = _project_root / "assets" / "bgm" / mood
    elif role == "voiceover":
        destination_dir = _project_root / "assets" / "voiceover"
    else:
        destination_dir = _project_root / "assets" / "sfx"
    raw_file_name = str(data.get("fileName") or data.get("file_name") or "").strip()
    filename_source = Path(raw_file_name).stem if raw_file_name else str(sidecar.get("title") or source_path.stem)
    filename_stem = slugify(filename_source)
    filename_stem = filename_stem or slugify(source_path.stem) or f"free-audio-{int(time.time())}"
    return role, _unique_audio_destination(destination_dir / f"{filename_stem}{source_path.suffix.lower()}")


@media_bp.route("/api/free-assets/audio-candidates", methods=["POST"])
def free_audio_candidates_route():
    """Return concrete zero-paid BGM/SFX candidates without downloading assets."""
    data = flask_request.get_json(silent=True) or {}
    template_type = str(data.get("templateType") or data.get("template_type") or "news_explainer")
    variant_key = str(data.get("variantKey") or data.get("variant_key") or "").strip() or None
    mood = str(data.get("mood") or _bgm_mood_for_template(template_type) or "").strip() or None
    kind = str(data.get("kind") or "").strip() or None
    include_risky = _truthy(data.get("includeRisky", data.get("include_risky", True)))
    limit = _positive_limit(data.get("limit"), 8, 50)
    template_audio_plan = _template_audio_plan_for(template_type, variant_key)
    candidates = free_audio_candidates(
        template_type=template_type,
        mood=mood,
        kind=kind,
        include_risky=include_risky,
        fallback_moods=template_audio_plan["fallbackMoods"],
        limit=limit,
    )
    fallback_used = any(str(candidate.get("matchReason") or "") != "exact" for candidate in candidates)
    return jsonify({
        "ok": True,
        "templateType": template_type,
        "variantKey": variant_key or "",
        "recommendedMood": mood,
        "kind": kind or "any",
        "includeRisky": include_risky,
        "fallbackUsed": fallback_used,
        "templateAudioPlan": template_audio_plan,
        "candidates": [_audio_candidate_payload(candidate) for candidate in candidates],
        "operatorAction": (
            "Choose a candidate, download it manually from the source page, then call import-audio "
            "with operatorApproved=true and either a browser-selected audio file or local file path so Video Studio writes provenance sidecars."
        ),
    })


@media_bp.route("/api/free-assets/import-audio", methods=["POST"])
def free_audio_import_route():
    """Copy operator-approved BGM/SFX/voiceover audio into the local library with provenance."""
    data = flask_request.get_json(silent=True) or {}
    if not _truthy(data.get("operatorApproved") or data.get("operator_approved")):
        return jsonify({"ok": False, "error": "operatorApproved=true is required before importing local audio"}), 400
    raw_source = str(data.get("sourcePath") or data.get("source_path") or data.get("localPath") or data.get("local_path") or "").strip()
    encoded_upload = str(data.get("fileBase64") or data.get("file_base64") or data.get("base64") or "").strip()
    upload_name = Path(str(data.get("fileName") or data.get("file_name") or data.get("name") or "").strip()).name
    source_path: Path | None = None
    source_for_destination: Path | None = None
    upload_bytes: bytes | None = None
    original_file_name = ""
    import_method = "local-path"

    if raw_source:
        source_path = Path(raw_source)
        if not source_path.is_absolute():
            source_path = _project_root / source_path
        try:
            source_path = source_path.resolve()
        except OSError as exc:
            return jsonify({"ok": False, "error": f"invalid sourcePath: {exc}"}), 400
        if not source_path.is_file():
            return jsonify({"ok": False, "error": f"sourcePath is not a file: {raw_source}"}), 400
        if source_path.suffix.lower() not in BGM_EXTENSIONS:
            return jsonify({"ok": False, "error": f"unsupported audio extension: {source_path.suffix}"}), 400
        source_for_destination = source_path
        original_file_name = source_path.name
    else:
        if not encoded_upload:
            return jsonify({"ok": False, "error": "sourcePath or fileBase64 is required"}), 400
        if not upload_name:
            return jsonify({"ok": False, "error": "fileName is required when fileBase64 is used"}), 400
        upload_path = Path(upload_name)
        if upload_path.suffix.lower() not in BGM_EXTENSIONS:
            return jsonify({"ok": False, "error": f"unsupported audio extension: {upload_path.suffix}"}), 400
        if encoded_upload.lower().startswith("data:") and "," in encoded_upload:
            encoded_upload = encoded_upload.split(",", 1)[1]
        try:
            upload_bytes = base64.b64decode(encoded_upload, validate=True)
        except (binascii.Error, ValueError) as exc:
            return jsonify({"ok": False, "error": f"invalid fileBase64: {exc}"}), 400
        if not upload_bytes:
            return jsonify({"ok": False, "error": "fileBase64 decoded to an empty file"}), 400
        source_for_destination = upload_path
        original_file_name = upload_name
        import_method = "browser-upload"

    sidecar = _audio_sidecar_from_request(data)
    role = _audio_target_role(data, sidecar)
    if role == "voiceover":
        sidecar.setdefault("provider", "upload")
        sidecar.setdefault("kind", "voiceover")
        sidecar.setdefault("sourceOrigin", "operator-owned-voiceover")
        sidecar.setdefault("sourceLicense", "operator-owned")
        if _operator_owned_voiceover_ready(data):
            sidecar["operatorOwned"] = True
    if role == "voiceover" and not _operator_owned_voiceover_ready(sidecar):
        return jsonify({
            "ok": False,
            "error": "operatorOwned=true is required for voiceover imports",
        }), 400
    if role != "voiceover" and not _free_audio_provenance_ready(sidecar):
        return jsonify({
            "ok": False,
            "error": "sourceUrl and sourceLicense/license/licenseUrl are required for free audio provenance",
        }), 400

    try:
        if source_for_destination is None:
            return jsonify({"ok": False, "error": "audio source could not be resolved"}), 400
        role, destination = _audio_destination(source_for_destination, data, sidecar)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path is not None:
            shutil.copy2(source_path, destination)
        else:
            destination.write_bytes(upload_bytes or b"")
        sidecar.setdefault("provider", "upload" if role == "voiceover" else "local-bgm" if role == "bgm" else "local-sfx")
        sidecar["targetRole"] = role
        sidecar["originalFileName"] = original_file_name
        sidecar["importMethod"] = import_method
        sidecar["importedAt"] = datetime.now().isoformat(timespec="seconds")
        sidecar_path = destination.with_suffix(f"{destination.suffix}.json")
        sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        # Flask route handler: broad catch required to convert filesystem import
        # failures into a response while leaving the original download untouched.
        logger.warning("%s failed: %s", flask_request.path, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "asset": {
            "role": "audio" if role == "voiceover" else role,
            "path": _project_relative(destination),
            "sidecarPath": _project_relative(sidecar_path),
            "provider": sidecar.get("provider"),
            "title": sidecar.get("title"),
            "artist": sidecar.get("artist"),
            "sourceUrl": sidecar.get("sourceUrl"),
            "sourceLicense": sidecar.get("sourceLicense") or sidecar.get("license") or sidecar.get("licenseUrl"),
            "mood": sidecar.get("mood"),
            "kind": sidecar.get("kind") or ("voiceover" if role == "voiceover" else None),
            "targetRole": role,
            "operatorOwned": sidecar.get("operatorOwned") is True,
            "importMethod": import_method,
            "provenanceReady": True,
            "operatorAction": (
                "Attach this asset as the scene voiceover, then render again so the manifest records owned voice evidence."
                if role == "voiceover"
                else "Render again so the manifest records free audio provenance and BGM rotation evidence."
            ),
        },
        "sidecar": sidecar,
    })


def _scene_id(scene: dict, index: int) -> str:
    raw = scene.get("sceneId") or scene.get("scene_id") or scene.get("id")
    if raw:
        return slugify(str(raw)) or f"scene-{index + 1:02d}"
    try:
        num = int(scene.get("scene_num") or index + 1)
    except (TypeError, ValueError):
        num = index + 1
    return f"scene-{num:02d}"


def _compact_query(value: str, fallback: str) -> str:
    text = re.sub(r"https?://\S+", " ", str(value or ""))
    text = re.sub(r"[^\w가-힣\s-]", " ", text, flags=re.UNICODE)
    words = [part.strip("-_ ") for part in text.split() if len(part.strip("-_ ")) > 1]
    query = " ".join(words[:8]).strip()
    return query or fallback


def _scene_queries(scene: dict, index: int, guide: dict) -> list[str]:
    fields = [
        scene.get("image_prompt"),
        scene.get("display_text"),
        scene.get("title"),
        scene.get("narration"),
    ]
    hints = guide.get("searchHints") or ["vertical motion b-roll"]
    queries: list[str] = []
    for value in fields:
        query = _compact_query(str(value or ""), "")
        if query and query not in queries:
            queries.append(query)
    if len(queries) < 3:
        for hint in hints:
            candidate = f"{hint} {index + 1}".strip()
            if candidate not in queries:
                queries.append(candidate)
            if len(queries) >= 3:
                break
    return queries[:3] or [f"{hints[0]} {index + 1}".strip()]


def _provider_search_url(provider: str, query: str) -> str:
    encoded_path = quote(query.strip())
    encoded_query = quote_plus(query.strip())
    if provider == "pexels-video":
        return f"https://www.pexels.com/search/videos/{encoded_path}/"
    if provider == "pixabay-video":
        return f"https://pixabay.com/videos/search/{encoded_path}/"
    if provider == "wikimedia-commons":
        return f"https://commons.wikimedia.org/w/index.php?search={encoded_query}&title=Special:MediaSearch&type=video"
    if provider == "mixkit":
        return f"https://mixkit.co/free-stock-video/?q={encoded_query}"
    if provider == "freesound":
        return f"https://freesound.org/search/?q={encoded_query}"
    if provider == "youtube-audio-library":
        return "https://www.youtube.com/audiolibrary"
    if provider == "gongu-copyright":
        return f"https://gongu.copyright.or.kr/gongu/wrt/wrtCl/listWrt.do?menuNo=200020&searchWrd={encoded_query}"
    if provider == "kogl":
        return f"https://www.kogl.or.kr/recommend/recommendDivList.do?searchKeyword={encoded_query}"
    return ""


def _provider_plan(provider: str, query: str, role: str) -> dict:
    guide = _FREE_ASSET_PROVIDERS.get(provider)
    if not guide:
        return {
            "provider": provider,
            "label": provider,
            "kind": "operator/original",
            "role": role,
            "searchUrl": "",
            "requires": "Operator-supplied source; keep provenance in scene source fields.",
            "licenseNote": "Only use footage the operator has rights to use.",
            "proofFields": ["source_rationale", "originality_evidence", "quality_review_note"],
        }
    return {
        "provider": provider,
        "label": guide["label"],
        "kind": guide["kind"],
        "role": role,
        "officialUrl": guide["officialUrl"],
        "manualUrl": guide["manualUrl"],
        "searchUrl": _provider_search_url(provider, query),
        "requires": guide["requires"],
        "licenseNote": guide["licenseNote"],
        "proofFields": guide["proofFields"],
    }


def _slot_role(provider: str, slot_index: int) -> str:
    if provider in {"grok", "wan", "ltx-video", "hunyuan-video", "direct-upload"}:
        return "hero original motion"
    if provider in {"youtube-audio-library", "freesound", "gongu-copyright"}:
        return "audio or ambience"
    if provider == "kogl":
        return "public context media or evidence insert"
    if slot_index == 0:
        return "primary support b-roll"
    if slot_index == 1:
        return "alternate candidate b-roll"
    return "texture or transition insert"


def _build_free_asset_sourcing_packet(project_id: str, template_type: str, scenes: list[dict]) -> dict:
    guide = _asset_guide_for(template_type)
    layout_variants = _TEMPLATE_LAYOUT_VARIANTS.get(template_type) or _TEMPLATE_LAYOUT_VARIANTS["news_explainer"]
    selected_playbook = _template_playbook_for(template_type)
    asset_production_recipes = _asset_production_recipes_for(template_type)
    recommended_bgm_mood = _bgm_mood_for_template(template_type)
    provider_keys = list(dict.fromkeys(guide.get("providers") or []))
    preferred_sources = list(dict.fromkeys(guide.get("preferredSourceOrder") or []))
    stock_candidates = [source for source in preferred_sources if source in _FREE_ASSET_PROVIDERS]
    scene_plans: list[dict] = []

    for index, scene in enumerate(scenes):
        scene_id = _scene_id(scene, index)
        queries = _scene_queries(scene, index, guide)
        main_query = queries[0]
        slots: list[dict] = []
        for slot_index, source in enumerate(preferred_sources[:5]):
            if source == "image-ken-burns":
                slots.append({
                    "source": source,
                    "role": "last-resort still image fallback",
                    "reason": "Use only when a moving clip cannot be found or generated.",
                    "proofFields": ["why video was unavailable", "Ken Burns direction", "caption safe-zone review"],
                })
                continue
            slots.append(_provider_plan(source, queries[min(slot_index, len(queries) - 1)], _slot_role(source, slot_index)))

        scene_plans.append({
            "sceneId": scene_id,
            "title": scene.get("title") or scene.get("display_text") or f"Scene {index + 1}",
            "queries": queries,
            "preferredSourceOrder": preferred_sources,
            "layoutVariants": layout_variants,
            "assetSlots": slots,
            "candidateSearches": [
                _provider_plan(provider, query, "manual candidate search")
                for provider in provider_keys
                for query in queries[:2]
                if provider in _FREE_ASSET_PROVIDERS
            ],
            "repeatGuard": {
                "distinctKey": f"{template_type}:{scene_id}",
                "rule": "Do not reuse the same visual asset URL/id across scenes unless the quality review marks it as a deliberate callback.",
            },
            "templatePlaybook": selected_playbook,
            "assetProductionRecipes": asset_production_recipes[:3],
            "freeAssetFallbacks": selected_playbook.get("freeAssetSubstitutes") or [],
            "qualityReviewPrompts": [
                "Does the clip show the exact scene intent rather than generic related footage?",
                "Does motion continue for the usable duration without freeze/low-motion artifacts?",
                "Does the subject remain visible under the selected caption preset and Shorts UI safe zone?",
                "Is source URL, license/attribution, creator, and selection rationale captured?",
            ],
            "avoid": guide.get("avoid") or [],
        })

    return {
        "projectId": project_id,
        "templateType": template_type,
        "templateFamily": guide["family"],
        "layout": guide["layout"],
        "layoutVariants": layout_variants,
        "sourceMix": guide["sourceMix"],
        "audioMood": guide["audioMood"],
        "recommendedBgmMood": recommended_bgm_mood,
        "preferredSourceOrder": preferred_sources,
        "stockProviderOrder": stock_candidates,
        "freeAssetSources": [_provider_plan(provider, guide["searchHints"][0], "global library") for provider in provider_keys],
        "audioSources": [
            _provider_plan("youtube-audio-library", guide["audioMood"], "BGM bed"),
            _provider_plan("mixkit", guide["audioMood"], "BGM/SFX substitute"),
            _provider_plan("freesound", guide["audioMood"], "SFX/ambience"),
            _provider_plan("gongu-copyright", guide["audioMood"], "Korean BGM/SFX source"),
            _provider_plan("kogl", guide["audioMood"], "public audio/media source"),
        ],
        "assetAcquisitionMethods": _ASSET_ACQUISITION_METHODS,
        "assetProductionRecipes": asset_production_recipes,
        "evidenceSources": _EVIDENCE_SOURCES,
        "templatePlaybook": _KOREAN_TEMPLATE_PLAYBOOK,
        "selectedTemplatePlaybook": selected_playbook,
        "bgmPlan": {
            "recommendedMood": recommended_bgm_mood,
            "templateAudioMood": guide["audioMood"],
            "localLibrary": _scan_local_bgm_library(recommended_bgm_mood),
            "freeAlternatives": [
                _provider_plan("youtube-audio-library", guide["audioMood"], "BGM bed"),
                _provider_plan("mixkit", guide["audioMood"], "BGM/SFX substitute"),
                _provider_plan("freesound", guide["audioMood"], "SFX/ambience"),
                _provider_plan("gongu-copyright", guide["audioMood"], "Korean BGM/SFX source"),
                _provider_plan("kogl", guide["audioMood"], "public audio/media source"),
            ],
            "mixRule": "Narration-first. BGM must stay ducked under Edge/Windows TTS and pass audio_mix_review_note before upload.",
        },
        "scenes": scene_plans,
        "templateAlternatives": [
            {
                "templateType": key,
                "family": value["family"],
                "layout": value["layout"],
                "sourceMix": value["sourceMix"],
                "preferredSourceOrder": value["preferredSourceOrder"][:4],
            }
            for key, value in _TEMPLATE_ASSET_GUIDES.items()
        ],
        "globalRules": [
            "Zero paid API path: this route only returns manual search/source instructions and does not call paid AI or paid stock services.",
            "Prefer real moving MP4 clips. Image+Ken Burns is last resort and must explain why video was unavailable.",
            "First hook scene needs original/direct/Grok/local footage for channel-ready quality, not stock-only filler.",
            "Avoid repeated stock assets across scenes; every scene needs a distinct source URL/id or a deliberate callback note.",
            "Keep BGM/SFX provenance, license, attribution, and download date with the final packet.",
            "TTS or spoken narration is required for explainers/commentary unless the operator explicitly marks a no-voice format.",
            "Choose a template/layout family before collecting assets; do not force every project into one caption/card style.",
        ],
        "koreanYoutubePatterns": [
            "news_explainer: hook headline, context B-roll, lower-info captions, source/evidence rhythm",
            "ranking_list: numbered beats, one clip per item, short retention resets without random transitions",
            "tutorial_steps: direct proof footage or screen capture, step chips, quiet instructional narration",
            "authentic_vlog: handheld/POV texture, sparse captions, natural ambience",
            "persona_story: consistent character/place/prop bible, Grok/local original clips, no text artifacts",
            "kculture_fandom: rights-safe fan/event context, city/stage B-roll, copyright-safe music only",
            "podcast_clip: speaker-first, waveform/quote support, voice mix over decorative B-roll",
            "longform_deep_dive: chaptered evidence flow, source/data cards, restrained lower captions",
            "interview_documentary: owned interview/location proof, TTS summary only when rights are absent",
            "live_recap: direct event footage, route/point chapters, rights-safe ambience",
        ],
    }


def _free_asset_packet_markdown(packet: dict) -> str:
    lines = [
        "# Free Asset Sourcing Worksheet",
        "",
        f"- projectId: {packet.get('projectId')}",
        f"- templateType: {packet.get('templateType')}",
        f"- templateFamily: {packet.get('templateFamily')}",
        f"- createdAt: {packet.get('createdAt')}",
        f"- sourceMix: {packet.get('sourceMix')}",
        f"- recommendedBgmMood: {packet.get('recommendedBgmMood')}",
        "",
        "## Global Rules",
    ]
    lines.extend([f"- [ ] {item}" for item in packet.get("globalRules") or []] or ["- [ ] Keep every free asset source URL, license, and selection rationale."])
    selected_playbook = packet.get("selectedTemplatePlaybook") or {}
    if selected_playbook:
        lines.extend([
            "",
            "## Selected Template Playbook",
            f"- family: {selected_playbook.get('family')}",
            f"- pattern: {selected_playbook.get('pattern')}",
            f"- layout: {selected_playbook.get('layout')}",
            f"- primary assets: {', '.join(selected_playbook.get('primaryAssets') or [])}",
            f"- free substitutes: {', '.join(selected_playbook.get('freeAssetSubstitutes') or [])}",
            f"- quality gate: {selected_playbook.get('qualityGate')}",
        ])
    lines.extend(["", "## Layout Variants"])
    for variant in packet.get("layoutVariants") or []:
        lines.append(f"- {variant.get('label') or variant.get('key')}: {variant.get('scenePattern')} | captions: {variant.get('captionPlan')}")

    lines.extend(["", "## Zero-Paid Asset Production Recipes"])
    for recipe in packet.get("assetProductionRecipes") or []:
        lines.extend([
            f"### {recipe.get('label') or recipe.get('key')}",
            f"- goal: {recipe.get('goal')}",
            f"- when: {recipe.get('whenToUse')}",
            f"- tools: {', '.join(recipe.get('freeTools') or [])}",
            f"- quality gate: {recipe.get('qualityGate')}",
            "- steps:",
        ])
        lines.extend([f"  - [ ] {step}" for step in recipe.get("steps") or []])
        lines.append("- proof fields:")
        lines.extend([f"  - [ ] {field}" for field in recipe.get("proofFields") or []])

    bgm_plan = packet.get("bgmPlan") or {}
    local_library = bgm_plan.get("localLibrary") or {}
    lines.extend([
        "",
        "## BGM Plan",
        f"- mood: {bgm_plan.get('recommendedMood') or packet.get('recommendedBgmMood')}",
        f"- local library: {local_library.get('tracksWithProvenance', 0)}/{local_library.get('totalTracks', 0)} tracks with provenance",
        f"- action: {local_library.get('operatorAction') or 'Add at least two free/local BGM candidates with source/license metadata.'}",
        "- [ ] Add at least two candidates in the selected mood so BGM rotation evidence can pass.",
        "- [ ] Add sidecar metadata with sourceUrl, sourceLicense/license, creator/artist, and attribution text.",
    ])
    for source in bgm_plan.get("freeAlternatives") or []:
        url = source.get("searchUrl") or source.get("manualUrl") or source.get("officialUrl") or ""
        lines.append(f"- [ ] {source.get('label') or source.get('provider')}: {url}")

    lines.extend(["", "## Scene Asset Collection"])
    for scene in packet.get("scenes") or []:
        lines.extend([
            "",
            f"### {scene.get('sceneId')} - {scene.get('title')}",
            f"- repeat guard: {(scene.get('repeatGuard') or {}).get('rule')}",
            "- queries:",
        ])
        lines.extend([f"  - {query}" for query in scene.get("queries") or []])
        lines.append("- candidate searches:")
        for item in scene.get("candidateSearches") or []:
            url = item.get("searchUrl") or item.get("manualUrl") or item.get("officialUrl") or ""
            lines.append(f"  - [ ] {item.get('label') or item.get('provider')} ({item.get('role')}): {url}")
        lines.append("- chosen source proof:")
        for field in ("source URL/ID", "creator/artist", "license/attribution", "selection rationale", "continuity note", "caption/subject review"):
            lines.append(f"  - [ ] {field}")

    lines.extend(["", "## Evidence Sources"])
    for source in packet.get("evidenceSources") or []:
        lines.append(f"- {source.get('label')}: {source.get('url')} - {source.get('operatorUse')}")

    lines.extend([
        "",
        "## Korean YouTube Pattern Notes",
    ])
    lines.extend([f"- {item}" for item in packet.get("koreanYoutubePatterns") or []])
    return "\n".join(lines).rstrip() + "\n"


def _write_free_asset_packet_artifacts(packet: dict) -> dict:
    project_id = slugify(str(packet.get("projectId") or "free-assets")) or "free-assets"
    artifact_dir = _project_root / "storage" / "asset-packets" / project_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now().isoformat(timespec="seconds")
    packet_with_artifacts = {
        **packet,
        "createdAt": created_at,
        "artifactDir": _project_relative(artifact_dir),
        "packetPath": _project_relative(artifact_dir / "free-asset-sourcing-packet.json"),
        "worksheetPath": _project_relative(artifact_dir / "free-asset-sourcing-worksheet.md"),
    }
    packet_path = artifact_dir / "free-asset-sourcing-packet.json"
    worksheet_path = artifact_dir / "free-asset-sourcing-worksheet.md"
    packet_path.write_text(json.dumps(packet_with_artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
    worksheet_path.write_text(_free_asset_packet_markdown(packet_with_artifacts), encoding="utf-8")
    return packet_with_artifacts


@media_bp.route("/api/free-assets/sourcing-packet", methods=["POST"])
def free_asset_sourcing_packet_route():
    """Build a template-aware free asset sourcing packet without calling external APIs."""
    data = flask_request.get_json(silent=True) or {}
    template_type = str(data.get("templateType") or data.get("template_type") or "news_explainer")
    scenes = data.get("draftScenes") or data.get("scenes") or []
    if not isinstance(scenes, list) or not scenes:
        return jsonify({"ok": False, "error": "draftScenes are required"}), 400
    normalized_scenes = [scene for scene in scenes if isinstance(scene, dict)]
    if not normalized_scenes:
        return jsonify({"ok": False, "error": "draftScenes must contain scene objects"}), 400
    project_id = slugify(str(data.get("projectId") or f"free-assets-{int(time.time())}")) or "free-assets"
    packet = _build_free_asset_sourcing_packet(project_id, template_type, normalized_scenes)
    packet = _write_free_asset_packet_artifacts(packet)
    return jsonify({"ok": True, **packet})


# ---------------------------------------------------------------------------
# Pexels Video Search (RENDERING-SPEC §5.2)
# ---------------------------------------------------------------------------

@media_bp.route("/api/search-pexels-video", methods=["POST"])
def search_pexels_video_route():
    """Search Pexels for a stock video matching scene requirements.

    Input JSON: {"query": str, "min_duration": float (optional)}
    Output JSON: {"ok": true, "videos": [...], "video": first_candidate}
    """
    data = flask_request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"ok": False, "error": "query is required"}), 400

    try:
        min_duration = float(data.get("min_duration", 0))
    except (TypeError, ValueError):
        min_duration = 0.0

    try:
        per_page = int(data.get("per_page", 8))
    except (TypeError, ValueError):
        per_page = 8

    result = search_pexels_video_candidates(query, min_duration=min_duration, per_page=per_page)
    if result:
        return jsonify({"ok": True, "videos": result, "video": result[0]})
    return jsonify({"ok": False, "error": "No matching video found"}), 404


# ---------------------------------------------------------------------------
# Local video command generation (Wan / LTX / Hunyuan)
# ---------------------------------------------------------------------------

def _local_intake_scene_id(scene: dict, index: int) -> str:
    raw = scene.get("sceneId") or scene.get("scene_id") or scene.get("id")
    if raw:
        return slugify(str(raw)) or f"scene-{index + 1:02d}"
    try:
        num = int(scene.get("scene_num") or index + 1)
    except (TypeError, ValueError):
        num = index + 1
    return f"scene-{num:02d}"


def _local_intake_match_score(path: Path, scene_id: str, index: int) -> int:
    stem = path.stem.lower().replace("_", "-")
    compact = stem.replace("-", "")
    scene_key = scene_id.lower()
    scene_compact = scene_key.replace("-", "")
    scene_num = str(index + 1).zfill(2)
    if scene_key in stem or scene_compact in compact:
        return 100
    if f"scene-{scene_num}" in stem or f"scene{scene_num}" in compact:
        return 90
    if stem.startswith(scene_num) or stem.endswith(scene_num) or f"-{scene_num}-" in stem:
        return 70
    return 0


def _local_intake_assignments(video_files: list[Path], scenes: list[dict]) -> list[tuple[dict, Path, str]]:
    assignments: list[tuple[dict, Path, str]] = []
    remaining = list(video_files)
    scene_payloads = [
        {
            "sceneId": _local_intake_scene_id(scene, index),
            "index": index,
            "title": scene.get("title") or scene.get("display_text") or f"Scene {index + 1}",
        }
        for index, scene in enumerate(scenes)
    ]
    assigned_scene_ids: set[str] = set()

    for scene in scene_payloads:
        scored = [
            (_local_intake_match_score(path, str(scene["sceneId"]), int(scene["index"])), path)
            for path in remaining
        ]
        scored = [(score, path) for score, path in scored if score > 0]
        if not scored:
            continue
        scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
        score, selected = scored[0]
        remaining.remove(selected)
        assigned_scene_ids.add(str(scene["sceneId"]))
        assignments.append((scene, selected, f"filename-score:{score}"))

    for scene in scene_payloads:
        if str(scene["sceneId"]) in assigned_scene_ids or not remaining:
            continue
        selected = remaining.pop(0)
        assignments.append((scene, selected, "scene-order"))

    return assignments


@media_bp.route("/api/local-video/import-folder", methods=["POST"])
def import_local_video_folder_route():
    """Import operator-approved MP4 files from a local folder as scene assets.

    This is for local Wan/LTX/Hunyuan or other zero-paid outputs that already
    exist on disk. The route copies MP4s into project storage and does not
    delete, move, execute, or call external services.
    """
    data = flask_request.get_json(silent=True) or {}
    if not data.get("operatorApproved"):
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before importing local MP4s",
        }), 403

    source_dir_raw = str(data.get("sourceDir") or data.get("folderPath") or "").strip()
    if not source_dir_raw:
        return jsonify({"ok": False, "error": "sourceDir is required"}), 400
    source_dir = Path(source_dir_raw).expanduser()
    try:
        source_dir = source_dir.resolve()
    except OSError as exc:
        return jsonify({"ok": False, "error": f"sourceDir is unreadable: {exc}"}), 400
    if not source_dir.is_dir():
        return jsonify({"ok": False, "error": "sourceDir must be an existing folder"}), 400

    scenes = data.get("draftScenes") or data.get("scenes") or []
    if not isinstance(scenes, list) or not scenes:
        return jsonify({"ok": False, "error": "draftScenes are required"}), 400
    normalized_scenes = [scene for scene in scenes if isinstance(scene, dict)]
    if not normalized_scenes:
        return jsonify({"ok": False, "error": "draftScenes must contain scene objects"}), 400

    video_files = sorted(
        [path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"],
        key=lambda path: path.name.lower(),
    )
    if not video_files:
        return jsonify({"ok": False, "error": "sourceDir has no .mp4 files"}), 404

    project_id = slugify(str(data.get("projectId") or f"local-folder-{int(time.time())}")) or "local-folder"
    packet_dir = _project_root / "storage" / "local-video-imports" / project_id
    packet_dir.mkdir(parents=True, exist_ok=True)

    assets: list[dict] = []
    imports: list[dict] = []
    assignments = sorted(
        _local_intake_assignments(video_files, normalized_scenes),
        key=lambda item: int(item[0]["index"]),
    )
    for scene, source_path, match_method in assignments:
        scene_id = str(scene["sceneId"])
        scene_dir = packet_dir / scene_id
        scene_dir.mkdir(parents=True, exist_ok=True)
        target_path = scene_dir / f"{scene_id}.local-folder.mp4"
        shutil.copy2(source_path, target_path)
        relative_source = _project_relative(target_path)
        asset = {
            "sceneId": scene_id,
            "role": "visual",
            "fileName": target_path.name,
            "mimeType": "video/mp4",
            "sourcePath": relative_source,
            "previewUrl": _local_video_preview_url(relative_source),
            "provider": "local-folder",
            "sourceGenerator": "local-folder",
            "sourceGeneratorRequestPath": _project_relative(packet_dir / "local-folder-import.json"),
            "sourceGeneratorPromptPath": "",
            "sourceGeneratorLogPath": "",
            "sourceGeneratorCommand": None,
            "originalPath": str(source_path),
            "importMatch": match_method,
        }
        assets.append(asset)
        imports.append({
            "sceneId": scene_id,
            "title": scene.get("title"),
            "sourcePath": str(source_path),
            "targetPath": str(target_path),
            "match": match_method,
        })

    manifest = {
        "projectId": project_id,
        "sourceDir": str(source_dir),
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "operatorApproved": True,
        "zeroPaid": True,
        "mode": "local-mp4-folder-intake",
        "importedCount": len(assets),
        "availableMp4Count": len(video_files),
        "imports": imports,
    }
    manifest_path = packet_dir / "local-folder-import.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return jsonify({
        "ok": True,
        "projectId": project_id,
        "sourceDir": str(source_dir),
        "packetDir": _project_relative(packet_dir),
        "manifestPath": _project_relative(manifest_path),
        "importedCount": len(assets),
        "availableMp4Count": len(video_files),
        "assets": assets,
        "imports": imports,
    })


@media_bp.route("/api/local-video/generate-scene", methods=["POST"])
def generate_local_video_scene_route():
    """Run one operator-approved local video adapter and expose its MP4 as a scene asset.

    The route never changes environment variables and never calls a paid API. If the
    selected adapter is still in stub/off mode, it still writes prompt/request files
    and returns diagnostics so the operator can wire the local command deliberately.
    """
    data = flask_request.get_json(silent=True) or {}
    if not data.get("operatorApproved"):
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before running a local video command",
        }), 403

    provider = str(data.get("provider") or "").strip()
    if provider not in _LOCAL_VIDEO_PROVIDERS:
        return jsonify({
            "ok": False,
            "error": "provider must be one of wan, ltx-video, hunyuan-video",
        }), 400

    prompt = str(data.get("prompt") or data.get("image_prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt is required"}), 400

    scene_id = slugify(str(data.get("sceneId") or "scene-01")) or "scene-01"
    project_id = slugify(str(data.get("projectId") or "local-video")) or "local-video"
    title = str(data.get("title") or scene_id).strip() or scene_id
    try:
        duration_sec = max(1.0, min(float(data.get("durationSec", data.get("duration", 5))), 30.0))
    except (TypeError, ValueError):
        duration_sec = 5.0

    packet_dir = _project_root / "storage" / "local-video" / project_id / scene_id
    output_dir = packet_dir / "outputs"
    output_path = output_dir / f"{scene_id}.{provider}.mp4"
    prompt_path = packet_dir / f"{scene_id}.{provider}.prompt.txt"
    request_path = packet_dir / f"{scene_id}.{provider}.request.json"
    log_path = packet_dir / f"{scene_id}.{provider}.command.log"
    packet_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    command_template = None
    command_override_approved = data.get("commandOverrideApproved") is True
    if data.get("commandTemplate") is not None:
        if not command_override_approved:
            return jsonify({
                "ok": False,
                "error": "commandOverrideApproved=true is required before running a per-scene commandTemplate",
            }), 403
        command_template, template_error = parse_command_template_value(data.get("commandTemplate"), "commandTemplate")
        if template_error or not command_template:
            return jsonify({"ok": False, "error": template_error}), 400

    adapter_status = (
        probe_command_template_adapter(provider, command_template, project_root=_project_root)
        if command_template
        else probe_local_media_adapter(provider, project_root=_project_root)
    )
    prompt_path.write_text(
        "\n".join([
            title,
            "",
            prompt,
            "",
            "Vertical 9:16 MP4. No captions, logos, watermarks, or baked-in text.",
            f"Duration: {duration_sec:.2f}",
            f"Provider: {provider}",
            f"Output: {output_path}",
        ]),
        encoding="utf-8",
    )
    request_payload = {
        "projectId": project_id,
        "sceneId": scene_id,
        "title": title,
        "prompt": prompt,
        "visualKind": "video",
        "durationSec": duration_sec,
        "route": "local",
        "outputPath": str(output_path),
        "cacheDir": str(packet_dir),
        "adapter": provider,
        "adapterStatus": adapter_status.to_dict(),
        "operatorApproved": True,
        "commandOverrideApproved": command_override_approved,
        "commandTemplateSource": "request" if command_template else "adapter-env",
        "zeroPaid": True,
    }
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_local_media_adapter(
        provider,
        AdapterExecutionContext(
            adapterKey=provider,
            sceneId=scene_id,
            sceneTitle=title,
            prompt=prompt,
            durationSec=duration_sec,
            projectRoot=str(_project_root.resolve()),
            cacheDir=str(packet_dir),
            route="local",
            manifestPath="",
            promptPath=str(prompt_path),
            requestPath=str(request_path),
            logPath=str(log_path),
            outputPath=str(output_path),
        ),
        project_root=_project_root,
        command_template_override=command_template,
    )

    asset = None
    if result.status == "generated" and output_path.exists():
        relative_source = _project_relative(output_path)
        asset = {
            "sceneId": scene_id,
            "role": "visual",
            "fileName": output_path.name,
            "mimeType": "video/mp4",
            "sourcePath": relative_source,
            "previewUrl": _local_video_preview_url(relative_source),
            "provider": provider,
            "sourceGenerator": provider,
            "sourceGeneratorRequestPath": _project_relative(request_path),
            "sourceGeneratorPromptPath": _project_relative(prompt_path),
            "sourceGeneratorLogPath": _project_relative(log_path),
            "sourceGeneratorCommand": result.commandPreview or adapter_status.commandPreview,
        }

    return jsonify({
        "ok": True,
        "provider": provider,
        "projectId": project_id,
        "sceneId": scene_id,
        "adapterStatus": adapter_status.to_dict(),
        "result": result.to_dict(),
        "asset": asset,
        "requestPath": str(request_path),
        "promptPath": str(prompt_path),
        "logPath": str(log_path),
        "commandPreview": result.commandPreview or adapter_status.commandPreview,
        "status": result.status,
        "detail": result.detail,
    })


@media_bp.route("/api/local-video/preview", methods=["GET"])
def local_video_preview_route():
    source = _resolve_under_project(str(flask_request.args.get("path") or ""))
    if not source or not source.exists() or source.suffix.lower() not in {".mp4", ".mov", ".webm"}:
        return jsonify({"ok": False, "error": "path must be an existing video under the project root"}), 400
    return send_file(source, mimetype="video/mp4", conditional=True)


# ---------------------------------------------------------------------------
# Publish packet finalization
# ---------------------------------------------------------------------------

def _resolve_project_file(value: str) -> Path | None:
    if not _safe_resolve:
        return None
    return _safe_resolve(value, _project_root)


def _read_quality_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


_CURRENT_FINALIZE_REQUIRED_SECTIONS = (
    "publishReadiness",
    "channelReadiness",
    "uploadReview",
    "topTierReadiness",
    "productionReview",
)

_CURRENT_FINALIZE_REQUIRED_CHECKS = (
    "outputSpec",
    "noPlaceholders",
    "movingClipPriority",
    "sourceMotionEvidence",
    "zeroPaidProviders",
    "captionSafePresets",
    "subtitleArtifact",
    "manualSelectionEvidence",
    "continuityEvidence",
    "firstTwoSecondHook",
    "cutDensityPacing",
    "aiSlopVisualFit",
    "stockAiClipFit",
    "thumbnailFirstFrameStrength",
    "stockOnlyCaveat",
    "ttsNarrationEvidence",
    "voicePolicyCompliance",
    "captionLayoutReview",
    "captionDensityAndSafeZone",
    "assetReuseDiversity",
    "freeAssetProvenance",
    "bgmAssetRotation",
    "bgmSoundQuality",
    "templateSourcePlan",
    "publishReadinessGate",
    "channelReadinessGate",
    "uploadReviewGate",
    "topTierReadinessGate",
)


def _quality_report_freshness(report: dict) -> dict:
    """Return whether a render report was produced by the current QA gate."""
    missing_sections = [
        key
        for key in _CURRENT_FINALIZE_REQUIRED_SECTIONS
        if not isinstance(report.get(key), dict)
    ]
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    missing_checks = [key for key in _CURRENT_FINALIZE_REQUIRED_CHECKS if key not in checks]
    ok = not missing_sections and not missing_checks
    return {
        "ok": ok,
        "missingSections": missing_sections,
        "missingChecks": missing_checks,
        "requiredFixes": [] if ok else [
            (
                "Re-render with the current quality gate before finalizing: "
                f"missingSections={missing_sections}, missingChecks={missing_checks}"
            )
        ],
        "recommendedFixes": [] if ok else [
            "Old publish-ready packets must be regenerated so TTS narration, caption layout, asset diversity, provenance, channel readiness, upload review, and top-tier readiness are all evaluated.",
        ],
    }


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_project_root.resolve()))
    except ValueError:
        return str(path)


def _write_publish_checklist(path: Path, report: dict, final_video: Path, final_report: Path) -> None:
    readiness = report.get("publishReadiness") or {}
    channel_readiness = report.get("channelReadiness") or {}
    upload_review = report.get("uploadReview") or {}
    top_tier_readiness = report.get("topTierReadiness") or {}
    criteria = readiness.get("criteria") or []
    channel_criteria = channel_readiness.get("criteria") or []
    upload_criteria = upload_review.get("criteria") or []
    top_tier_criteria = top_tier_readiness.get("criteria") or []
    required = readiness.get("requiredFixes") or []
    recommended = readiness.get("recommendedFixes") or []
    channel_required = channel_readiness.get("requiredFixes") or []
    channel_recommended = channel_readiness.get("recommendedFixes") or []
    upload_required = upload_review.get("requiredFixes") or []
    upload_manual = upload_review.get("manualReviewItems") or []
    top_tier_required = top_tier_readiness.get("requiredFixes") or []
    lines = [
        "# Video Studio Publish Checklist",
        "",
        f"- projectId: {report.get('projectId') or 'unknown'}",
        f"- generatedAt: {datetime.now().isoformat(timespec='seconds')}",
        f"- publishReadiness: {readiness.get('status') or 'unknown'}",
        f"- channelReadiness: {channel_readiness.get('status') or 'unknown'}",
        f"- uploadReview: {upload_review.get('status') or 'unknown'}",
        f"- topTierReadiness: {top_tier_readiness.get('status') or 'unknown'}",
        f"- finalVideo: {_relative_or_absolute(final_video)}",
        f"- qualityReport: {_relative_or_absolute(final_report)}",
        "",
        "## Required Fixes",
    ]
    lines.extend([f"- {item}" for item in required] or ["- none"])
    lines.extend(["", "## Recommended Fixes"])
    lines.extend([f"- {item}" for item in recommended] or ["- none"])
    lines.extend(["", "## Criteria"])
    for item in criteria:
        marker = "required" if item.get("required") else "recommended"
        lines.append(f"- [{item.get('status')}] {item.get('label')} ({marker}) - {item.get('detail')}")
    lines.extend(["", "## Channel Required Fixes"])
    lines.extend([f"- {item}" for item in channel_required] or ["- none"])
    lines.extend(["", "## Channel Recommended Fixes"])
    lines.extend([f"- {item}" for item in channel_recommended] or ["- none"])
    lines.extend(["", "## Channel Criteria"])
    for item in channel_criteria:
        marker = "required" if item.get("required") else "recommended"
        lines.append(f"- [{item.get('status')}] {item.get('label')} ({marker}) - {item.get('detail')}")
    lines.extend(["", "## Upload Required Fixes"])
    lines.extend([f"- {item}" for item in upload_required] or ["- none"])
    lines.extend(["", "## Upload Manual Review"])
    lines.extend([f"- {item}" for item in upload_manual] or ["- none"])
    lines.extend(["", "## Upload Criteria"])
    for item in upload_criteria:
        marker = "required" if item.get("required") else "manual"
        lines.append(f"- [{item.get('status')}] {item.get('label')} ({marker}) - {item.get('detail')}")
    lines.extend(["", "## Top-Tier Required Fixes"])
    lines.extend([f"- {item}" for item in top_tier_required] or ["- none"])
    lines.extend(["", "## Top-Tier Criteria"])
    for item in top_tier_criteria:
        lines.append(f"- [{item.get('status')}] {item.get('label')} (required) - {item.get('detail')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _publish_decision(report: dict, quality_audit: dict) -> dict:
    publish = report.get("publishReadiness") or {}
    channel = report.get("channelReadiness") or {}
    upload = report.get("uploadReview") or {}
    checks = report.get("checks") or {}
    rerender_keys = {
        "outputSpec",
        "noPlaceholders",
        "movingClipPriority",
        "sourceMotionEvidence",
        "captionSafePresets",
        "captionDensityAndSafeZone",
    }
    failed_rerender = [
        key
        for key in rerender_keys
        if (checks.get(key) or {}).get("status") == "fail"
    ]
    if failed_rerender or publish.get("status") == "blocked":
        return {
            "key": "rerender-required",
            "label": "재렌더 필요",
            "reason": f"blocking checks: {', '.join(failed_rerender) or publish.get('status')}",
        }
    if (
        publish.get("status") == "ready"
        and channel.get("status") == "channel-ready"
        and upload.get("status") == "ready"
    ):
        return {
            "key": "artifact-packet-ready",
            "label": "패킷 준비",
            "reason": "publish/channel/upload artifact gates are ready; same-day upload still requires final-library pre-upload evidence",
            "scope": "artifact-packet",
            "uploadApproval": False,
            "sameDayUploadApproval": False,
        }
    summary = quality_audit.get("summary") if isinstance(quality_audit.get("summary"), dict) else {}
    return {
        "key": "needs-edit",
        "label": "수정 필요",
        "reason": summary.get("benchmarkGap") or "manual checklist or channel gate still needs attention",
    }


def _template_hashtags(template_type: str) -> list[str]:
    normalized = str(template_type or "").strip()
    if normalized == "authentic_vlog":
        return ["#shorts", "#reels", "#tiktok", "#퇴근루틴", "#브이로그"]
    if normalized == "ranking_list":
        return ["#shorts", "#top3", "#랭킹", "#리스트", "#생활루틴"]
    if normalized in {"longform_deep_dive", "interview_documentary"}:
        return ["#youtube", "#deepdive", "#documentary", "#explainer"]
    return ["#shorts", "#reels", "#tiktok", "#정보", "#핵심정리"]


def _title_candidates(report: dict) -> list[str]:
    production = report.get("productionReview") or {}
    scenes = production.get("scenes") or []
    summary = production.get("summary") or {}
    template = str(summary.get("contentTemplate") or report.get("templateType") or "").strip()
    project_title = str(report.get("projectId") or "Video Studio").replace("-", " ").strip()
    first_scene = scenes[0] if scenes else {}
    hook = str(first_scene.get("hookNote") or first_scene.get("sourceRationale") or "").strip()
    scene_label = str(first_scene.get("sceneId") or "첫 장면").strip()
    base = project_title[:70] or "Video Studio"
    if template == "ranking_list":
        return [
            "퇴근 후 바로 하는 리셋 루틴 TOP 5",
            "집 오자마자 하기 좋은 5가지",
            "피곤한 날 몸 풀리는 루틴 5위부터",
        ]
    if template == "authentic_vlog":
        return [
            f"{base}: 말 없이 보는 루틴",
            f"퇴근 후 15초 리셋 루틴",
            f"{scene_label}에서 시작하는 하루 마감",
        ]
    if template in {"news_explainer", "myth_buster", "tutorial_steps", "hot_take", "podcast_clip"}:
        return [
            "퇴근 후 15초 리셋 루틴",
            "집에 오자마자 몸이 풀리는 5단계",
            "오늘 피로 줄이는 짧은 루틴",
        ]
    return [
        f"{base}: 핵심만 20초",
        f"{base} 첫 장면부터 결론",
        hook[:48] if len(hook) >= 12 else f"{base} 업로드 후보",
    ]


def _description_text(report: dict, final_video: Path) -> str:
    production = report.get("productionReview") or {}
    template_review = production.get("templateSourceReview") or {}
    summary = production.get("summary") or {}
    audio_credits = summary.get("youtubeDescriptionAudioCredits") or []
    template = str(template_review.get("template") or summary.get("contentTemplate") or "").strip()
    if template == "ranking_list":
        intro = "퇴근 후 바로 따라 하기 좋은 리셋 루틴 TOP 5입니다. 각 순위는 움직이는 Grok MP4와 짧은 음성 설명으로 확인했습니다."
    elif template in {"news_explainer", "myth_buster", "tutorial_steps", "hot_take", "podcast_clip"}:
        intro = "퇴근 직후 길게 생각하지 않고 바로 시작할 수 있는 15초 리셋 루틴입니다. 한 장면에 한 행동만 담았습니다."
    elif template == "authentic_vlog":
        intro = "퇴근 후 조용히 정리되는 짧은 루틴 기록입니다."
    else:
        intro = "짧은 모바일 업로드용 Video Studio 후보입니다."
    lines = [
        intro,
        "",
        f"Final MP4: {_relative_or_absolute(final_video)}",
        f"Template: {template_review.get('template') or summary.get('contentTemplate') or 'unknown'}",
        f"Source mix: {template_review.get('sourceMix') or 'direct/Grok/local/free source mix'}",
        "Created with zero-paid Video Studio workflow. Manual source/provenance review is required before upload.",
    ]
    if audio_credits:
        lines.extend(["", "Audio credits:"])
        lines.extend([f"- {credit}" for credit in audio_credits])
    return "\n".join(lines)


def _publish_scene_review(report: dict) -> list[dict]:
    production = report.get("productionReview") or {}
    scenes = production.get("scenes") or []
    summary = production.get("summary") or {}
    first_scene = scenes[0] if scenes else {}
    first_scene_id = str(summary.get("firstSceneId") or first_scene.get("sceneId") or "scene-01")
    rows: list[dict] = []
    for scene in scenes:
        scene_id = str(scene.get("sceneId") or "")
        source_intent = str(scene.get("sourceIntent") or scene.get("visualProvider") or "")
        source_rail = (
            "Grok"
            if source_intent == "grok"
            else "local"
            if source_intent in {"wan", "ltx-video", "hunyuan-video"}
            else "direct"
            if scene.get("visualProvider") == "upload"
            else "stock"
            if scene.get("visualProvider") == "pexels-video"
            else source_intent or "media"
        )
        caveats = scene.get("caveats") or []
        rows.append({
            "sceneId": scene_id,
            "decision": "pass" if not caveats and scene.get("visualQualityVerdictStatus") == "pass" else "review",
            "sourceRail": source_rail,
            "visualProvider": scene.get("visualProvider"),
            "selectedFileName": scene.get("selectedFileName"),
            "candidateCount": scene.get("candidateCount"),
            "selectedCandidateSummary": scene.get("selectedCandidateSummary"),
            "sourceProvenanceStatus": scene.get("sourceProvenanceStatus"),
            "sourceProvenanceConfirmed": scene.get("sourceProvenanceConfirmed"),
            "captionSafeZone": {
                "preset": scene.get("captionPreset"),
                "durationSec": scene.get("captionDurationSec"),
                "status": "pass" if scene.get("captionPreset") in {"none", "center-short", "top-hook", "lower-info"} else "review",
            },
            "firstHook": {
                "status": "pass" if scene_id == first_scene_id and (scene.get("hookNote") or scene.get("captionPreset") == "top-hook") else ("n/a" if scene_id != first_scene_id else "review"),
                "note": scene.get("hookNote"),
            },
            "audioMix": {
                "status": "pass" if scene.get("audioMixReviewNote") else "review",
                "note": scene.get("audioMixReviewNote"),
                "mode": scene.get("audioDesignMode"),
            },
            "watermarkLogoCompression": {
                "status": "pass" if scene.get("visualQualityVerdictStatus") == "pass" else "review",
                "note": scene.get("qualityReviewNote"),
            },
            "stockRelevance": {
                "status": "pass" if source_rail != "stock" or not caveats else "review",
                "note": scene.get("sourceRationale"),
            },
            "caveats": caveats,
        })
    return rows


def _operator_upload_checklist(report: dict, quality_audit: dict) -> list[dict]:
    audit_items = quality_audit.get("checklist") if isinstance(quality_audit.get("checklist"), list) else []
    wanted = {
        "firstTwoSecondHook",
        "captionSafeZone",
        "captionSubjectClear",
        "audioMixNotTooLoud",
        "noWatermarkLogoCompression",
        "stockCandidateCuration",
        "voicePolicyCompliance",
        "bgmSoundQuality",
        "manualSelectionEvidence",
        "youtubeBenchmarkGap",
    }
    checklist = [
        {
            "key": item.get("key"),
            "label": item.get("label"),
            "status": item.get("status"),
            "detail": item.get("detail"),
            "source": item.get("source"),
        }
        for item in audit_items
        if item.get("key") in wanted
    ]
    upload = report.get("uploadReview") or {}
    for item in upload.get("criteria") or []:
        checklist.append({
            "key": item.get("key"),
            "label": item.get("label"),
            "status": item.get("status"),
            "detail": item.get("detail"),
            "source": "uploadReview.criteria",
        })
    return checklist


def _build_publish_packet(
    report: dict,
    final_video: Path,
    final_report: Path,
    quality_audit: dict,
    review_frames: list[Path],
    contact_sheet: Path | None,
    audio_level: dict,
) -> dict:
    production = report.get("productionReview") or {}
    summary = production.get("summary") or {}
    template_review = production.get("templateSourceReview") or {}
    operating_template = report.get("operatingTemplate") or template_review.get("operatingTemplate") or operating_template_for(str(summary.get("contentTemplate") or ""))
    required_fixes = (
        list((report.get("publishReadiness") or {}).get("requiredFixes") or [])
        + list((report.get("channelReadiness") or {}).get("requiredFixes") or [])
        + list((report.get("uploadReview") or {}).get("requiredFixes") or [])
        + list((report.get("topTierReadiness") or {}).get("requiredFixes") or [])
    )
    recommended_fixes = (
        list((report.get("publishReadiness") or {}).get("recommendedFixes") or [])
        + list((report.get("channelReadiness") or {}).get("recommendedFixes") or [])
        + list((report.get("topTierReadiness") or {}).get("recommendedFixes") or [])
    )
    shortcomings = [item for item in dict.fromkeys(required_fixes + recommended_fixes) if item]
    decision = _publish_decision(report, quality_audit)
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    production_summary = summary if isinstance(summary, dict) else {}
    return {
        "projectId": report.get("projectId") or final_video.parent.name,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "decision": decision,
        "decisionScope": "artifact-packet",
        "preUploadBoundary": (
            "Publish packet decisions are artifact-scoped. Same-day upload approval is only the final-library "
            "preUploadDecision after fresh-source proof and phone-sized human review."
        ),
        "sameDayUploadDecision": {
            "status": "requires-final-library-evidence",
            "label": "사전 업로드 증거 필요",
            "reason": "This packet is not upload approval; use the final-video-library preUploadDecision for same-day upload.",
        },
        "finalMp4": str(final_video),
        "qualityReport": str(final_report),
        "qualityAudit": str(final_video.parent / "quality-audit.json"),
        "thumbnailCandidates": {
            "firstFrame": str(review_frames[0]) if review_frames else None,
            "reviewFrames": [str(path) for path in review_frames],
            "contactSheet": str(contact_sheet) if contact_sheet else None,
            "rule": operating_template.get("thumbnailFirstFrameRule"),
        },
        "titleCandidates": _title_candidates(report),
        "description": _description_text(report, final_video),
        "hashtags": _template_hashtags(str(summary.get("contentTemplate") or template_review.get("template") or "")),
        "operatingTemplate": operating_template,
        "sceneReview": _publish_scene_review(report),
        "uploadChecklist": _operator_upload_checklist(report, quality_audit),
        "liveChannelFailureReview": {
            "automaticGateIsNotUploadApproval": True,
            "placeholderBgm": checks.get("bgmSoundQuality") or {},
            "voicePolicy": checks.get("voicePolicyCompliance") or {},
            "captionSafeZone": checks.get("captionDensityAndSafeZone") or {},
            "aiSlopVisualFit": checks.get("aiSlopVisualFit") or {},
            "stockAiClipFit": checks.get("stockAiClipFit") or {},
            "firstTwoSecondHook": checks.get("firstTwoSecondHook") or {},
            "cutDensityPacing": checks.get("cutDensityPacing") or {},
            "thumbnailFirstFrameStrength": checks.get("thumbnailFirstFrameStrength") or {},
            "firstSceneHookReady": production_summary.get("firstSceneHookReady"),
            "shortsCutDensityReady": production_summary.get("shortsCutDensityReady"),
            "thumbnailFirstFrameReady": production_summary.get("thumbnailFirstFrameReady"),
            "visualVerdictFailures": production_summary.get("failedVisualVerdictScenes") or [],
        },
        "shortcomings": shortcomings,
        "nextImprovementActions": [
            action.get("operatorAction") or action.get("label") or action.get("key")
            for action in _final_packet_next_actions(
                has_video=final_video.exists(),
                has_quality_audit=True,
                ffprobe=_run_final_video_ffprobe(final_video),
                flags=_final_packet_flags(quality_audit, report),
            )
        ],
        "audioLevel": audio_level,
    }


def _write_publish_packet_markdown(path: Path, packet: dict) -> None:
    decision = packet.get("decision") or {}
    thumbnail = packet.get("thumbnailCandidates") or {}
    operating_template = packet.get("operatingTemplate") or {}
    lines = [
        "# Video Studio Publish Packet",
        "",
        f"- projectId: {packet.get('projectId')}",
        f"- decision: {decision.get('label')} ({decision.get('key')})",
        f"- finalMp4: {packet.get('finalMp4')}",
        f"- firstFrame: {thumbnail.get('firstFrame') or 'not extracted'}",
        f"- contactSheet: {thumbnail.get('contactSheet') or 'not extracted'}",
        f"- operatingTemplate: {operating_template.get('label') or operating_template.get('key') or 'unknown'}",
        "",
        "## Title Candidates",
    ]
    lines.extend([f"- {item}" for item in packet.get("titleCandidates") or []] or ["- TBD"])
    lines.extend(["", "## Description", "", packet.get("description") or ""])
    lines.extend(["", "## Hashtags"])
    lines.append(" ".join(packet.get("hashtags") or []))
    lines.extend(["", "## Upload Checklist"])
    for item in packet.get("uploadChecklist") or []:
        lines.append(f"- [{item.get('status')}] {item.get('label')} - {item.get('detail')}")
    lines.extend(["", "## Scene Review"])
    for scene in packet.get("sceneReview") or []:
        lines.append(
            f"- {scene.get('sceneId')}: {scene.get('decision')} / {scene.get('sourceRail')} / "
            f"caption {((scene.get('captionSafeZone') or {}).get('status'))} / "
            f"audio {((scene.get('audioMix') or {}).get('status'))} / "
            f"file {scene.get('selectedFileName') or 'n/a'}"
        )
    live_failures = packet.get("liveChannelFailureReview") or {}
    lines.extend(["", "## Live Channel Failure Review"])
    for key in [
        "placeholderBgm",
        "voicePolicy",
        "captionSafeZone",
        "aiSlopVisualFit",
        "stockAiClipFit",
        "firstTwoSecondHook",
        "cutDensityPacing",
        "thumbnailFirstFrameStrength",
    ]:
        check = live_failures.get(key) or {}
        lines.append(f"- {key}: {check.get('status') or 'unknown'} - {check.get('detail') or ''}")
    lines.append(f"- automaticGateIsNotUploadApproval: {live_failures.get('automaticGateIsNotUploadApproval')}")
    lines.extend(["", "## Shortcomings"])
    lines.extend([f"- {item}" for item in packet.get("shortcomings") or []] or ["- none"])
    lines.extend(["", "## Next Improvement Actions"])
    lines.extend([f"- {item}" for item in packet.get("nextImprovementActions") or []] or ["- Human publish review"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report_duration_seconds(report: dict) -> float | None:
    try:
        duration = (((report.get("ffprobe") or {}).get("raw") or {}).get("format") or {}).get("duration")
        parsed = float(duration)
    except (TypeError, ValueError, AttributeError):
        return None
    return parsed if parsed > 0 else None


def _run_ffmpeg_command(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            cwd=_project_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("final packet ffmpeg artifact command failed to start: %s", exc)
        return None


def _extract_review_frames(final_video: Path, final_dir: Path, report: dict) -> tuple[list[Path], Path | None]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return [], None

    duration = _report_duration_seconds(report) or 9.0
    times = [0.5, max(0.5, duration * 0.45), max(0.5, duration - 0.75)]
    frame_paths: list[Path] = []
    for index, timestamp in enumerate(times, start=1):
        frame_path = final_dir / f"review-frame-{index:02d}.jpg"
        result = _run_ffmpeg_command([
            ffmpeg,
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(final_video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(frame_path),
        ])
        if result and result.returncode == 0 and frame_path.exists():
            frame_paths.append(frame_path)

    contact_sheet = None
    if len(frame_paths) >= 2:
        contact_sheet_path = final_dir / "contact-sheet.jpg"
        args = [ffmpeg, "-y"]
        for frame_path in frame_paths:
            args.extend(["-i", str(frame_path)])
        args.extend([
            "-filter_complex",
            f"hstack=inputs={len(frame_paths)}",
            "-q:v",
            "3",
            str(contact_sheet_path),
        ])
        result = _run_ffmpeg_command(args)
        if result and result.returncode == 0 and contact_sheet_path.exists():
            contact_sheet = contact_sheet_path

    return frame_paths, contact_sheet


def _measure_audio_level(final_video: Path) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg not found"}
    result = _run_ffmpeg_command([
        ffmpeg,
        "-hide_banner",
        "-i",
        str(final_video),
        "-filter:a",
        "volumedetect",
        "-f",
        "null",
        os.devnull,
    ])
    if not result or result.returncode != 0:
        return {"ok": False, "error": "volumedetect failed"}
    output = f"{result.stdout}\n{result.stderr}"
    mean_match = re.search(r"mean_volume:\s*([-0-9.]+)\s*dB", output)
    max_match = re.search(r"max_volume:\s*([-0-9.]+)\s*dB", output)
    return {
        "ok": bool(mean_match and max_match),
        "meanVolumeDb": float(mean_match.group(1)) if mean_match else None,
        "maxVolumeDb": float(max_match.group(1)) if max_match else None,
    }


def _write_final_quality_checklist(
    path: Path,
    report: dict,
    final_video: Path,
    frame_paths: list[Path],
    contact_sheet: Path | None,
    audio_level: dict,
) -> None:
    publish = report.get("publishReadiness") or {}
    channel = report.get("channelReadiness") or {}
    upload = report.get("uploadReview") or {}
    top_tier = report.get("topTierReadiness") or {}
    production = report.get("productionReview") or {}
    production_summary = production.get("summary") or {}
    channel_summary = channel.get("summary") or {}
    upload_summary = upload.get("summary") if isinstance(upload.get("summary"), dict) else {}
    checks = report.get("checks") or {}

    def check_line(key: str, label: str) -> str:
        item = checks.get(key) or {}
        return f"- {label}: {str(item.get('status') or 'unknown').upper()} - {item.get('detail') or ''}".rstrip()

    ai_hero_ready = channel_summary.get("heroAiOrLocalReady") is True
    original_hero_ready = channel_summary.get("heroOriginalClipReady") is True
    missing_free_visual = production_summary.get("missingFreeAssetProvenanceScenes") or []
    missing_free_audio = production_summary.get("missingFreeAudioProvenanceAssets") or []
    lines = [
        "# Final Upload Quality Checklist",
        "",
        f"- projectId: {report.get('projectId') or 'unknown'}",
        f"- finalVideo: {_relative_or_absolute(final_video)}",
        f"- generatedAt: {datetime.now().isoformat(timespec='seconds')}",
        f"- publishReadiness: {publish.get('status') or 'unknown'}",
        f"- channelReadiness: {channel.get('status') or 'unknown'}",
        f"- uploadReview: {upload.get('status') or 'unknown'}",
        f"- topTierReadiness: {top_tier.get('status') or 'unknown'}",
        "",
        "## Automated Evidence",
        check_line("outputSpec", "1080x1920 / 30fps / audio stream"),
        check_line("noPlaceholders", "No placeholder media"),
        check_line("movingClipPriority", "Moving clip priority"),
        check_line("sourceMotionEvidence", "Source MP4 motion evidence"),
        check_line("captionSafePresets", "Caption safe-zone presets"),
        check_line("ttsNarrationEvidence", "Viewer audio design evidence (voiceover or intentional no-voice bed)"),
        check_line("voicePolicyCompliance", "Template voice policy"),
        check_line("captionLayoutReview", "Caption layout review"),
        check_line("assetReuseDiversity", "Visual asset reuse diversity"),
        check_line("freeAssetProvenance", "Free asset source provenance"),
        check_line("bgmAssetRotation", "BGM rotation / reuse evidence"),
        check_line("bgmSoundQuality", "BGM sound quality"),
        check_line("uploadReviewGate", "Upload review gate"),
        check_line("topTierReadinessGate", "Top-tier readiness gate"),
        f"- reviewFrames: {len(frame_paths)}",
        f"- contactSheet: {_relative_or_absolute(contact_sheet) if contact_sheet else 'unavailable'}",
        f"- audioLevel: mean={audio_level.get('meanVolumeDb')} dB, max={audio_level.get('maxVolumeDb')} dB, ok={audio_level.get('ok')}",
        "",
        "## Human Upload Checklist",
        f"- Placeholder 없음: {'PASS' if (checks.get('noPlaceholders') or {}).get('status') == 'pass' else 'CHECK'}",
        f"- 무관한 스톡 컷 없음: {'PASS' if not production_summary.get('stockOnly') else 'CHECK'}",
        f"- 움직임 없는 이미지 슬라이드쇼 아님: {'PASS' if (checks.get('movingClipPriority') or {}).get('status') == 'pass' else 'CHECK'}",
        f"- 씬 간 색감/톤/카메라 움직임 일관성: {'PASS' if not production_summary.get('missingContinuityScenes') else 'CHECK'}",
        f"- 자막 safe zone 준수: {'PASS' if (checks.get('captionSafePresets') or {}).get('status') == 'pass' else 'CHECK'}",
        f"- 자막이 핵심 피사체를 가리지 않음: {'PASS' if upload.get('status') == 'ready' else 'CHECK'}",
        f"- 워터마크/로고/저품질 압축 티 없음: {'PASS' if not production_summary.get('missingQualityReviewScenes') else 'CHECK'}",
        f"- BGM/voice/native audio 볼륨 과하지 않음: {'PASS' if audio_level.get('ok') and (audio_level.get('maxVolumeDb') is None or audio_level.get('maxVolumeDb') <= -1.0) else 'CHECK'}",
        f"- 오디오 설계가 자연스러움(TTS 또는 no-voice BGM/native audio): {'PASS' if (checks.get('ttsNarrationEvidence') or {}).get('status') == 'pass' else 'CHECK'}",
        f"- 정보/랭킹 템플릿 voice policy 준수: {'PASS' if (checks.get('voicePolicyCompliance') or {}).get('status') == 'pass' else 'CHECK'}",
        f"- 첫 2초 hook 있음: {'PASS' if production_summary.get('firstSceneHookReady') else 'CHECK'}",
        f"- 컷 전환 자연스러움: {'PASS' if not production_summary.get('missingQualityReviewScenes') and not production_summary.get('repeatedVisualAssetScenes') else 'CHECK'}",
        f"- AI가 대충 만든 느낌을 줄이는 수동 선택 근거 있음: {'PASS' if not production_summary.get('missingRationaleScenes') else 'CHECK'}",
        f"- 같은 무료 에셋 반복 사용 없음: {'PASS' if not production_summary.get('repeatedVisualAssetScenes') else 'CHECK'}",
        f"- 같은 BGM 기본 트랙 반복 사용 없음: {'PASS' if (checks.get('bgmAssetRotation') or {}).get('status') == 'pass' else 'CHECK'}",
        f"- beep/click/test-tone BGM 아님: {'PASS' if (checks.get('bgmSoundQuality') or {}).get('status') == 'pass' else 'CHECK'}",
        f"- 무료 영상/BGM/SFX 출처/라이선스 검수 가능: {'PASS' if not missing_free_visual and not missing_free_audio else 'CHECK'}",
        f"- 템플릿/레이아웃 유형이 의도적으로 선택됨: {production_summary.get('contentTemplate') or 'CHECK'}",
        "",
        "## YouTube AI-Assisted Benchmark Gap",
        f"- Original hero MP4 ready: {original_hero_ready}",
        f"- Grok/local AI hero ready: {ai_hero_ready}",
        f"- Top-tier readiness: {top_tier.get('status') or 'unknown'}",
        "- If Grok/local AI hero is false, this packet may be upload-ready but still needs a stronger generative hero shot before claiming top-tier AI-assisted Shorts quality.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _quality_status(condition: bool) -> str:
    return "pass" if condition else "check"


def _audit_nested_value(source: dict, path: tuple[str, ...]) -> object:
    current: object = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _audit_metric_number(value: object) -> int | None:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _audit_scene_count(source: dict, paths: list[tuple[str, ...]]) -> int:
    for path in paths:
        value = _audit_nested_value(source, path)
        if isinstance(value, list):
            scene_ids = {str(item).strip() for item in value if str(item or "").strip()}
            return len(scene_ids)
        number = _audit_metric_number(value)
        if number is not None:
            return number
    return 0


def _audit_first_number(source: dict, paths: list[tuple[str, ...]]) -> int:
    for path in paths:
        number = _audit_metric_number(_audit_nested_value(source, path))
        if number is not None:
            return number
    return 0


def _quality_gate_blocker_count(audit: dict) -> int:
    blockers: list[str] = []
    checks_needed = _audit_nested_value(audit, ("summary", "checksNeeded"))
    if isinstance(checks_needed, list):
        blockers.extend(f"summary:{item}" for item in _clean_string_list(checks_needed))
    for section_key in ("publishReadiness", "channelReadiness", "uploadReview", "topTierReadiness"):
        section = audit.get(section_key)
        if not isinstance(section, dict):
            continue
        required_fixes = _clean_string_list(section.get("requiredFixes"))
        blockers.extend(f"{section_key}:{item}" for item in required_fixes)
        status = str(section.get("status") or "").strip()
        ready_status = "top-tier-ready" if section_key == "topTierReadiness" else (
            "channel-ready" if section_key == "channelReadiness" else "ready"
        )
        if status and status != ready_status and not required_fixes:
            blockers.append(f"{section_key}:status={status}")
    if not blockers:
        evidence = audit.get("automatedEvidence")
        if isinstance(evidence, dict):
            for key, value in evidence.items():
                if isinstance(value, dict) and value.get("status") == "fail":
                    blockers.append(f"automatedEvidence.{key}")
    return len(set(blockers))


def _quality_gate_metrics(audit: dict) -> dict:
    metrics = {
        "acceptedScenes": _audit_scene_count(audit, [
            ("summary", "acceptedSceneIds"),
            ("summary", "originalClipSceneIds"),
            ("topTierReadiness", "summary", "originalClipSceneIds"),
            ("channelReadiness", "summary", "originalClipSceneIds"),
            ("uploadReview", "summary", "originalClipSceneIds"),
            ("topTierReadiness", "summary", "originalClipScenes"),
            ("channelReadiness", "summary", "originalClipScenes"),
            ("uploadReview", "summary", "originalClipScenes"),
        ]),
        "qualityScore": _audit_first_number(audit, [
            ("summary", "qualityScore"),
            ("summary", "passed"),
            ("topTierReadiness", "score", "passed"),
            ("uploadReview", "score", "passed"),
            ("channelReadiness", "score", "passed"),
            ("publishReadiness", "score", "passed"),
        ]),
        "blockerCount": _quality_gate_blocker_count(audit),
        "originalSceneCount": _audit_scene_count(audit, [
            ("topTierReadiness", "summary", "originalClipSceneIds"),
            ("channelReadiness", "summary", "originalClipSceneIds"),
            ("uploadReview", "summary", "originalClipSceneIds"),
            ("topTierReadiness", "summary", "originalClipScenes"),
            ("channelReadiness", "summary", "originalClipScenes"),
            ("uploadReview", "summary", "originalClipScenes"),
        ]),
        "stockSceneCount": _audit_scene_count(audit, [
            ("topTierReadiness", "summary", "stockVideoSceneIds"),
            ("channelReadiness", "summary", "stockVideoSceneIds"),
            ("topTierReadiness", "summary", "stockVideoScenes"),
            ("channelReadiness", "summary", "stockVideoScenes"),
            ("uploadReview", "summary", "stockVideoScenes"),
        ]),
        "visualVerdictPassScenes": _audit_scene_count(audit, [
            ("topTierReadiness", "summary", "visualVerdictScenes"),
            ("channelReadiness", "summary", "visualVerdictScenes"),
            ("uploadReview", "summary", "visualVerdictScenes"),
        ]),
        "visualVerdictMissingScenes": _audit_scene_count(audit, [
            ("topTierReadiness", "summary", "missingVisualVerdictScenes"),
            ("channelReadiness", "summary", "missingVisualVerdictScenes"),
            ("uploadReview", "summary", "missingVisualVerdictScenes"),
        ]),
        "visualVerdictFailedScenes": _audit_scene_count(audit, [
            ("topTierReadiness", "summary", "failedVisualVerdictScenes"),
            ("channelReadiness", "summary", "failedVisualVerdictScenes"),
            ("uploadReview", "summary", "failedVisualVerdictScenes"),
        ]),
    }
    return metrics


def _quality_gate_hard_failures(audit: dict) -> list[str]:
    failures: list[str] = []
    readiness_expectations = {
        "publishReadiness": "ready",
        "channelReadiness": "channel-ready",
        "uploadReview": "ready",
        "topTierReadiness": "top-tier-ready",
    }
    for section_key, ready_status in readiness_expectations.items():
        section = audit.get(section_key)
        if not isinstance(section, dict):
            continue
        status = str(section.get("status") or "").strip()
        if status and status != ready_status:
            failures.append(f"{section_key}:status={status}")
        for item in _clean_string_list(section.get("requiredFixes")):
            failures.append(f"{section_key}:{item}")

    evidence = audit.get("automatedEvidence")
    if isinstance(evidence, dict):
        for key, value in evidence.items():
            if isinstance(value, dict) and value.get("status") == "fail":
                failures.append(f"{key}:{value.get('detail') or 'failed'}")
    return sorted(set(failures))


def _attach_quality_gate_fields(audit: dict) -> dict:
    audit["metrics"] = _quality_gate_metrics(audit)
    hard_failures = _quality_gate_hard_failures(audit)
    if hard_failures:
        audit["hardFailures"] = hard_failures
    else:
        audit.pop("hardFailures", None)
    return audit


def _clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if item is not None and str(item).strip()]


def _clean_string_list_map(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, list[str]] = {}
    for key, items in value.items():
        scene_id = str(key).strip()
        if not scene_id:
            continue
        issue_list = _clean_string_list(items)
        if issue_list:
            cleaned[scene_id] = issue_list
    return cleaned


def _stock_candidate_curation_summary(source: dict | None) -> dict:
    source = source or {}
    direct_summary = source.get("summary") if isinstance(source.get("summary"), dict) else {}
    production = source.get("productionReview") if isinstance(source.get("productionReview"), dict) else {}
    production_summary = production.get("summary") if isinstance(production.get("summary"), dict) else {}
    top_tier = source.get("topTierReadiness") if isinstance(source.get("topTierReadiness"), dict) else {}
    top_tier_summary = top_tier.get("summary") if isinstance(top_tier.get("summary"), dict) else {}
    checks = source.get("checks") if isinstance(source.get("checks"), dict) else {}
    check = checks.get("stockCandidateCuration") if isinstance(checks.get("stockCandidateCuration"), dict) else {}

    scenes = _clean_string_list(
        production_summary.get("stockCandidateCurationScenes")
        or direct_summary.get("stockCandidateCurationScenes")
    )
    ready_scenes = _clean_string_list(
        production_summary.get("stockCandidateCurationReadyScenes")
        or direct_summary.get("stockCandidateCurationReadyScenes")
    )
    missing_scenes = _clean_string_list(
        production_summary.get("missingStockCandidateCurationScenes")
        or direct_summary.get("missingStockCandidateCurationScenes")
    )
    issues_by_scene = _clean_string_list_map(
        production_summary.get("stockCandidateCurationIssuesByScene")
        or direct_summary.get("stockCandidateCurationIssuesByScene")
    )
    missing_candidate_count = _clean_string_list(
        production_summary.get("missingStockCandidateCountScenes")
        or direct_summary.get("missingStockCandidateCountScenes")
    )
    missing_creator = _clean_string_list(
        production_summary.get("missingStockCandidateCreatorScenes")
        or direct_summary.get("missingStockCandidateCreatorScenes")
    )
    missing_selection_summary = _clean_string_list(
        production_summary.get("missingStockSelectionSummaryScenes")
        or direct_summary.get("missingStockSelectionSummaryScenes")
    )

    status = str(check.get("status") or direct_summary.get("stockCandidateCurationStatus") or "").strip()
    top_tier_ready = top_tier_summary.get("stockCandidateCurationReady")
    direct_ready = direct_summary.get("stockCandidateCurationReady")
    if isinstance(top_tier_ready, bool):
        ready: bool | None = top_tier_ready
    elif isinstance(direct_ready, bool):
        ready = direct_ready
    elif status == "pass":
        ready = True
    elif status in {"fail", "warn", "blocked"} or missing_scenes or issues_by_scene:
        ready = False
    elif scenes or ready_scenes:
        ready = len(missing_scenes) == 0 and len(ready_scenes) >= len(scenes)
    else:
        ready = None

    recorded = bool(
        status
        or scenes
        or ready_scenes
        or missing_scenes
        or issues_by_scene
        or missing_candidate_count
        or missing_creator
        or missing_selection_summary
        or isinstance(top_tier_ready, bool)
        or isinstance(direct_ready, bool)
    )
    normalized_status = status or ("pass" if ready is True else "warn" if ready is False else "not-recorded")
    return {
        "recorded": recorded,
        "ready": ready,
        "status": normalized_status,
        "detail": check.get("detail") or direct_summary.get("stockCandidateCurationDetail"),
        "scenes": scenes,
        "readyScenes": ready_scenes,
        "missingScenes": missing_scenes,
        "missingCandidateCountScenes": missing_candidate_count,
        "missingCreatorScenes": missing_creator,
        "missingSelectionSummaryScenes": missing_selection_summary,
        "issuesByScene": issues_by_scene,
    }


def _build_final_quality_audit(
    report: dict,
    final_video: Path,
    frame_paths: list[Path],
    contact_sheet: Path | None,
    audio_level: dict,
) -> dict:
    publish = report.get("publishReadiness") or {}
    channel = report.get("channelReadiness") or {}
    upload = report.get("uploadReview") or {}
    top_tier = report.get("topTierReadiness") or {}
    production = report.get("productionReview") or {}
    production_summary = production.get("summary") or {}
    channel_summary = channel.get("summary") or {}
    upload_summary = upload.get("summary") if isinstance(upload.get("summary"), dict) else {}
    top_tier_summary = top_tier.get("summary") if isinstance(top_tier.get("summary"), dict) else {}
    checks = report.get("checks") or {}
    stock_curation = _stock_candidate_curation_summary(report)

    def check_pass(key: str) -> bool:
        return (checks.get(key) or {}).get("status") == "pass"

    audio_ok = bool(audio_level.get("ok")) and (
        audio_level.get("maxVolumeDb") is None or audio_level.get("maxVolumeDb") <= -1.0
    )
    ai_hero_ready = channel_summary.get("heroAiOrLocalReady") is True
    original_hero_ready = channel_summary.get("heroOriginalClipReady") is True
    channel_ready = channel.get("status") == "channel-ready"
    audio_design_ready = (
        (
            check_pass("ttsNarrationEvidence")
            or upload_summary.get("audioDesignReady") is True
            or upload_summary.get("narrationReady") is True
        )
        and check_pass("voicePolicyCompliance")
    )
    caption_layout_ready = check_pass("captionLayoutReview") or upload_summary.get("captionLayoutReady") is True
    asset_diversity_ready = check_pass("assetReuseDiversity") or upload_summary.get("assetDiversityReady") is True
    free_asset_provenance_ready = check_pass("freeAssetProvenance") or upload_summary.get("freeAssetProvenanceReady") is True
    bgm_sound_ready = check_pass("bgmSoundQuality") or upload_summary.get("bgmSoundReady") is True
    bgm_rotation_ready = (check_pass("bgmAssetRotation") or upload_summary.get("bgmRotationReady") is True) and bgm_sound_ready
    stock_candidate_curation_ready = stock_curation.get("ready") is not False
    audio_mix_review_ready = upload_summary.get("audioMixReviewReady") is True
    platform_comparison_ready = upload_summary.get("platformComparisonReady") is True
    top_tier_evidence_ready = bool(
        top_tier_summary.get("topTierEvidenceReady") is True
        or (
            top_tier.get("status") == "top-tier-ready"
            and channel_ready
            and ai_hero_ready
            and audio_design_ready
            and caption_layout_ready
            and asset_diversity_ready
            and free_asset_provenance_ready
            and bgm_rotation_ready
            and stock_candidate_curation_ready
            and audio_mix_review_ready
            and platform_comparison_ready
        )
    )

    checklist = [
        {
            "key": "noPlaceholders",
            "label": "Placeholder 없음",
            "status": _quality_status(check_pass("noPlaceholders")),
            "detail": (checks.get("noPlaceholders") or {}).get("detail") or "render quality report check",
            "source": "automated",
        },
        {
            "key": "noUnrelatedStockCuts",
            "label": "무관한 스톡 컷 없음",
            "status": _quality_status(not production_summary.get("stockOnly")),
            "detail": "stockOnly=false" if not production_summary.get("stockOnly") else "stock-only packet needs manual relevance review",
            "source": "productionReview.summary",
        },
        {
            "key": "notStillImageSlideshow",
            "label": "움직임 없는 이미지 슬라이드쇼 아님",
            "status": _quality_status(check_pass("movingClipPriority")),
            "detail": (checks.get("movingClipPriority") or {}).get("detail") or "moving clip priority check",
            "source": "automated",
        },
        {
            "key": "toneCameraContinuity",
            "label": "씬 간 색감/톤/카메라 움직임 일관성",
            "status": _quality_status(not production_summary.get("missingContinuityScenes")),
            "detail": "no missing continuity scenes" if not production_summary.get("missingContinuityScenes") else "continuity scenes need review",
            "source": "productionReview.summary",
        },
        {
            "key": "captionSafeZone",
            "label": "자막 safe zone 준수",
            "status": _quality_status(check_pass("captionSafePresets")),
            "detail": (checks.get("captionSafePresets") or {}).get("detail") or "caption preset safe-zone check",
            "source": "automated",
        },
        {
            "key": "captionSubjectClear",
            "label": "자막이 영상 핵심 피사체를 가리지 않음",
            "status": _quality_status(upload.get("status") == "ready"),
            "detail": upload.get("status") or "upload review not ready",
            "source": "uploadReview",
        },
        {
            "key": "noWatermarkLogoCompression",
            "label": "워터마크/로고/저품질 압축 티 없음",
            "status": _quality_status(not production_summary.get("missingQualityReviewScenes")),
            "detail": "no missing quality review scenes" if not production_summary.get("missingQualityReviewScenes") else "quality review evidence missing",
            "source": "productionReview.summary",
        },
        {
            "key": "audioMixNotTooLoud",
            "label": "BGM/TTS 볼륨이 과하지 않음",
            "status": _quality_status(audio_ok),
            "detail": f"mean={audio_level.get('meanVolumeDb')} dB, max={audio_level.get('maxVolumeDb')} dB, ok={audio_level.get('ok')}",
            "source": "ffmpeg volumedetect",
        },
        {
            "key": "viewerAudioDesign",
            "label": "오디오 설계가 자연스러움(TTS 또는 no-voice BGM/native audio)",
            "status": _quality_status(audio_design_ready),
            "detail": (checks.get("ttsNarrationEvidence") or {}).get("detail") or "viewer audio design evidence missing",
            "source": "render-quality-report.checks",
        },
        {
            "key": "voicePolicyCompliance",
            "label": "정보/랭킹 템플릿 voice policy 준수",
            "status": _quality_status(check_pass("voicePolicyCompliance")),
            "detail": (checks.get("voicePolicyCompliance") or {}).get("detail") or "voice policy evidence missing",
            "source": "render-quality-report.checks",
        },
        {
            "key": "firstTwoSecondHook",
            "label": "첫 2초 hook이 있음",
            "status": _quality_status(production_summary.get("firstSceneHookReady") is True),
            "detail": "firstSceneHookReady=true" if production_summary.get("firstSceneHookReady") else "first scene hook needs manual review",
            "source": "productionReview.summary",
        },
        {
            "key": "naturalCuts",
            "label": "컷 전환이 자연스러움",
            "status": _quality_status(not production_summary.get("missingQualityReviewScenes") and asset_diversity_ready),
            "detail": "quality review present and no repeated visual assets" if not production_summary.get("missingQualityReviewScenes") and asset_diversity_ready else "cut quality/repeated asset use needs manual review",
            "source": "productionReview.summary",
        },
        {
            "key": "captionLayoutIntent",
            "label": "자막 위치/레이아웃이 의도적으로 선택됨",
            "status": _quality_status(caption_layout_ready),
            "detail": (checks.get("captionLayoutReview") or {}).get("detail") or "caption layout review missing",
            "source": "render-quality-report.checks",
        },
        {
            "key": "assetReuseDiversity",
            "label": "같은 무료 에셋 반복 사용 없음",
            "status": _quality_status(asset_diversity_ready),
            "detail": (checks.get("assetReuseDiversity") or {}).get("detail") or "asset diversity evidence missing",
            "source": "render-quality-report.checks",
        },
        {
            "key": "freeAssetSourcePlan",
            "label": "무료 에셋 출처/라이선스 검수 가능",
            "status": _quality_status(free_asset_provenance_ready),
            "detail": (checks.get("freeAssetProvenance") or {}).get("detail") or "free asset provenance missing",
            "source": "render-quality-report.checks",
        },
        {
            "key": "stockCandidateCuration",
            "label": "Pexels 후보 비교/선택 근거 있음",
            "status": _quality_status(stock_candidate_curation_ready),
            "detail": stock_curation.get("detail") or (
                "stock candidate curation ready"
                if stock_curation.get("ready") is True
                else "no stock candidate curation requirement recorded"
                if stock_curation.get("ready") is None
                else f"missing scenes: {', '.join(stock_curation.get('missingScenes') or []) or 'unknown'}"
            ),
            "source": "productionReview.summary/checks.stockCandidateCuration",
        },
        {
            "key": "bgmAssetRotation",
            "label": "무료 BGM이 같은 기본 트랙만 반복되지 않음",
            "status": _quality_status(bgm_rotation_ready),
            "detail": (checks.get("bgmAssetRotation") or {}).get("detail") or "BGM rotation evidence missing",
            "source": "render-quality-report.checks",
        },
        {
            "key": "bgmSoundQuality",
            "label": "beep/click/test-tone BGM 아님",
            "status": _quality_status(bgm_sound_ready),
            "detail": (checks.get("bgmSoundQuality") or {}).get("detail") or "BGM sound quality evidence missing",
            "source": "render-quality-report.checks",
        },
        {
            "key": "manualSelectionEvidence",
            "label": "AI가 대충 만든 느낌을 줄이는 수동 선택 근거 있음",
            "status": _quality_status(not production_summary.get("missingRationaleScenes")),
            "detail": "selection rationale present" if not production_summary.get("missingRationaleScenes") else "scene rationale missing",
            "source": "productionReview.summary",
        },
        {
            "key": "youtubeBenchmarkGap",
            "label": "YouTube AI 활용 쇼츠/롱폼 기준 비교",
            "status": _quality_status(top_tier_evidence_ready),
            "detail": "top-tier evidence ready" if top_tier_evidence_ready else "needs Grok/local hero, viewer-facing audio design, caption layout review, asset diversity, visual/audio free asset provenance, audio mix review, and platform comparison",
            "source": "channelReadiness.summary",
        },
    ]

    passed = sum(1 for item in checklist if item["status"] == "pass")
    needs_check = [item["key"] for item in checklist if item["status"] != "pass"]
    audit = {
        "projectId": report.get("projectId") or "unknown",
        "finalVideo": str(final_video),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "publishReadiness": publish,
        "channelReadiness": channel,
        "uploadReview": upload,
        "topTierReadiness": top_tier,
        "automationDirection": {
            "grok": "operator-approved Chrome/Grok handoff: prompt preparation, generation observation, then operator-owned local MP4 import; Chrome native download prompts and Downloads watcher fallback are repeatability failures",
            "localModels": "operator-approved Wan/LTX/Hunyuan command adapter packets with local MP4 scene import",
            "paidApiPolicy": "paid AI/API routes remain disabled unless the operator explicitly changes policy outside this flow",
        },
        "artifacts": {
            "reviewFrames": [str(path) for path in frame_paths],
            "contactSheet": str(contact_sheet) if contact_sheet else None,
            "audioLevel": audio_level,
        },
        "automatedEvidence": {
            "outputSpec": checks.get("outputSpec") or {},
            "noPlaceholders": checks.get("noPlaceholders") or {},
            "movingClipPriority": checks.get("movingClipPriority") or {},
            "sourceMotionEvidence": checks.get("sourceMotionEvidence") or {},
            "captionSafePresets": checks.get("captionSafePresets") or {},
            "aiSlopVisualFit": checks.get("aiSlopVisualFit") or {},
            "stockAiClipFit": checks.get("stockAiClipFit") or {},
            "ttsNarrationEvidence": checks.get("ttsNarrationEvidence") or {},
            "voicePolicyCompliance": checks.get("voicePolicyCompliance") or {},
            "captionLayoutReview": checks.get("captionLayoutReview") or {},
            "assetReuseDiversity": checks.get("assetReuseDiversity") or {},
            "freeAssetProvenance": checks.get("freeAssetProvenance") or {},
            "stockCandidateCuration": checks.get("stockCandidateCuration") or {},
            "bgmAssetRotation": checks.get("bgmAssetRotation") or {},
            "bgmSoundQuality": checks.get("bgmSoundQuality") or {},
            "uploadReviewGate": checks.get("uploadReviewGate") or {},
            "topTierReadinessGate": checks.get("topTierReadinessGate") or {},
        },
        "checklist": checklist,
        "summary": {
            "passed": passed,
            "total": len(checklist),
            "checksNeeded": needs_check,
            "readyForUpload": upload.get("status") == "ready",
            "channelReady": channel_ready,
            "grokOrLocalHeroReady": ai_hero_ready,
            "originalHeroReady": original_hero_ready,
            "audioDesignReady": audio_design_ready,
            "narrationReady": audio_design_ready,
            "captionLayoutReady": caption_layout_ready,
            "assetDiversityReady": asset_diversity_ready,
            "freeAssetProvenanceReady": free_asset_provenance_ready,
            "stockCandidateCurationRecorded": stock_curation.get("recorded"),
            "stockCandidateCurationReady": stock_curation.get("ready"),
            "stockCandidateCurationStatus": stock_curation.get("status"),
            "stockCandidateCurationScenes": stock_curation.get("scenes") or [],
            "stockCandidateCurationReadyScenes": stock_curation.get("readyScenes") or [],
            "missingStockCandidateCurationScenes": stock_curation.get("missingScenes") or [],
            "stockCandidateCurationIssuesByScene": stock_curation.get("issuesByScene") or {},
            "bgmRotationReady": bgm_rotation_ready,
            "bgmSoundReady": bgm_sound_ready,
            "audioMixReviewReady": audio_mix_review_ready,
            "platformComparisonReady": platform_comparison_ready,
            "topTierEvidenceReady": top_tier_evidence_ready,
            "benchmarkGap": "none" if top_tier_evidence_ready else "needs Grok/local hero, viewer-facing audio design, caption/layout proof, varied free visual/audio assets, source/license provenance, BGM rotation evidence, audio mix review, and Korean YouTube benchmark pass",
        },
    }
    return _attach_quality_gate_fields(audit)


def _read_json_artifact(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable final video artifact: %s", path)
        return None
    return value if isinstance(value, dict) else None


def _parse_frame_rate(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text == "0/0":
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            return float(numerator) / denominator_value
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _run_final_video_ffprobe(final_video: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"ok": False, "error": "ffprobe not found", "specReady": False}
    result = _run_ffmpeg_command([
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(final_video),
    ], timeout=30)
    if not result or result.returncode != 0:
        return {"ok": False, "error": "ffprobe failed", "specReady": False}
    try:
        raw = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"ffprobe JSON unreadable: {exc}", "specReady": False}
    video_stream = next((item for item in raw.get("streams") or [] if item.get("codec_type") == "video"), {})
    audio_stream = next((item for item in raw.get("streams") or [] if item.get("codec_type") == "audio"), {})
    frame_rate = _parse_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
    try:
        duration = float((raw.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    width = video_stream.get("width")
    height = video_stream.get("height")
    spec_ready = (
        width == 1080
        and height == 1920
        and frame_rate is not None
        and abs(frame_rate - 30.0) < 0.1
        and bool(audio_stream)
        and duration is not None
        and duration > 0
    )
    return {
        "ok": True,
        "width": width,
        "height": height,
        "frameRate": frame_rate,
        "durationSeconds": duration,
        "hasAudio": bool(audio_stream),
        "specReady": spec_ready,
        "raw": raw,
    }


def _final_packet_flags(quality_audit: dict | None, report: dict | None) -> dict:
    audit = quality_audit or {}
    report = report or {}
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    upload = audit.get("uploadReview") if isinstance(audit.get("uploadReview"), dict) else report.get("uploadReview") or {}
    channel = audit.get("channelReadiness") if isinstance(audit.get("channelReadiness"), dict) else report.get("channelReadiness") or {}
    publish = audit.get("publishReadiness") if isinstance(audit.get("publishReadiness"), dict) else report.get("publishReadiness") or {}
    top_tier = audit.get("topTierReadiness") if isinstance(audit.get("topTierReadiness"), dict) else report.get("topTierReadiness") or {}
    channel_summary = channel.get("summary") if isinstance(channel.get("summary"), dict) else {}
    top_tier_summary = top_tier.get("summary") if isinstance(top_tier.get("summary"), dict) else {}
    stock_curation = _stock_candidate_curation_summary(report)
    if not stock_curation.get("recorded"):
        stock_curation = _stock_candidate_curation_summary(audit)
    stock_curation_blocks = stock_curation.get("ready") is False
    ai_hero_ready = summary.get("grokOrLocalHeroReady") is True or channel_summary.get("heroAiOrLocalReady") is True
    audio_design_ready = (
        summary.get("audioDesignReady") is True
        or summary.get("narrationReady") is True
        or channel_summary.get("audioDesignReady") is True
        or channel_summary.get("narrationReady") is True
    )
    caption_layout_ready = summary.get("captionLayoutReady") is True or channel_summary.get("captionLayoutReady") is True
    asset_diversity_ready = summary.get("assetDiversityReady") is True or channel_summary.get("assetDiversityReady") is True
    free_asset_provenance_ready = summary.get("freeAssetProvenanceReady") is True or channel_summary.get("freeAssetProvenanceReady") is True
    bgm_rotation_ready = summary.get("bgmRotationReady") is True or channel_summary.get("bgmRotationReady") is True
    audio_mix_review_ready = summary.get("audioMixReviewReady") is True
    platform_comparison_ready = summary.get("platformComparisonReady") is True
    top_tier_evidence_ready = (
        (summary.get("topTierEvidenceReady") is True and bgm_rotation_ready)
        or top_tier_summary.get("topTierEvidenceReady") is True
        or (
            top_tier.get("status") == "top-tier-ready"
            and ai_hero_ready
            and audio_design_ready
            and caption_layout_ready
            and asset_diversity_ready
            and free_asset_provenance_ready
            and bgm_rotation_ready
            and audio_mix_review_ready
            and platform_comparison_ready
        )
    ) and not stock_curation_blocks
    benchmark_gap = summary.get("benchmarkGap") or top_tier_summary.get("benchmarkGap") or (
        "none" if top_tier_evidence_ready else "needs Grok/local AI hero, viewer-facing audio design, caption layout proof, asset diversity, free asset provenance, BGM rotation evidence, audio mix review, and platform benchmark evidence"
    )
    if stock_curation_blocks and "stock candidate curation" not in str(benchmark_gap).lower():
        benchmark_gap = f"{benchmark_gap}; missing Pexels stock candidate curation proof"
    return {
        "readyForUpload": summary.get("readyForUpload") is True or upload.get("status") == "ready",
        "channelReady": summary.get("channelReady") is True or channel.get("status") == "channel-ready",
        "grokOrLocalHeroReady": ai_hero_ready,
        "originalHeroReady": summary.get("originalHeroReady") is True or channel_summary.get("heroOriginalClipReady") is True,
        "audioDesignReady": audio_design_ready,
        "narrationReady": audio_design_ready,
        "captionLayoutReady": caption_layout_ready,
        "assetDiversityReady": asset_diversity_ready,
        "freeAssetProvenanceReady": free_asset_provenance_ready,
        "stockCandidateCurationRecorded": stock_curation.get("recorded"),
        "stockCandidateCurationReady": stock_curation.get("ready"),
        "stockCandidateCurationStatus": stock_curation.get("status"),
        "stockCandidateCurationScenes": stock_curation.get("scenes") or [],
        "stockCandidateCurationReadyScenes": stock_curation.get("readyScenes") or [],
        "missingStockCandidateCurationScenes": stock_curation.get("missingScenes") or [],
        "stockCandidateCurationIssuesByScene": stock_curation.get("issuesByScene") or {},
        "bgmRotationReady": bgm_rotation_ready,
        "audioMixReviewReady": audio_mix_review_ready,
        "platformComparisonReady": platform_comparison_ready,
        "topTierEvidenceReady": top_tier_evidence_ready,
        "publishStatus": publish.get("status") or "unknown",
        "channelStatus": channel.get("status") or "unknown",
        "uploadStatus": upload.get("status") or "unknown",
        "topTierStatus": top_tier.get("status") or "unknown",
        "benchmarkGap": benchmark_gap,
    }


_PUBLISH_PACKET_REQUIRED_FIELDS = [
    "finalMp4",
    "thumbnailCandidates.firstFrame",
    "thumbnailCandidates.reviewFrames",
    "thumbnailCandidates.contactSheet",
    "titleCandidates",
    "description",
    "hashtags",
    "uploadChecklist",
    "shortcomings",
    "nextImprovementActions",
    "nextImprovementActions.safeSourceFlowGuidance",
]


def _truthy_text(value: object) -> bool:
    return bool(str(value or "").strip())


def _truthy_list(value: object) -> bool:
    return isinstance(value, list) and any(str(item or "").strip() for item in value)


_PROOF_TEMPLATE_BOUNDARY_FIELDS = (
    "templateOnly",
    "doNotSubmitAsProof",
    "targetProofArtifactPath",
)


def _proof_template_boundary_failed_fields(record: dict) -> list[str]:
    return [field for field in _PROOF_TEMPLATE_BOUNDARY_FIELDS if field in record]


def _artifact_path_exists(packet_dir: Path, value: object) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    candidate = Path(raw)
    if candidate.exists():
        return True
    if not candidate.is_absolute():
        if (packet_dir / candidate).exists():
            return True
        if (_project_root / candidate).exists():
            return True
    return False


def _image_evidence_dimensions(path: Path) -> tuple[int | None, int | None, str]:
    try:
        data = path.read_bytes()
    except OSError:
        return None, None, "unreadable"
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height, "png"
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        index = 2
        sof_markers = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            while index < len(data) and data[index] == 0xFF:
                index += 1
            if index >= len(data):
                break
            marker = data[index]
            index += 1
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(data):
                break
            segment_length = int.from_bytes(data[index:index + 2], "big")
            if segment_length < 2 or index + segment_length > len(data):
                break
            if marker in sof_markers and segment_length >= 7:
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                return width, height, "jpeg"
            index += segment_length
    return None, None, "unknown"


def _image_evidence_check(
    path: Path,
    min_width: int,
    min_height: int,
    min_bytes: int,
    require_portrait: bool = False,
) -> dict:
    issues: list[str] = []
    try:
        byte_count = path.stat().st_size
    except OSError:
        byte_count = 0
        issues.append("file is unreadable")
    width, height, image_kind = _image_evidence_dimensions(path) if byte_count else (None, None, "unreadable")
    if image_kind not in {"png", "jpeg"} or not width or not height:
        issues.append("expected PNG/JPEG image evidence")
    if byte_count < min_bytes:
        issues.append(f"image evidence is too small: {byte_count} bytes < {min_bytes}")
    if width is not None and width < min_width:
        issues.append(f"image width is too small: {width} < {min_width}")
    if height is not None and height < min_height:
        issues.append(f"image height is too small: {height} < {min_height}")
    if require_portrait and width is not None and height is not None and height <= width:
        issues.append("image evidence must be portrait phone orientation")
    return {
        "ok": not issues,
        "kind": "image",
        "format": image_kind,
        "path": str(path),
        "bytes": byte_count,
        "width": width,
        "height": height,
        "minWidth": min_width,
        "minHeight": min_height,
        "minBytes": min_bytes,
        "requirePortrait": require_portrait,
        "issues": issues,
    }


def _publish_packet_content_audit(packet_dir: Path, publish_packet_path: Path, final_video: Path | None) -> dict:
    if not publish_packet_path.exists():
        return {
            "ready": False,
            "status": "missing",
            "requiredFields": _PUBLISH_PACKET_REQUIRED_FIELDS,
            "presentFields": [],
            "missingFields": _PUBLISH_PACKET_REQUIRED_FIELDS,
            "operatorAction": "Create publish-packet.json with final MP4, thumbnail/first-frame candidates, titles, description, hashtags, upload checklist, shortcomings, and next improvement actions.",
        }

    packet = _read_json_artifact(publish_packet_path)
    if packet is None:
        return {
            "ready": False,
            "status": "unreadable",
            "requiredFields": _PUBLISH_PACKET_REQUIRED_FIELDS,
            "presentFields": [],
            "missingFields": _PUBLISH_PACKET_REQUIRED_FIELDS,
            "operatorAction": "Regenerate publish-packet.json; the current file is not readable JSON object evidence.",
        }

    thumbnails = packet.get("thumbnailCandidates") if isinstance(packet.get("thumbnailCandidates"), dict) else {}
    review_frames = thumbnails.get("reviewFrames")
    final_mp4_ready = _artifact_path_exists(packet_dir, packet.get("finalMp4"))
    if final_video and _truthy_text(packet.get("finalMp4")) and not final_mp4_ready:
        final_mp4_ready = Path(str(packet.get("finalMp4"))).name == final_video.name

    next_improvement_actions = packet.get("nextImprovementActions")
    next_improvement_text = "\n".join(
        str(item or "") for item in next_improvement_actions
    ) if isinstance(next_improvement_actions, list) else ""
    unsafe_source_flow_guidance = any(
        phrase in next_improvement_text.lower()
        for phrase in [
            "generate and download",
            "generate/download",
            "use grok download/save/export",
        ]
    )

    checks = {
        "finalMp4": final_mp4_ready,
        "thumbnailCandidates.firstFrame": _artifact_path_exists(packet_dir, thumbnails.get("firstFrame")),
        "thumbnailCandidates.reviewFrames": (
            isinstance(review_frames, list)
            and len(review_frames) > 0
            and all(_artifact_path_exists(packet_dir, item) for item in review_frames)
        ),
        "thumbnailCandidates.contactSheet": _artifact_path_exists(packet_dir, thumbnails.get("contactSheet")),
        "titleCandidates": _truthy_list(packet.get("titleCandidates")),
        "description": _truthy_text(packet.get("description")),
        "hashtags": _truthy_list(packet.get("hashtags")),
        "uploadChecklist": _truthy_list(packet.get("uploadChecklist")),
        "shortcomings": _truthy_list(packet.get("shortcomings")),
        "nextImprovementActions": _truthy_list(next_improvement_actions),
        "nextImprovementActions.safeSourceFlowGuidance": not unsafe_source_flow_guidance,
    }
    present_fields = [key for key, ready in checks.items() if ready]
    missing_fields = [key for key, ready in checks.items() if not ready]
    ready = not missing_fields
    return {
        "ready": ready,
        "status": "ready" if ready else "missing-fields",
        "requiredFields": _PUBLISH_PACKET_REQUIRED_FIELDS,
        "presentFields": present_fields,
        "missingFields": missing_fields,
        "operatorAction": (
            "Publish packet content is complete; still perform the human pre-upload watch."
            if ready
            else "Complete publish-packet.json before showing this artifact packet as ready: "
            + ", ".join(missing_fields)
            + (
                ". Replace Grok/Chrome automation-download guidance with operator-owned local MP4 import or explicit already-saved MP4 batch upload."
                if unsafe_source_flow_guidance else ""
            )
        ),
    }


def _final_packet_next_actions(
    *,
    has_video: bool,
    has_quality_audit: bool,
    ffprobe: dict,
    flags: dict,
    publish_packet_audit: dict | None = None,
) -> list[dict]:
    actions: list[dict] = []
    if not has_video:
        actions.append({
            "key": "missing-final-mp4",
            "priority": "required",
            "label": "Final MP4 missing",
            "operatorAction": "Rerender or rerun finalize-render so the packet contains an MP4.",
        })
        return actions
    if not ffprobe.get("specReady"):
        actions.append({
            "key": "verify-output-spec",
            "priority": "required",
            "label": "Verify 1080x1920/30fps/audio",
            "detail": ffprobe.get("error") or f"{ffprobe.get('width')}x{ffprobe.get('height')} / fps={ffprobe.get('frameRate')} / audio={ffprobe.get('hasAudio')}",
            "operatorAction": "Rerender with the Shorts output spec and run ffprobe again.",
        })
    if not has_quality_audit:
        actions.append({
            "key": "missing-quality-audit",
            "priority": "required",
            "label": "Quality audit missing",
            "operatorAction": "Rerun /api/finalize-render on a current render-quality-report so publish evidence is attached.",
        })
    if publish_packet_audit is not None and publish_packet_audit.get("ready") is not True:
        actions.append({
            "key": "complete-publish-packet",
            "priority": "required",
            "label": "Complete publish packet",
            "detail": ", ".join(publish_packet_audit.get("missingFields") or []) or publish_packet_audit.get("status"),
            "operatorAction": publish_packet_audit.get("operatorAction"),
        })
    if not flags.get("readyForUpload"):
        actions.append({
            "key": "complete-upload-review",
            "priority": "required",
            "label": "Complete upload review",
            "detail": f"uploadStatus={flags.get('uploadStatus')}",
            "operatorAction": "Fix placeholder, motion, caption, audio, watermark, and first-hook checks before upload.",
        })
    if not flags.get("channelReady"):
        actions.append({
            "key": "reach-channel-ready",
            "priority": "required",
            "label": "Reach channel-ready evidence",
            "detail": f"channelStatus={flags.get('channelStatus')}",
            "operatorAction": "Use reviewed original/direct/Grok/local MP4 clips and fill selection/continuity/quality review evidence.",
        })
    if not flags.get("grokOrLocalHeroReady"):
        actions.append({
            "key": "add-grok-or-local-hero",
            "priority": "recommended" if flags.get("readyForUpload") else "required",
            "label": "Add Grok/local AI hero MP4",
            "detail": flags.get("benchmarkGap"),
            "operatorAction": (
                "Use browser-control against the existing logged-in Chrome/Grok app or web: copy the scene prompt, "
                "generate the short MP4, then have the operator save/download and import it through Downloads import "
                "or explicit batch upload before review/acceptance. Do not press Grok Download/Save/Export or any "
                "Chrome native download prompt from Codex automation. Use local Wan/LTX/Hunyuan as the offline fallback."
            ),
        })
    if not flags.get("topTierEvidenceReady"):
        actions.append({
            "key": "complete-top-tier-gate",
            "priority": "recommended" if flags.get("readyForUpload") else "required",
            "label": "Do not claim top-tier yet",
            "detail": flags.get("benchmarkGap"),
            "operatorAction": "Use the top-tier finalize mode only after Grok/local hero, viewer-facing audio design, captions, asset diversity, provenance, BGM rotation, audio mix, and Korean benchmark evidence all pass.",
        })
    if not flags.get("audioDesignReady"):
        actions.append({
            "key": "fix-viewer-audio-design",
            "priority": "required",
            "label": "Fix viewer-facing audio design",
            "detail": "Short captions alone do not meet the current quality bar; Grok-first can pass as no-voice when BGM/native audio and mix review evidence are present.",
            "operatorAction": "For Grok-first edits, prefer intentional no-voice with audible BGM/native ambience and audio mix review proof. Use free local TTS only when spoken context helps the viewer.",
        })
    if not flags.get("captionLayoutReady"):
        actions.append({
            "key": "fix-caption-layout",
            "priority": "required",
            "label": "Fix caption layout",
            "detail": "Caption safe preset alone is not enough without subject/UI occlusion review.",
            "operatorAction": "Use no caption, top hook, center short, or lower info intentionally and record that the subject and YouTube UI danger zones stay clear.",
        })
    if not flags.get("assetDiversityReady"):
        actions.append({
            "key": "replace-reused-assets",
            "priority": "required",
            "label": "Replace repeated assets",
            "detail": "Repeated free assets make the video look templated and low-effort.",
            "operatorAction": "Select distinct Pexels/Pixabay/Mixkit/direct/Grok/local clips per scene, or document a deliberate visual callback.",
        })
    if not flags.get("freeAssetProvenanceReady"):
        actions.append({
            "key": "record-free-asset-provenance",
            "priority": "required",
            "label": "Record free asset provenance",
            "detail": "Free assets need source URL/ID/label and license verification evidence.",
            "operatorAction": "Keep Pexels/Pixabay/Mixkit/Freesound source metadata and avoid assets with unclear attribution or Content ID risk.",
        })
    if flags.get("stockCandidateCurationReady") is False:
        missing_stock_scenes = flags.get("missingStockCandidateCurationScenes") or []
        actions.append({
            "key": "complete-stock-candidate-curation",
            "priority": "recommended" if flags.get("readyForUpload") else "required",
            "label": "Complete Pexels candidate curation proof",
            "detail": f"missing scenes: {', '.join(missing_stock_scenes) or 'unknown'}",
            "operatorAction": "For each Pexels stock clip, keep candidateCount>=2 plus creator/source page and a selectedCandidateSummary explaining why the chosen clip beat the alternatives.",
        })
    if not flags.get("bgmRotationReady"):
        actions.append({
            "key": "add-bgm-rotation-evidence",
            "priority": "recommended" if flags.get("readyForUpload") else "required",
            "label": "Add BGM rotation evidence",
            "detail": "A single default local BGM track makes repeated exports feel templated.",
            "operatorAction": "Keep at least two free/local BGM candidates per mood, retain source/license metadata, and rerender so the selected track records candidateCount, selectionMethod, and selectionKey.",
        })
    if not flags.get("audioMixReviewReady") or not flags.get("platformComparisonReady"):
        actions.append({
            "key": "review-audio-and-benchmark",
            "priority": "required",
            "label": "Review audio and Korean YouTube benchmark",
            "detail": f"audioMixReviewReady={flags.get('audioMixReviewReady')}, platformComparisonReady={flags.get('platformComparisonReady')}",
            "operatorAction": "Watch the full render once against Korean Shorts/long-form references; verify voice/BGM balance, hook, pacing, caption scale, and asset fit.",
        })
    if not actions:
        actions.append({
            "key": "publish-review",
            "priority": "next",
            "label": "Human publish review",
            "operatorAction": "Watch the full MP4 once, confirm no platform UI danger-zone issue, then upload or archive as the current best packet.",
        })
    return actions


def _final_video_from_publish_packet(packet_dir: Path, publish_packet: dict | None) -> Path | None:
    if not isinstance(publish_packet, dict):
        return None
    final_mp4 = _packet_artifact_path(packet_dir, publish_packet.get("finalMp4"))
    if final_mp4 and final_mp4.suffix.lower() == ".mp4":
        return final_mp4
    return None


def _final_video_packet_audit(packet_dir: Path) -> dict:
    videos = sorted(packet_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    quality_audit_path = packet_dir / "quality-audit.json"
    report_path = packet_dir / "render-quality-report.json"
    publish_packet_path = packet_dir / "publish-packet.json"
    publish_packet_markdown_path = packet_dir / "publish-packet.md"
    publish_packet = _read_json_artifact(publish_packet_path)
    final_video = _final_video_from_publish_packet(packet_dir, publish_packet) or (videos[0] if videos else None)
    quality_audit = _read_json_artifact(quality_audit_path)
    report = _read_json_artifact(report_path)
    ffprobe = _run_final_video_ffprobe(final_video) if final_video else {"ok": False, "error": "final MP4 missing", "specReady": False}
    flags = _final_packet_flags(quality_audit, report)
    publish_packet_audit = _publish_packet_content_audit(packet_dir, publish_packet_path, final_video)
    publish_packet_ready = publish_packet_audit.get("ready") is True
    has_quality_audit = quality_audit is not None
    has_video = final_video is not None
    top_tier_ready = bool(
        has_video
        and ffprobe.get("specReady") is True
        and publish_packet_ready
        and flags.get("readyForUpload")
        and flags.get("channelReady")
        and flags.get("topTierEvidenceReady")
    )
    upload_ready = bool(has_video and ffprobe.get("specReady") is True and publish_packet_ready and flags.get("readyForUpload"))
    channel_ready = bool(upload_ready and flags.get("channelReady"))
    next_actions = _final_packet_next_actions(
        has_video=has_video,
        has_quality_audit=has_quality_audit,
        ffprobe=ffprobe,
        flags=flags,
        publish_packet_audit=publish_packet_audit,
    )
    return {
        "projectId": packet_dir.name,
        "packetDir": str(packet_dir),
        "updatedAt": datetime.fromtimestamp(packet_dir.stat().st_mtime).isoformat(timespec="seconds"),
        "finalVideoPath": str(final_video) if final_video else None,
        "qualityAuditPath": str(quality_audit_path) if quality_audit_path.exists() else None,
        "qualityReportPath": str(report_path) if report_path.exists() else None,
        "publishPacketPath": str(publish_packet_path) if publish_packet_path.exists() else None,
        "publishPacketMarkdownPath": str(publish_packet_markdown_path) if publish_packet_markdown_path.exists() else None,
        "hasFinalMp4": has_video,
        "hasQualityAudit": has_quality_audit,
        "hasPublishPacket": publish_packet_path.exists(),
        "publishPacketAudit": publish_packet_audit,
        "ffprobe": {key: value for key, value in ffprobe.items() if key != "raw"},
        "summary": {
            **flags,
            "uploadReady": upload_ready,
            "channelReady": channel_ready,
            "topTierReady": top_tier_ready,
            "publishPacketContentReady": publish_packet_ready,
            "publishPacketStatus": publish_packet_audit.get("status"),
            "missingPublishPacketFields": publish_packet_audit.get("missingFields") or [],
            "nextActionKeys": [item.get("key") for item in next_actions],
        },
        "nextActions": next_actions,
    }


def _coerce_final_video_library_limit(raw_limit, default: int = 20) -> int:
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, 100))


def _final_video_library_snapshot(limit: int = 20) -> dict:
    final_root = _project_root / "storage" / "final-videos"
    packet_dirs = []
    if final_root.exists():
        packet_dirs = sorted(
            [path for path in final_root.iterdir() if path.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]
    packets = [_final_video_packet_audit(path) for path in packet_dirs]
    top_tier_packets = [item for item in packets if item["summary"].get("topTierReady")]
    channel_ready_packets = [item for item in packets if item["summary"].get("channelReady")]
    upload_ready_packets = [item for item in packets if item["summary"].get("uploadReady")]
    best_packet = (top_tier_packets or channel_ready_packets or upload_ready_packets or packets or [None])[0]
    return {
        "root": final_root,
        "packets": packets,
        "topTierPackets": top_tier_packets,
        "channelReadyPackets": channel_ready_packets,
        "uploadReadyPackets": upload_ready_packets,
        "bestPacket": best_packet,
    }


@media_bp.route("/api/final-video-library/audit", methods=["GET"])
def final_video_library_audit_route():
    """Audit existing storage/final-videos packets without calling paid APIs."""
    limit = _coerce_final_video_library_limit(flask_request.args.get("limit", 20))
    snapshot = _final_video_library_snapshot(limit)
    final_root = snapshot["root"]
    packets = snapshot["packets"]
    top_tier_packets = snapshot["topTierPackets"]
    channel_ready_packets = snapshot["channelReadyPackets"]
    upload_ready_packets = snapshot["uploadReadyPackets"]
    best_packet = snapshot["bestPacket"]
    best_report: dict = {}
    if isinstance(best_packet, dict):
        report_path_raw = str(best_packet.get("qualityReportPath") or "").strip()
        audit_path_raw = str(best_packet.get("qualityAuditPath") or "").strip()
        if report_path_raw:
            best_report = _read_json_artifact(Path(report_path_raw)) or {}
        if not best_report and audit_path_raw:
            best_report = _read_json_artifact(Path(audit_path_raw)) or {}
    source_pipeline_status = _source_pipeline_status(best_report)
    goal_readiness = _goal_readiness_audit(packets, best_packet, best_report, source_pipeline_status)
    return jsonify({
        "ok": True,
        "root": str(final_root),
        "scanned": len(packets),
        "counts": {
            "withMp4": sum(1 for item in packets if item.get("hasFinalMp4")),
            "withQualityAudit": sum(1 for item in packets if item.get("hasQualityAudit")),
            "withPublishPacket": sum(1 for item in packets if item.get("hasPublishPacket")),
            "withPublishPacketContentReady": sum(1 for item in packets if (item.get("publishPacketAudit") or {}).get("ready") is True),
            "uploadReady": len(upload_ready_packets),
            "channelReady": len(channel_ready_packets),
            "topTierReady": len(top_tier_packets),
            "missingQualityAudit": sum(1 for item in packets if not item.get("hasQualityAudit")),
            "missingPublishPacketContent": sum(1 for item in packets if (item.get("publishPacketAudit") or {}).get("ready") is not True),
        },
        "bestPacket": best_packet,
        "sourcePipelineStatus": source_pipeline_status,
        "goalReadiness": goal_readiness,
        "gateSystem": goal_readiness.get("gateSystem"),
        "packets": packets,
    })


def _goal_evidence_template_write(audit_block: dict, template_kind: str) -> dict:
    template_path_raw = str(audit_block.get("templateArtifactPath") or "").strip()
    artifact_path_raw = str(audit_block.get("artifactPath") or "").strip()
    if not template_path_raw:
        return {
            "kind": template_kind,
            "written": False,
            "error": "template path missing",
            "templateOnly": True,
            "proofArtifactCreated": False,
        }

    template_path = Path(template_path_raw)
    artifact_path = Path(artifact_path_raw) if artifact_path_raw else None
    template_payload = dict(audit_block.get("template") or {})
    digest_prefill = _prefill_goal_evidence_template_digests(template_payload, template_kind, template_path.parent)
    template_payload.update({
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "worksheetDigestPrefill": digest_prefill,
        "targetProofArtifactPath": str(artifact_path) if artifact_path else "",
        "goalBoundary": (
            "This worksheet is not proof. Create the target proof artifact only after the real-world "
            "fresh-source run, phone review, or live platform analytics are complete."
        ),
    })
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(json.dumps(template_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "kind": template_kind,
        "written": True,
        "path": str(template_path),
        "proofArtifactPath": str(artifact_path) if artifact_path else "",
        "proofArtifactExists": artifact_path.exists() if artifact_path else False,
        "proofArtifactCreated": False,
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "digestPrefill": digest_prefill,
    }


_GOAL_TEMPLATE_DIGEST_PATH_FIELDS = {
    "freshSourceRepeatability": {
        "handoffManifestPath": "handoffManifestSha256",
        "sourceReviewPath": "sourceReviewSha256",
        "renderManifestPath": "renderManifestSha256",
        "qualityAuditPath": "qualityAuditSha256",
        "publishPacketPath": "publishPacketSha256",
        "dashboardSmokePath": "dashboardSmokeSha256",
    },
    "phoneSizedHumanReview": {
        "reviewSnapshotPath": "reviewSnapshotSha256",
        "captionSafeZoneFramePath": "captionSafeZoneFrameSha256",
        "thumbnailFirstFramePath": "thumbnailFirstFrameSha256",
        "audioMixEvidencePath": "audioMixEvidenceSha256",
    },
    "platformAnalytics": {
        "analyticsSnapshotPath": "analyticsSnapshotSha256",
    },
}


def _prefill_goal_evidence_template_digests(template_payload: dict, template_kind: str, packet_dir: Path) -> dict:
    digest_fields = _GOAL_TEMPLATE_DIGEST_PATH_FIELDS.get(template_kind, {})
    prefilled_fields: list[dict] = []
    unresolved_fields: list[dict] = []
    for path_field, digest_field in digest_fields.items():
        if str(template_payload.get(digest_field) or "").strip():
            continue
        path_value = str(template_payload.get(path_field) or "").strip()
        if not path_value:
            unresolved_fields.append({
                "pathField": path_field,
                "digestField": digest_field,
                "reason": "path missing",
            })
            continue
        resolved_path = _packet_artifact_path(packet_dir, path_value)
        if not resolved_path:
            unresolved_fields.append({
                "pathField": path_field,
                "digestField": digest_field,
                "path": path_value,
                "reason": "path missing, outside current final-video packet, or not a file",
            })
            continue
        if template_kind == "freshSourceRepeatability" and path_field == "dashboardSmokePath":
            parsed_smoke = _read_json_artifact(resolved_path)
            proof_rendered_id = str(template_payload.get("renderedProjectId") or "").strip()
            if not isinstance(parsed_smoke, dict):
                unresolved_fields.append({
                    "pathField": path_field,
                    "digestField": digest_field,
                    "path": path_value,
                    "reason": "dashboard smoke is not a JSON object",
                })
                continue
            smoke_issues = _fresh_source_dashboard_smoke_issues(parsed_smoke, proof_rendered_id)
            if smoke_issues:
                unresolved_fields.append({
                    "pathField": path_field,
                    "digestField": digest_field,
                    "path": path_value,
                    "reason": "dashboard smoke invalid: " + "; ".join(smoke_issues),
                })
                continue
        if template_kind == "phoneSizedHumanReview":
            artifact_check = _phone_review_artifact_check(path_field, resolved_path)
            if artifact_check.get("ok") is not True:
                unresolved_fields.append({
                    "pathField": path_field,
                    "digestField": digest_field,
                    "path": path_value,
                    "reason": "phone review evidence invalid: " + "; ".join(
                        str(item) for item in (artifact_check.get("issues") or [])
                    ),
                })
                continue
        try:
            template_payload[digest_field] = _sha256_file_digest(resolved_path)
        except OSError:
            unresolved_fields.append({
                "pathField": path_field,
                "digestField": digest_field,
                "path": str(resolved_path),
                "reason": "path unreadable",
            })
            continue
        prefilled_fields.append({
            "pathField": path_field,
            "digestField": digest_field,
            "path": path_value,
        })
    return {
        "prefilledFields": prefilled_fields,
        "unresolvedFields": unresolved_fields,
        "note": "Packet-local worksheet digest prefill only; this does not create or satisfy proof artifacts.",
    }


def _fresh_source_intake_scene_action(scene: dict) -> str:
    scene_id = str(scene.get("sceneId") or "scene").strip()
    expected_file = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4").strip()
    browser_generation = scene.get("browserGeneration") if isinstance(scene.get("browserGeneration"), dict) else {}
    if scene.get("accepted") is True:
        return "Accepted for source runway. Keep it paired with the review packet and rerender before using it in a publish packet."
    review = scene.get("review") if isinstance(scene.get("review"), dict) else {}
    if scene.get("imported") is True and review.get("status") == "rejected":
        categories = ", ".join(str(item) for item in (review.get("failCategories") or []) if item)
        category_detail = f" Failed live-channel categories: {categories}." if categories else ""
        return (
            f"Rejected imported Grok MP4 for {scene_id}.{category_detail} "
            "Replace it with a clean moving clip through operator-owned manual download/import or explicit batch upload from an already-saved local MP4; "
            "do not press Grok Download/Save/Export or any Chrome native download prompt from Codex automation, then rerun review acceptance."
        )
    if scene.get("imported") is True:
        return "Open the review packet, inspect motion/source fit/caption-safe framing, then accept or reject this imported Grok MP4."
    if browser_generation.get("generated") is True:
        return (
            f"Grok browser generation was observed for {scene_id}, but no native MP4 is imported yet. "
            f"Use operator-owned manual download/import or explicit batch upload from an already saved MP4 to save it as {expected_file}; "
            "do not press Grok Download/Save/Export or any Chrome native download prompt from Codex automation, "
            "then run import preflight and review acceptance."
        )
    return (
        f"Generate or acquire a native Grok MP4 for {scene_id}, import it as {expected_file} through operator-owned manual download/import or explicit batch upload from an already-saved local MP4, "
        "without using Codex automation to press Grok Download/Save/Export or any Chrome native download prompt, "
        "then review at least the first two seconds, motion density, source fit, and caption-safe composition."
    )


def _fresh_source_recovery_execution_checklist(source_recovery_plan: dict | None) -> list[dict]:
    plan = source_recovery_plan if isinstance(source_recovery_plan, dict) else {}
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    checklist: list[dict] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("sceneId") or "").strip()
        if not scene_id:
            continue
        runway = scene.get("directImportRunway") if isinstance(scene.get("directImportRunway"), dict) else {}
        prompt = runway.get("prompt") if isinstance(runway.get("prompt"), dict) else {}
        local_review = scene.get("localReview") if isinstance(scene.get("localReview"), dict) else {}
        expanded = scene.get("expandedPexelsSearch") if isinstance(scene.get("expandedPexelsSearch"), dict) else {}
        lane = str(scene.get("recommendedLane") or scene.get("status") or "source-recovery-needed")
        lane_action = {
            "review-local-candidates": (
                "Review local replacement candidates against first-2s hook, AI/source fit, caption safe zone, "
                "continuity, and provenance before accepting any source."
            ),
            "rewrite-selected-stock-fallback": (
                "Rewrite the scene beat to fit the selected-stock or expanded Pexels fallback, then rerun source-fit "
                "and phone-sized first-frame/caption review before render."
            ),
            "regenerate-direct-import": (
                "Regenerate or acquire a clean moving MP4 through operator-owned manual download/import "
                "or explicit already-saved local MP4 import."
            ),
            "accept-reviewed-local-candidate": (
                "Accept the upload-grade local candidate in the handoff review packet, then rerun source recovery and render gates."
            ),
            "review-selected-stock-candidate": (
                "Phone-size review the selected-stock candidate and keep source provenance attached before using it in a rewrite."
            ),
        }.get(lane, str(scene.get("operatorAction") or "Resolve this rejected scene before render."))
        checklist.append({
            "sceneId": scene_id,
            "status": str(scene.get("status") or ""),
            "recommendedLane": lane,
            "blocksRender": True,
            "blocksFreshSourceProof": True,
            "selectedFileName": str(scene.get("selectedFileName") or ""),
            "failCategories": [str(item) for item in (scene.get("failCategories") or []) if item],
            "nextRequiredAction": lane_action,
            "operatorAction": str(scene.get("operatorAction") or lane_action),
            "acceptanceCriteria": [
                "Upload-grade moving 9:16 MP4 source; no static slideshow substitution.",
                "Visible motion and viewer hook in the first two seconds.",
                "No AI slop, stock/AI mismatch, continuity drift, text/logo/watermark, or scene assembly artifact.",
                "Lower third and right-side Shorts/TikTok/Reels UI zones remain caption-safe.",
                "Source provenance is recorded, and the accepted clip is reviewed before render.",
            ],
            "recoveryInputs": {
                "localReviewStatus": str(local_review.get("status") or local_review.get("verdict") or ""),
                "localReviewUploadReady": local_review.get("uploadReady") is True,
                "localReviewContactSheets": [
                    str(path) for path in (local_review.get("contactSheetPaths") or []) if path
                ],
                "selectedStockCandidateFileName": str(scene.get("pexelsCandidateFileName") or ""),
                "selectedStockVerdict": str(scene.get("pexelsVerdict") or ""),
                "selectedStockRequiresScriptRewrite": scene.get("pexelsRequiresScriptRewrite") is True,
                "expandedPexelsStatus": str(expanded.get("status") or ""),
                "expandedPexelsReviewPath": str(expanded.get("reviewPath") or ""),
                "expandedPexelsRewriteCandidates": int(expanded.get("rewriteCandidateCount") or 0),
                "directImportStatus": str(runway.get("status") or ""),
                "directImportExpectedFileName": str(runway.get("expectedFileName") or ""),
                "directImportUploadEndpoint": str(runway.get("uploadEndpoint") or ""),
                "directImportProofMonitorUrl": str(runway.get("proofMonitorUrl") or ""),
                "observedPostUrl": str(runway.get("observedPostUrl") or ""),
                "observedPostDownloadScriptUrl": str(runway.get("observedPostDownloadScriptUrl") or ""),
                "recoveryPromptSource": str(prompt.get("source") or ""),
                "recoveryPromptPreview": str(prompt.get("promptPreview") or ""),
                "forbiddenActions": [str(item) for item in (runway.get("forbiddenActions") or []) if item],
                "allowedRoutes": [str(item) for item in (runway.get("allowedRoutes") or []) if item],
            },
        })
    return checklist


def _fresh_source_intake_payload(
    latest_handoff: dict,
    manifest: dict,
    packet_path: Path,
    source_recovery_plan: dict | None = None,
) -> dict:
    scenes = latest_handoff.get("scenes") if isinstance(latest_handoff.get("scenes"), list) else []
    download_freshness = latest_handoff.get("downloadFreshness") if isinstance(latest_handoff.get("downloadFreshness"), dict) else {}
    browser_generation_proof = latest_handoff.get("browserGenerationProof") if isinstance(latest_handoff.get("browserGenerationProof"), dict) else {}
    import_preflight = latest_handoff.get("importPreflightSummary") if isinstance(latest_handoff.get("importPreflightSummary"), dict) else {}
    if not import_preflight:
        import_preflight = latest_handoff.get("importPreflight") if isinstance(latest_handoff.get("importPreflight"), dict) else {}
    source_recovery_plan = source_recovery_plan if isinstance(source_recovery_plan, dict) else {}
    source_recovery_checklist = _fresh_source_recovery_execution_checklist(source_recovery_plan)
    required_scenes = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_payload = {
            "sceneId": str(scene.get("sceneId") or ""),
            "expectedFileName": str(scene.get("expectedFileName") or ""),
            "imported": scene.get("imported") is True,
            "accepted": scene.get("accepted") is True,
            "promptQualityStatus": str(scene.get("promptQualityStatus") or ""),
            "importPreflight": scene.get("importPreflight") if isinstance(scene.get("importPreflight"), dict) else {},
            "browserGeneration": scene.get("browserGeneration") if isinstance(scene.get("browserGeneration"), dict) else {},
            "review": scene.get("review") if isinstance(scene.get("review"), dict) else {},
            "candidatePool": scene.get("candidatePool") if isinstance(scene.get("candidatePool"), dict) else {},
        }
        scene_payload["operatorAction"] = _fresh_source_intake_scene_action(scene_payload)
        required_scenes.append(scene_payload)

    replacement_backlog = latest_handoff.get("replacementBacklog") if isinstance(latest_handoff.get("replacementBacklog"), list) else []
    return {
        "schema": "video-studio.fresh-source-intake.v1",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "projectId": str(latest_handoff.get("projectId") or ""),
        "handoffStatus": str(latest_handoff.get("status") or ""),
        "packetPath": str(packet_path),
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "operatorDecision": latest_handoff.get("operatorDecision") or {},
        "counts": {
            "totalScenes": latest_handoff.get("totalScenes") or 0,
            "importedScenes": latest_handoff.get("importedScenes") or 0,
            "acceptedScenes": latest_handoff.get("acceptedScenes") or 0,
            "rejectedScenes": latest_handoff.get("rejectedScenes") or 0,
            "missingScenes": len(latest_handoff.get("missingScenes") or []),
            "preflightReadyScenes": import_preflight.get("readyScenes") or 0,
            "preflightMissingScenes": len(import_preflight.get("missingScenes") or []),
            "preflightInvalidScenes": len(import_preflight.get("invalidScenes") or []),
            "preflightStaleScenes": len(import_preflight.get("staleScenes") or []),
            "freshDownloadCandidates": download_freshness.get("freshCandidateCount") or 0,
            "oldDownloadsExcluded": download_freshness.get("excludedOldCandidateCount") or 0,
            "browserGeneratedScenes": browser_generation_proof.get("generatedScenes") or 0,
            "browserGeneratedMissingScenes": len(browser_generation_proof.get("missingSceneIds") or []),
            "sourceRecoveryScenes": source_recovery_plan.get("totalScenes") or 0,
            "sourceRecoverySelectedStockRewriteScenes": source_recovery_plan.get("selectedStockRewriteAvailableScenes") or 0,
            "sourceRecoveryDirectImportRunwayScenes": source_recovery_plan.get("directImportRunwayScenes") or 0,
            "sourceRecoveryExpandedPexelsScenes": source_recovery_plan.get("expandedPexelsSearchScenes") or 0,
        },
        "missingScenes": latest_handoff.get("missingScenes") or [],
        "rejectedScenes": latest_handoff.get("rejectedSceneIds") or [],
        "liveFailCategories": latest_handoff.get("liveFailCategories") or [],
        "replacementBacklog": replacement_backlog,
        "sourceRecoveryPlan": source_recovery_plan,
        "sourceRecoveryExecutionChecklist": source_recovery_checklist,
        "sourceRecoveryBoundary": (
            "Source recovery execution prep is not proof and does not allow render or upload. "
            "Every rejected scene must be replaced, accepted through review, rerendered, finalized, audited, "
            "dashboard-smoked, and then recorded in fresh-source-proof.json."
        ),
        "importPreflight": import_preflight,
        "importPreflightSummary": import_preflight,
        "browserGenerationProof": browser_generation_proof,
        "requiredScenes": required_scenes,
        "downloadFreshness": download_freshness,
        "handoffLinks": {
            "worksheetUrl": latest_handoff.get("worksheetUrl") or "",
            "productionQueueUrl": latest_handoff.get("productionQueueUrl") or "",
            "reviewPacketUrl": latest_handoff.get("reviewPacketUrl") or "",
            "statusUrl": latest_handoff.get("statusUrl") or "",
        },
        "sourcePolicy": {
            "paidAiApiAllowed": False,
            "allowedFlow": "existing signed-in Grok app/web browser-control with operator-owned upload/import from an already-saved local MP4",
            "disallowedFlow": "paid xAI API, paid AI services, static image slideshow, stale pre-handoff Downloads MP4 reuse, Codex automation pressing Grok Download/Save/Export, Chrome native download prompts, Downloads watcher fallback",
            "freshnessPolicy": download_freshness.get("freshnessPolicy") or "Only MP4s modified after this handoff can support fresh-source repeatability.",
        },
        "operatorChecklist": [
            "Use a different topic/source run than the existing final MP4 baseline.",
            "Import moving native Grok MP4 clips for every missing scene; do not substitute still images or a slideshow.",
            "Reject clips with AI slop, stock/AI mismatch, weak first-two-second hook, low motion/cut density, or unsafe caption composition.",
            "For rejected scenes, follow sourceRecoveryExecutionChecklist first; selected-stock and expanded Pexels options are rewrite triage, not direct proof.",
            "Accept or reject every imported scene in the review packet before rendering.",
            "After acceptance, rerender/finalize a publish packet with TTS or approved no-voice policy, non-placeholder BGM, caption safe-zone proof, source provenance, thumbnail/first-frame candidate, title, description, hashtags, checklist, shortcomings, and next action.",
            "Record phone-sized human review and live platform analytics separately; this intake template is not proof.",
        ],
        "doesNotSatisfy": [
            "fresh-source repeatability until imported clips are accepted, rendered, finalized, audited, and dashboard-smoked",
            "phone-sized human review",
            "live platform analytics loop",
            "broad live-channel operating-system Goal",
        ],
        "goalBoundary": (
            "This file is an operator intake worksheet only. It does not create Grok MP4 proof, source repeatability proof, "
            "phone-review proof, platform analytics proof, or broad Goal completion."
        ),
    }


def _source_recovery_acceptance_payload(
    latest_handoff: dict,
    packet_path: Path,
    source_recovery_plan: dict | None = None,
) -> dict:
    """Build a rejected-scene acceptance worksheet without creating proof."""
    plan = source_recovery_plan if isinstance(source_recovery_plan, dict) else {}
    checklist = _fresh_source_recovery_execution_checklist(plan)
    checklist_by_scene = {
        str(item.get("sceneId") or ""): item
        for item in checklist
        if isinstance(item, dict) and str(item.get("sceneId") or "").strip()
    }
    plan_scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    acceptance_scenes: list[dict] = []
    fallback_criteria = [
        "Accepted replacement is a moving 9:16 MP4 source and is not a static/slideshow substitute.",
        "First two seconds have visible motion and a viewer hook.",
        "AI slop, stock/AI mismatch, scene assembly artifacts, text/logo/watermark, and continuity drift are absent.",
        "Caption and platform UI safe zones pass phone-sized review.",
        "Source provenance, local path, reviewer, and accepted timestamp are recorded before rerender.",
    ]
    required_fields = [
        "acceptedReplacementFileName",
        "acceptedReplacementPath",
        "acceptedReplacementSha256",
        "reviewerId",
        "acceptedAt",
        "firstTwoSecondHookPass",
        "motionDensityPass",
        "aiSlopVisualFitPass",
        "stockAiClipFitPass",
        "captionSafeZonePass",
        "sourceProvenanceConfirmed",
        "phoneFirstFrameReviewPass",
        "continuityReviewPass",
    ]
    for scene in plan_scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("sceneId") or "").strip()
        if not scene_id:
            continue
        checklist_item = checklist_by_scene.get(scene_id) or {}
        local_review = scene.get("localReview") if isinstance(scene.get("localReview"), dict) else {}
        expanded = scene.get("expandedPexelsSearch") if isinstance(scene.get("expandedPexelsSearch"), dict) else {}
        runway = scene.get("directImportRunway") if isinstance(scene.get("directImportRunway"), dict) else {}
        render_blockers = [str(item) for item in (scene.get("renderBlockers") or []) if item]
        proof_blockers = [str(item) for item in (scene.get("freshSourceProofBlockers") or render_blockers) if item]
        acceptance_scenes.append({
            "sceneId": scene_id,
            "status": "operator-review-required",
            "acceptanceStatus": "operator-review-required",
            "recommendedLane": str(scene.get("recommendedLane") or scene.get("status") or "source-recovery-needed"),
            "selectedFileName": str(scene.get("selectedFileName") or ""),
            "blocksRender": True,
            "blocksFreshSourceProof": True,
            "directRenderAllowed": False,
            "uploadReady": False,
            "renderBlockers": render_blockers,
            "freshSourceProofBlockers": proof_blockers,
            "renderBlockerCount": int(scene.get("renderBlockerCount") or len(render_blockers)),
            "freshSourceProofBlockerCount": int(scene.get("freshSourceProofBlockerCount") or len(proof_blockers)),
            "failCategories": [str(item) for item in (scene.get("failCategories") or []) if item],
            "acceptanceCriteria": checklist_item.get("acceptanceCriteria") or fallback_criteria,
            "requiredAcceptanceFields": required_fields,
            "operatorDecisionTemplate": {
                "accepted": False,
                "reviewStatus": "needs-operator-review",
                "acceptedReplacementFileName": "",
                "acceptedReplacementPath": "",
                "reviewerId": "",
                "acceptedAt": "",
                "reviewNotes": "",
                "rerenderRequired": True,
                "freshSourceProofReady": False,
            },
            "recoveryInputs": checklist_item.get("recoveryInputs") or {},
            "localReview": local_review,
            "selectedStock": {
                "candidateFileName": str(scene.get("pexelsCandidateFileName") or ""),
                "verdict": str(scene.get("pexelsVerdict") or ""),
                "requiresScriptRewrite": scene.get("pexelsRequiresScriptRewrite") is True,
                "uploadReady": False,
            },
            "expandedPexelsSearch": {
                "status": str(expanded.get("status") or ""),
                "reviewPath": str(expanded.get("reviewPath") or ""),
                "rewriteCandidateCount": int(expanded.get("rewriteCandidateCount") or 0),
                "uploadReadyCandidates": int(expanded.get("uploadReadyCandidates") or 0),
            },
            "directImportRunway": {
                "status": str(runway.get("status") or ""),
                "expectedFileName": str(runway.get("expectedFileName") or ""),
                "uploadEndpoint": str(runway.get("uploadEndpoint") or ""),
                "proofMonitorUrl": str(runway.get("proofMonitorUrl") or ""),
                "observedPostUrl": str(runway.get("observedPostUrl") or ""),
                "observedPostDownloadScriptUrl": str(runway.get("observedPostDownloadScriptUrl") or ""),
                "allowedRoutes": [str(item) for item in (runway.get("allowedRoutes") or []) if item],
                "forbiddenActions": [str(item) for item in (runway.get("forbiddenActions") or []) if item],
            },
            "operatorAction": str(scene.get("operatorAction") or checklist_item.get("operatorAction") or ""),
            "doesNotSatisfy": [
                "fresh-source-proof.json",
                "final MP4 render readiness",
                "phone-review.json",
                "platform-analytics.json",
                "live-channel operating-system Goal",
            ],
        })

    render_blocker_count = int(plan.get("renderBlockerCount") or sum(
        int(scene.get("renderBlockerCount") or len(scene.get("renderBlockers") or []))
        for scene in acceptance_scenes
    ))
    proof_blocker_count = int(plan.get("freshSourceProofBlockerCount") or sum(
        int(scene.get("freshSourceProofBlockerCount") or len(scene.get("freshSourceProofBlockers") or []))
        for scene in acceptance_scenes
    ))
    return {
        "schema": "video-studio.source-recovery-acceptance.v1",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "projectId": str(latest_handoff.get("projectId") or ""),
        "handoffStatus": str(latest_handoff.get("status") or ""),
        "packetPath": str(packet_path),
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "directRenderAllowed": False,
        "uploadReady": False,
        "sourceRecoveryStatus": str(plan.get("status") or "missing"),
        "sourceRecoveryScenes": len(acceptance_scenes),
        "renderBlockerCount": render_blocker_count,
        "freshSourceProofBlockerCount": proof_blocker_count,
        "scenesBlockingRender": plan.get("scenesBlockingRender") or [scene["sceneId"] for scene in acceptance_scenes],
        "scenesBlockingFreshSourceProof": plan.get("scenesBlockingFreshSourceProof") or [scene["sceneId"] for scene in acceptance_scenes],
        "sourceRecoveryPlan": plan,
        "sourceRecoveryExecutionChecklist": checklist,
        "acceptanceScenes": acceptance_scenes,
        "operatorChecklist": [
            "Review each acceptanceScenes row and fill all requiredAcceptanceFields before any rerender.",
            "Use the recommendedLane only as an execution path; selected-stock and expanded Pexels rows require rewrite and phone-sized review.",
            "Keep Grok/Chrome native Download/Save/Export actions out of Codex automation; use direct import or operator-owned local MP4 import.",
            "After acceptance, rerender/finalize/audit/dashboard-smoke the packet and only then create fresh-source-proof.json from accepted evidence.",
        ],
        "sourceRecoveryBoundary": (
            "This acceptance worksheet is not source proof. It records what the operator must review before render; "
            "it does not create fresh-source-proof.json, does not allow direct render, and does not approve upload."
        ),
        "doesNotSatisfy": [
            "fresh-source-proof.json",
            "render readiness",
            "phone-sized human review",
            "live platform analytics loop",
            "broad live-channel operating-system Goal",
        ],
        "goalBoundary": (
            "This file is a source-recovery acceptance worksheet only. It does not create proof artifacts, "
            "does not unblock render, and does not mark the operating system goal complete."
        ),
    }


_SOURCE_RECOVERY_ACCEPTANCE_BOOL_FIELDS = {
    "firstTwoSecondHookPass",
    "motionDensityPass",
    "aiSlopVisualFitPass",
    "stockAiClipFitPass",
    "captionSafeZonePass",
    "sourceProvenanceConfirmed",
    "phoneFirstFrameReviewPass",
    "continuityReviewPass",
}


def _source_recovery_acceptance_decision(scene: dict) -> dict:
    decision = scene.get("operatorDecision") if isinstance(scene.get("operatorDecision"), dict) else {}
    if decision:
        return decision
    return scene.get("operatorDecisionTemplate") if isinstance(scene.get("operatorDecisionTemplate"), dict) else {}


def _source_recovery_acceptance_value(scene: dict, decision: dict, field: str) -> object:
    if field in decision:
        return decision.get(field)
    return scene.get(field)


def _source_recovery_acceptance_video_check(path: Path) -> dict:
    issues: list[str] = []
    if path.suffix.lower() != ".mp4":
        issues.append("accepted replacement must be an MP4 file")
    ffprobe = _run_final_video_ffprobe(path)
    width = ffprobe.get("width")
    height = ffprobe.get("height")
    duration = ffprobe.get("durationSeconds")
    if ffprobe.get("ok") is not True:
        issues.append(str(ffprobe.get("error") or "ffprobe did not confirm a usable video stream"))
    else:
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            issues.append("accepted replacement video dimensions are missing")
        elif height <= width:
            issues.append("accepted replacement must be portrait 9:16 video")
        else:
            aspect_ratio = width / height
            if abs(aspect_ratio - (9 / 16)) > 0.035:
                issues.append(f"accepted replacement aspect ratio must be close to 9:16, got {width}x{height}")
        if not isinstance(duration, (int, float)) or duration <= 0:
            issues.append("accepted replacement video duration is missing or zero")
    return {
        "ok": not issues,
        "path": str(path),
        "issues": issues,
        "ffprobe": _compact_ffprobe(ffprobe),
    }


def _source_recovery_acceptance_path_check(
    value: object,
    expected_sha256: object,
    expected_file_name: object = "",
) -> dict:
    raw = str(value or "").strip()
    if not raw:
        return {"ok": False, "reason": "path missing", "issues": ["path missing"]}
    path = _resolve_project_artifact_path(raw)
    if not path:
        return {"ok": False, "path": raw, "reason": "path unresolved", "issues": ["path unresolved"]}
    try:
        resolved = path.resolve()
        root = _project_root.resolve()
    except OSError:
        return {"ok": False, "path": str(path), "reason": "path unresolved", "issues": ["path unresolved"]}
    if not resolved.is_relative_to(root):
        return {"ok": False, "path": str(path), "reason": "path outside project root", "issues": ["path outside project root"]}
    if not resolved.is_file():
        return {"ok": False, "path": str(path), "reason": "path missing or not a file", "issues": ["path missing or not a file"]}

    issues: list[str] = []
    file_name = str(expected_file_name or "").strip()
    file_name_check = {
        "ok": True,
        "expectedFileName": file_name,
        "actualFileName": resolved.name,
    }
    if file_name and resolved.name != file_name:
        issue = f"acceptedReplacementFileName must match path basename {resolved.name}"
        issues.append(issue)
        file_name_check["ok"] = False
        file_name_check["issue"] = issue

    expected_digest = str(expected_sha256 or "").strip().lower()
    if not expected_digest:
        return {
            "ok": False,
            "path": str(resolved),
            "reason": "acceptedReplacementSha256 missing",
            "issues": [*issues, "acceptedReplacementSha256 missing"],
            "fileNameCheck": file_name_check,
        }
    try:
        actual_digest = _sha256_file_digest(resolved)
    except OSError:
        return {
            "ok": False,
            "path": str(resolved),
            "reason": "path unreadable",
            "issues": [*issues, "path unreadable"],
            "fileNameCheck": file_name_check,
        }
    if actual_digest.lower() != expected_digest:
        return {
            "ok": False,
            "path": str(resolved),
            "reason": "acceptedReplacementSha256 mismatch",
            "actualSha256": actual_digest,
            "expectedSha256": expected_digest,
            "issues": [*issues, "acceptedReplacementSha256 mismatch"],
            "fileNameCheck": file_name_check,
        }
    video_check = _source_recovery_acceptance_video_check(resolved)
    issues.extend(str(item) for item in (video_check.get("issues") or []) if item)
    return {
        "ok": not issues,
        "path": str(resolved),
        "reason": "" if not issues else issues[0],
        "actualSha256": actual_digest,
        "expectedSha256": expected_digest,
        "issues": issues,
        "fileNameCheck": file_name_check,
        "videoCheck": video_check,
    }


def _source_recovery_acceptance_status(project_id: str, source_recovery_plan: dict | None = None) -> dict:
    project_id = str(project_id or "").strip()
    plan = source_recovery_plan if isinstance(source_recovery_plan, dict) else {}
    handoff_dir = _project_root / "storage" / "grok-handoffs" / project_id
    acceptance_path = handoff_dir / "source-recovery-acceptance.json"
    template_path = handoff_dir / "source-recovery-acceptance.template.json"
    required_artifact_path = str(acceptance_path)
    plan_scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    plan_scene_ids = [
        str(scene.get("sceneId") or "").strip()
        for scene in plan_scenes
        if isinstance(scene, dict) and str(scene.get("sceneId") or "").strip()
    ]
    total_scenes = int(plan.get("totalScenes") or len(plan_scene_ids))
    if total_scenes == 0:
        return {
            "available": True,
            "projectId": project_id,
            "status": "no-source-recovery-required",
            "requiredArtifactPath": required_artifact_path,
            "templatePath": str(template_path),
            "artifactPath": str(acceptance_path) if acceptance_path.exists() else "",
            "templateOnly": False,
            "proofArtifactCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
            "blocksRender": False,
            "blocksFreshSourceProof": False,
            "acceptedSceneCount": 0,
            "totalScenes": 0,
            "missingFieldsByScene": {},
            "scenes": [],
            "operatorAction": "No rejected source-recovery scenes are currently exposed.",
        }

    selected_path = acceptance_path if acceptance_path.exists() else template_path if template_path.exists() else None
    parsed = _read_json_artifact(selected_path) if selected_path else {}
    if not selected_path or not isinstance(parsed, dict):
        scene_statuses = [{
            "sceneId": scene_id,
            "status": "missing-acceptance-artifact",
            "accepted": False,
            "missingFields": ["source-recovery-acceptance.json"],
            "blocksRender": True,
            "blocksFreshSourceProof": True,
        } for scene_id in plan_scene_ids]
        return {
            "available": False,
            "projectId": project_id,
            "status": "missing",
            "requiredArtifactPath": required_artifact_path,
            "templatePath": str(template_path),
            "artifactPath": "",
            "templateOnly": False,
            "proofArtifactCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
            "blocksRender": True,
            "blocksFreshSourceProof": True,
            "acceptedSceneCount": 0,
            "incompleteSceneCount": total_scenes,
            "totalScenes": total_scenes,
            "missingFieldsByScene": {scene["sceneId"]: scene["missingFields"] for scene in scene_statuses},
            "scenes": scene_statuses,
            "operatorAction": "Create source-recovery-acceptance.json from the template after operator replacement review; the template is not accepted evidence.",
        }

    template_only = selected_path.name.endswith(".template.json") or parsed.get("templateOnly") is True
    raw_scenes = parsed.get("acceptanceScenes") if isinstance(parsed.get("acceptanceScenes"), list) else []
    acceptance_by_scene = {
        str(scene.get("sceneId") or "").strip(): scene
        for scene in raw_scenes
        if isinstance(scene, dict) and str(scene.get("sceneId") or "").strip()
    }
    scene_ids = plan_scene_ids or list(acceptance_by_scene.keys())
    scene_statuses: list[dict] = []
    for scene_id in scene_ids:
        scene = acceptance_by_scene.get(scene_id) or {"sceneId": scene_id}
        decision = _source_recovery_acceptance_decision(scene)
        default_required_fields = [
            "acceptedReplacementFileName",
            "acceptedReplacementPath",
            "acceptedReplacementSha256",
            "reviewerId",
            "acceptedAt",
            "firstTwoSecondHookPass",
            "motionDensityPass",
            "aiSlopVisualFitPass",
            "stockAiClipFitPass",
            "captionSafeZonePass",
            "sourceProvenanceConfirmed",
            "phoneFirstFrameReviewPass",
            "continuityReviewPass",
        ]
        required_fields = []
        for field in [
            *[str(item) for item in (scene.get("requiredAcceptanceFields") or []) if item],
            *default_required_fields,
        ]:
            if field not in required_fields:
                required_fields.append(field)
        missing_fields: list[str] = []
        for field in required_fields:
            value = _source_recovery_acceptance_value(scene, decision, field)
            if field in _SOURCE_RECOVERY_ACCEPTANCE_BOOL_FIELDS:
                if value is not True:
                    missing_fields.append(field)
            elif not str(value or "").strip():
                missing_fields.append(field)

        path_check = _source_recovery_acceptance_path_check(
            _source_recovery_acceptance_value(scene, decision, "acceptedReplacementPath"),
            _source_recovery_acceptance_value(scene, decision, "acceptedReplacementSha256"),
            _source_recovery_acceptance_value(scene, decision, "acceptedReplacementFileName"),
        )
        if path_check.get("ok") is not True:
            for reason in [str(item) for item in (path_check.get("issues") or []) if item] or [
                str(path_check.get("reason") or "accepted replacement path invalid")
            ]:
                if reason not in missing_fields:
                    missing_fields.append(reason)
        accepted_at = _source_recovery_acceptance_value(scene, decision, "acceptedAt")
        accepted_at_check = _audit_timestamp_check("acceptedAt", accepted_at) if str(accepted_at or "").strip() else {}
        for issue in [str(item) for item in (accepted_at_check.get("issues") or []) if item]:
            if issue not in missing_fields:
                missing_fields.append(issue)
        accepted_flag = decision.get("accepted") is True or scene.get("accepted") is True
        accepted = bool(accepted_flag and not missing_fields and not template_only)
        status = "accepted" if accepted else "template-only-not-accepted" if template_only else "operator-acceptance-incomplete"
        scene_statuses.append({
            "sceneId": scene_id,
            "status": status,
            "accepted": accepted,
            "acceptanceStatus": str(scene.get("acceptanceStatus") or decision.get("reviewStatus") or status),
            "recommendedLane": str(scene.get("recommendedLane") or ""),
            "acceptedReplacementFileName": str(_source_recovery_acceptance_value(scene, decision, "acceptedReplacementFileName") or ""),
            "acceptedReplacementPath": str(_source_recovery_acceptance_value(scene, decision, "acceptedReplacementPath") or ""),
            "acceptedReplacementPathCheck": path_check,
            "reviewerId": str(_source_recovery_acceptance_value(scene, decision, "reviewerId") or ""),
            "acceptedAt": str(_source_recovery_acceptance_value(scene, decision, "acceptedAt") or ""),
            "acceptedAtCheck": accepted_at_check,
            "missingFields": missing_fields,
            "requiredAcceptanceFields": required_fields,
            "blocksRender": not accepted,
            "blocksFreshSourceProof": True,
            "proofReady": False,
        })

    accepted_count = sum(1 for scene in scene_statuses if scene.get("accepted") is True)
    incomplete_count = len(scene_statuses) - accepted_count
    status = (
        "template-only-not-accepted"
        if template_only
        else "accepted-replacements-ready-for-rerender"
        if scene_statuses and accepted_count == len(scene_statuses)
        else "operator-acceptance-incomplete"
    )
    return {
        "available": acceptance_path.exists() or template_path.exists(),
        "projectId": project_id,
        "status": status,
        "requiredArtifactPath": required_artifact_path,
        "templatePath": str(template_path),
        "artifactPath": str(acceptance_path if acceptance_path.exists() else selected_path),
        "templateOnly": template_only,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "blocksRender": incomplete_count > 0,
        "blocksFreshSourceProof": True,
        "acceptedSceneCount": accepted_count,
        "incompleteSceneCount": incomplete_count,
        "totalScenes": len(scene_statuses),
        "missingFieldsByScene": {
            str(scene.get("sceneId") or ""): scene.get("missingFields") or []
            for scene in scene_statuses
            if scene.get("missingFields")
        },
        "scenes": scene_statuses,
        "operatorAction": (
            "Fill source-recovery-acceptance.json with accepted replacement path, SHA-256, reviewer, timestamp, and all phone/source-fit pass fields before rerender."
            if incomplete_count
            else "Accepted replacement sources are ready for rerender, but this is still not fresh-source-proof.json or upload approval."
        ),
        "goalBoundary": "Source recovery acceptance verifies operator replacement review only; proof/upload gates still require rerender, final audit, dashboard smoke, fresh-source-proof.json, phone review, and analytics.",
    }


def _source_recovery_rerender_plan_payload(
    latest_handoff: dict,
    packet_path: Path,
    source_recovery_plan: dict | None,
    acceptance_status: dict | None,
) -> dict:
    """Build a rerender input worksheet from already accepted recovery sources."""
    plan = source_recovery_plan if isinstance(source_recovery_plan, dict) else {}
    acceptance_status = acceptance_status if isinstance(acceptance_status, dict) else {}
    acceptance_artifact_path = str(acceptance_status.get("artifactPath") or "")
    acceptance_artifact_sha256 = ""
    if acceptance_artifact_path:
        try:
            acceptance_path = Path(acceptance_artifact_path)
            if acceptance_path.is_file():
                acceptance_artifact_sha256 = _sha256_file_digest(acceptance_path)
        except OSError:
            acceptance_artifact_sha256 = ""
    accepted_scenes: list[dict] = []
    for scene in acceptance_status.get("scenes") or []:
        if not isinstance(scene, dict) or scene.get("accepted") is not True:
            continue
        path_check = scene.get("acceptedReplacementPathCheck") if isinstance(scene.get("acceptedReplacementPathCheck"), dict) else {}
        accepted_scenes.append({
            "sceneId": str(scene.get("sceneId") or ""),
            "acceptedReplacementFileName": str(scene.get("acceptedReplacementFileName") or ""),
            "acceptedReplacementPath": str(scene.get("acceptedReplacementPath") or ""),
            "acceptedReplacementSha256": str(path_check.get("actualSha256") or ""),
            "acceptedReplacementPathCheck": path_check,
            "reviewerId": str(scene.get("reviewerId") or ""),
            "acceptedAt": str(scene.get("acceptedAt") or ""),
            "recommendedLane": str(scene.get("recommendedLane") or ""),
            "renderInputOverride": {
                "sceneId": str(scene.get("sceneId") or ""),
                "sourcePath": str(scene.get("acceptedReplacementPath") or ""),
                "sourceFileName": str(scene.get("acceptedReplacementFileName") or ""),
                "sourceKind": "source-recovery-accepted-replacement",
                "sourceRecoveryAcceptanceArtifactPath": acceptance_artifact_path,
                "sourceRecoveryAcceptanceSha256": acceptance_artifact_sha256,
                "requiresRerender": True,
                "requiresFinalLibraryAudit": True,
                "requiresDashboardSmoke": True,
                "requiresFreshSourceProofAfterRerender": True,
            },
            "postRerenderChecks": [
                "render-manifest selectedFilePath matches this accepted replacement source",
                "quality-audit source motion, hook, caption-safe-zone, source-fit, and continuity gates pass",
                "publish-packet source-flow guidance remains no-native-download",
                "dashboard-smoke.json is browser-rendered for the rerendered packet",
                "fresh-source-proof.json is created only after rerender/finalize/audit/dashboard-smoke",
            ],
        })

    return {
        "schema": "video-studio.source-recovery-rerender-plan.v1",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "projectId": str(latest_handoff.get("projectId") or acceptance_status.get("projectId") or ""),
        "handoffStatus": str(latest_handoff.get("status") or ""),
        "packetPath": str(packet_path),
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "sourceRecoveryAcceptanceCleared": acceptance_status.get("status") == "accepted-replacements-ready-for-rerender",
        "rerenderInputReady": bool(accepted_scenes) and acceptance_status.get("blocksRender") is False,
        "renderExecuted": False,
        "finalMp4Created": False,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "phoneReviewProofCreated": False,
        "platformAnalyticsProofCreated": False,
        "uploadReady": False,
        "goalComplete": False,
        "acceptedReplacementCount": len(accepted_scenes),
        "acceptedSceneCount": acceptance_status.get("acceptedSceneCount") or len(accepted_scenes),
        "totalScenes": acceptance_status.get("totalScenes") or len(accepted_scenes),
        "sourceRecoveryAcceptanceStatus": acceptance_status,
        "sourceRecoveryAcceptanceArtifactPath": acceptance_artifact_path,
        "sourceRecoveryAcceptanceSha256": acceptance_artifact_sha256,
        "sourceRecoveryPlan": plan,
        "sceneReplacements": accepted_scenes,
        "renderPlan": {
            "inputSource": "source-recovery-acceptance.json accepted replacements",
            "sourceReplacementMode": "replace rejected scene sources before rerender",
            "renderManifestRequired": True,
            "qualityAuditRequired": True,
            "publishPacketRequired": True,
            "dashboardSmokeRequired": True,
            "freshSourceProofRequiredAfterRerender": True,
            "phoneReviewRequiredAfterRerender": True,
            "platformAnalyticsRequiredAfterUpload": True,
        },
        "operatorChecklist": [
            "Use sceneReplacements as the exact source override list for the rerender input project.",
            "Rerender and finalize a new 1080x1920/30fps/audio packet; do not mutate the old packet into proof.",
            "Run ffprobe, quality audit, publish packet audit, and browser-rendered dashboard smoke on the rerendered packet.",
            "Create fresh-source-proof.json only after rerender/finalize/audit/dashboard-smoke and bind it to the rerendered final MP4.",
            "Record phone-review.json and platform-analytics.json separately; this rerender worksheet is not upload approval.",
        ],
        "doesNotSatisfy": [
            "fresh-source-proof.json",
            "final MP4 render completion",
            "phone-review.json",
            "platform-analytics.json",
            "same-day upload approval",
            "broad live-channel operating-system Goal",
        ],
        "goalBoundary": (
            "This file only preserves accepted replacement source mapping for rerender. It does not render, "
            "does not create fresh-source-proof.json, does not approve upload, and does not complete the broad Goal."
        ),
    }


@media_bp.route("/api/final-video-library/fresh-source-intake", methods=["POST"])
def final_video_library_fresh_source_intake_route():
    """Write a fresh-source operator intake worksheet without treating it as proof."""
    data = flask_request.get_json(silent=True) or {}
    project_id = str(data.get("projectId") or "").strip()
    context = _latest_grok_handoff_context()
    if project_id:
        context = {
            **context,
            "projectId": project_id,
            "sceneId": str(data.get("sceneId") or context.get("sceneId") or "scene-01"),
        }
    latest_handoff = _latest_grok_handoff_summary(context)
    if latest_handoff.get("available") is not True:
        return jsonify({
            "ok": False,
            "error": "No Grok handoff is available for fresh-source intake.",
            "proofArtifactCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
        }), 404

    handoff_dir = _project_root / "storage" / "grok-handoffs" / str(latest_handoff.get("projectId") or "")
    manifest = _read_json_artifact(handoff_dir / "handoff.json") or {}
    packet_path = handoff_dir / "fresh-source-intake.template.json"
    handoff_project_id = str(latest_handoff.get("projectId") or "")
    source_recovery_plan = _source_recovery_plan(
        latest_handoff,
        _latest_pexels_replacement_research_summary(handoff_project_id),
        _latest_local_candidate_review_summary(handoff_project_id),
        _latest_pexels_expanded_search_summary(handoff_project_id),
    )
    packet = _fresh_source_intake_payload(latest_handoff, manifest, packet_path, source_recovery_plan)
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return jsonify({
        "ok": True,
        "projectId": latest_handoff.get("projectId"),
        "path": str(packet_path),
        "templateOnly": True,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "operatorDecision": latest_handoff.get("operatorDecision") or {},
        "missingScenes": latest_handoff.get("missingScenes") or [],
        "rejectedScenes": latest_handoff.get("rejectedSceneIds") or [],
        "liveFailCategories": latest_handoff.get("liveFailCategories") or [],
        "sourceRecoveryPlan": packet.get("sourceRecoveryPlan") or {},
        "sourceRecoveryExecutionChecklist": packet.get("sourceRecoveryExecutionChecklist") or [],
        "sourceRecoveryBoundary": packet.get("sourceRecoveryBoundary") or "",
        "importPreflight": packet.get("importPreflight") or {},
        "importPreflightSummary": packet.get("importPreflightSummary") or {},
        "downloadFreshness": latest_handoff.get("downloadFreshness") or {},
        "packet": packet,
        "goalBoundary": packet["goalBoundary"],
    })


@media_bp.route("/api/final-video-library/source-recovery-acceptance", methods=["POST"])
def final_video_library_source_recovery_acceptance_route():
    """Write rejected-scene source acceptance worksheet rows without proof side effects."""
    data = flask_request.get_json(silent=True) or {}
    project_id = str(data.get("projectId") or "").strip()
    context = _latest_grok_handoff_context()
    if project_id:
        context = {
            **context,
            "projectId": project_id,
            "sceneId": str(data.get("sceneId") or context.get("sceneId") or "scene-01"),
        }
    latest_handoff = _latest_grok_handoff_summary(context)
    if latest_handoff.get("available") is not True:
        return jsonify({
            "ok": False,
            "error": "No Grok handoff is available for source recovery acceptance.",
            "proofArtifactCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
        }), 404

    handoff_project_id = str(latest_handoff.get("projectId") or "")
    handoff_dir = _project_root / "storage" / "grok-handoffs" / handoff_project_id
    packet_path = handoff_dir / "source-recovery-acceptance.template.json"
    source_recovery_plan = _source_recovery_plan(
        latest_handoff,
        _latest_pexels_replacement_research_summary(handoff_project_id),
        _latest_local_candidate_review_summary(handoff_project_id),
        _latest_pexels_expanded_search_summary(handoff_project_id),
    )
    packet = _source_recovery_acceptance_payload(latest_handoff, packet_path, source_recovery_plan)
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    acceptance_status = _source_recovery_acceptance_status(handoff_project_id, source_recovery_plan)
    return jsonify({
        "ok": True,
        "status": "written-not-proof",
        "projectId": latest_handoff.get("projectId"),
        "path": str(packet_path),
        "templateOnly": True,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "directRenderAllowed": False,
        "uploadReady": False,
        "sourceRecoveryStatus": packet.get("sourceRecoveryStatus") or "",
        "sourceRecoveryScenes": packet.get("sourceRecoveryScenes") or 0,
        "renderBlockerCount": packet.get("renderBlockerCount") or 0,
        "freshSourceProofBlockerCount": packet.get("freshSourceProofBlockerCount") or 0,
        "scenesBlockingRender": packet.get("scenesBlockingRender") or [],
        "scenesBlockingFreshSourceProof": packet.get("scenesBlockingFreshSourceProof") or [],
        "sourceRecoveryPlan": packet.get("sourceRecoveryPlan") or {},
        "sourceRecoveryExecutionChecklist": packet.get("sourceRecoveryExecutionChecklist") or [],
        "acceptanceScenes": packet.get("acceptanceScenes") or [],
        "sourceRecoveryAcceptanceStatus": acceptance_status,
        "sourceRecoveryBoundary": packet.get("sourceRecoveryBoundary") or "",
        "doesNotSatisfy": packet.get("doesNotSatisfy") or [],
        "packet": packet,
        "goalBoundary": packet["goalBoundary"],
    })


@media_bp.route("/api/final-video-library/source-recovery-rerender-plan", methods=["POST"])
def final_video_library_source_recovery_rerender_plan_route():
    """Write accepted source-recovery rerender mapping only after actual acceptance passes."""
    data = flask_request.get_json(silent=True) or {}
    project_id = str(data.get("projectId") or "").strip()
    context = _latest_grok_handoff_context()
    if project_id:
        context = {
            **context,
            "projectId": project_id,
            "sceneId": str(data.get("sceneId") or context.get("sceneId") or "scene-01"),
        }
    latest_handoff = _latest_grok_handoff_summary(context)
    if latest_handoff.get("available") is not True:
        return jsonify({
            "ok": False,
            "status": "missing-handoff",
            "error": "No Grok handoff is available for source recovery rerender planning.",
            "proofArtifactCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
        }), 404

    handoff_project_id = str(latest_handoff.get("projectId") or "")
    handoff_dir = _project_root / "storage" / "grok-handoffs" / handoff_project_id
    packet_path = handoff_dir / "source-recovery-rerender-plan.template.json"
    source_recovery_plan = _source_recovery_plan(
        latest_handoff,
        _latest_pexels_replacement_research_summary(handoff_project_id),
        _latest_local_candidate_review_summary(handoff_project_id),
        _latest_pexels_expanded_search_summary(handoff_project_id),
    )
    acceptance_status = _source_recovery_acceptance_status(handoff_project_id, source_recovery_plan)
    if acceptance_status.get("status") != "accepted-replacements-ready-for-rerender":
        return jsonify({
            "ok": False,
            "status": "blocked-by-source-recovery-acceptance",
            "error": "source-recovery-acceptance.json is missing, template-only, or incomplete.",
            "projectId": latest_handoff.get("projectId"),
            "path": str(packet_path),
            "templateOnly": False,
            "blockedBySourceRecoveryAcceptance": True,
            "rerenderInputReady": False,
            "renderExecuted": False,
            "proofArtifactCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
            "sourceRecoveryAcceptanceStatus": acceptance_status,
            "sourceRecoveryAcceptanceBlockerCount": acceptance_status.get("incompleteSceneCount") or 0,
            "requiredArtifactPath": acceptance_status.get("requiredArtifactPath") or str(handoff_dir / "source-recovery-acceptance.json"),
            "missingFieldsByScene": acceptance_status.get("missingFieldsByScene") or {},
            "goalBoundary": "Rerender planning is blocked until actual accepted replacement sources are recorded; no proof or upload approval is created.",
        })

    packet = _source_recovery_rerender_plan_payload(
        latest_handoff,
        packet_path,
        source_recovery_plan,
        acceptance_status,
    )
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return jsonify({
        "ok": True,
        "status": "written-not-proof",
        "projectId": latest_handoff.get("projectId"),
        "path": str(packet_path),
        "templateOnly": True,
        "blockedBySourceRecoveryAcceptance": False,
        "sourceRecoveryAcceptanceCleared": packet.get("sourceRecoveryAcceptanceCleared") is True,
        "rerenderInputReady": packet.get("rerenderInputReady") is True,
        "renderExecuted": False,
        "finalMp4Created": False,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "phoneReviewProofCreated": False,
        "platformAnalyticsProofCreated": False,
        "uploadReady": False,
        "goalComplete": False,
        "acceptedReplacementCount": packet.get("acceptedReplacementCount") or 0,
        "acceptedSceneCount": packet.get("acceptedSceneCount") or 0,
        "totalScenes": packet.get("totalScenes") or 0,
        "sceneReplacements": packet.get("sceneReplacements") or [],
        "renderPlan": packet.get("renderPlan") or {},
        "sourceRecoveryAcceptanceStatus": acceptance_status,
        "sourceRecoveryPlan": packet.get("sourceRecoveryPlan") or {},
        "doesNotSatisfy": packet.get("doesNotSatisfy") or [],
        "packet": packet,
        "goalBoundary": packet["goalBoundary"],
    })


def _fresh_source_evidence_scene_status(scene: dict) -> tuple[str, bool]:
    verdict = str(
        scene.get("visualQualityVerdictStatus")
        or scene.get("visualQualityVerdict")
        or scene.get("visualVerdict")
        or ""
    ).strip().lower()
    stock_fit = str(
        scene.get("stockAiClipFitVerdict")
        or scene.get("clipFitVerdict")
        or scene.get("sourceFitVerdict")
        or ""
    ).strip().lower()
    provenance_confirmed = scene.get("sourceProvenanceConfirmed") is True
    ready_terms = {"pass", "ready", "accepted", "ok", "channel-ready", "top-tier-ready"}
    candidate_ready = bool(verdict in ready_terms and (provenance_confirmed or stock_fit in ready_terms))
    return verdict or stock_fit or "needs-operator-review", candidate_ready


def _fresh_source_evidence_scene_blockers(scene_payload: dict, first_scene_id: str) -> list[str]:
    blockers = ["operator source review has not accepted this scene"]
    scene_id = str(scene_payload.get("sceneId") or "").strip()
    intent = str(scene_payload.get("visualSourceIntent") or "").strip().lower()
    selected_file = str(scene_payload.get("selectedFileName") or scene_payload.get("selectedFilePath") or "").strip()
    visual_verdict = str(scene_payload.get("visualQualityVerdict") or "").strip().lower()
    stock_fit = str(scene_payload.get("stockAiClipFitVerdict") or "").strip().lower()
    ready_terms = {"pass", "ready", "accepted", "ok", "channel-ready", "top-tier-ready"}
    if not selected_file:
        blockers.append("selected source file is missing from the render manifest")
    if scene_payload.get("sourceProvenanceConfirmed") is not True:
        blockers.append("source provenance is not confirmed")
    if visual_verdict not in ready_terms:
        blockers.append("visual quality verdict is not pass/ready")
    if intent in {"selected-stock", "pexels", "pexels-video", "stock"}:
        blockers.append("selected-stock or Pexels fallback still needs explicit source-fit and phone-sized review")
        if stock_fit not in ready_terms:
            blockers.append("stock/AI clip-fit verdict is not pass/ready")
    if scene_id and first_scene_id and scene_id == first_scene_id:
        if not str(scene_payload.get("hookNote") or "").strip() and scene_payload.get("captionPreset") != "top-hook":
            blockers.append("first-two-second hook evidence is missing")
        else:
            blockers.append("first-two-second hook still needs phone-sized operator review")
    return blockers


def _fresh_source_evidence_scene_payload(scene: dict, index: int, first_scene_id: str) -> dict:
    scene_id = str(scene.get("sceneId") or scene.get("id") or f"scene-{index + 1:02d}").strip()
    selected_file = str(
        scene.get("selectedFileName")
        or scene.get("selectedFile")
        or scene.get("fileName")
        or scene.get("sourceFileName")
        or ""
    ).strip()
    source_provenance = scene.get("sourceProvenance") if isinstance(scene.get("sourceProvenance"), dict) else {}
    source_review_status, candidate_ready = _fresh_source_evidence_scene_status(scene)
    scene_payload = {
        "sceneId": scene_id,
        "title": str(scene.get("title") or scene.get("sceneTitle") or ""),
        "visualSourceIntent": str(scene.get("visualSourceIntent") or scene.get("sourceIntent") or ""),
        "selectedFileName": Path(selected_file).name if selected_file else "",
        "selectedFilePath": selected_file,
        "sourceProvenanceConfirmed": scene.get("sourceProvenanceConfirmed") is True,
        "sourceProvenance": source_provenance,
        "sourceRationale": str(scene.get("sourceRationale") or scene.get("rationale") or ""),
        "continuityNote": str(scene.get("continuityNote") or ""),
        "hookNote": str(scene.get("hookNote") or ""),
        "qualityReviewNote": str(scene.get("qualityReviewNote") or ""),
        "visualQualityVerdict": str(
            scene.get("visualQualityVerdictStatus")
            or scene.get("visualQualityVerdict")
            or scene.get("visualVerdict")
            or ""
        ),
        "stockAiClipFitVerdict": str(
            scene.get("stockAiClipFitVerdict")
            or scene.get("clipFitVerdict")
            or scene.get("sourceFitVerdict")
            or ""
        ),
        "captionPreset": str(scene.get("captionPreset") or ""),
        "candidateReadyForOperatorReview": candidate_ready,
        "operatorDecision": "needs-review",
        "sourceReviewStatus": source_review_status,
        "operatorReviewRequired": True,
        "proofAccepted": False,
    }
    blockers = _fresh_source_evidence_scene_blockers(scene_payload, first_scene_id)
    scene_payload.update({
        "freshSourceProofReady": False,
        "proofBlockers": blockers,
        "proofBlockerCount": len(blockers),
        "freshSourceProofBoundary": (
            "This scene is only a draft source-evidence row until operator source review records accepted/pass evidence."
        ),
    })
    return scene_payload


def _fresh_source_evidence_payloads(
    best_packet: dict,
    source_recovery_acceptance: dict | None = None,
) -> dict:
    packet_dir = Path(str(best_packet.get("packetDir") or ""))
    project_id = str(best_packet.get("projectId") or "").strip()
    source_recovery_acceptance = (
        source_recovery_acceptance if isinstance(source_recovery_acceptance, dict) else {}
    )
    render_manifest_path = packet_dir / "render-manifest.json"
    render_manifest = _read_json_artifact(render_manifest_path) or {}
    manifest_scenes = render_manifest.get("scenes") if isinstance(render_manifest.get("scenes"), list) else []
    first_scene_id = ""
    for scene in manifest_scenes:
        if isinstance(scene, dict):
            first_scene_id = str(scene.get("sceneId") or scene.get("id") or "").strip()
            if first_scene_id:
                break
    scenes = [
        _fresh_source_evidence_scene_payload(scene, index, first_scene_id)
        for index, scene in enumerate(manifest_scenes)
        if isinstance(scene, dict)
    ]
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    candidate_ready_scene_ids = [
        scene["sceneId"] for scene in scenes if scene.get("candidateReadyForOperatorReview") is True
    ]
    proof_blocker_count = sum(int(scene.get("proofBlockerCount") or 0) for scene in scenes)
    scenes_with_proof_blockers = [
        scene["sceneId"] for scene in scenes if int(scene.get("proofBlockerCount") or 0) > 0
    ]
    source_recovery_blocks_proof = source_recovery_acceptance.get("blocksFreshSourceProof") is True
    source_recovery_acceptance_blocker_count = (
        int(source_recovery_acceptance.get("incompleteSceneCount") or 0)
        if source_recovery_blocks_proof
        else 0
    )
    handoff_path = packet_dir / "fresh-source-handoff.template.json"
    review_path = packet_dir / "fresh-source-review.template.json"
    boundary = (
        "Fresh-source evidence prep writes packet-local handoff/review drafts only. "
        "It does not create fresh-source-proof.json, does not mark scenes accepted, "
        "and does not approve same-day upload or broad Goal completion."
    )
    handoff_payload = {
        "schema": "video-studio.fresh-source-handoff-evidence.v1",
        "createdAt": created_at,
        "source": "video-studio-fresh-source-evidence-prep",
        "projectId": project_id,
        "renderedProjectId": project_id,
        "packetDir": str(packet_dir),
        "renderManifestPath": str(render_manifest_path),
        "sceneCount": len(scenes),
        "candidateReadySceneCount": len(candidate_ready_scene_ids),
        "candidateReadySceneIds": candidate_ready_scene_ids,
        "operatorAcceptedSceneCount": 0,
        "freshSourceProofReadySceneCount": 0,
        "proofBlockerCount": proof_blocker_count,
        "scenesWithProofBlockers": scenes_with_proof_blockers,
        "sourceRecoveryAcceptanceStatus": source_recovery_acceptance,
        "sourceRecoveryAcceptanceBlockerCount": source_recovery_acceptance_blocker_count,
        "freshSourceProofBlockedBySourceRecoveryAcceptance": source_recovery_blocks_proof,
        "scenes": scenes,
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "operatorReviewRequired": True,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "goalBoundary": boundary,
        "doesNotSatisfy": [
            "fresh-source-proof.json",
            "phone-review.json",
            "platform-analytics.json",
            "same-day upload decision",
            "broad live-channel operating-system Goal",
        ],
    }
    review_scenes = [
        {
            "sceneId": scene["sceneId"],
            "selectedFileName": scene.get("selectedFileName") or "",
            "visualSourceIntent": scene.get("visualSourceIntent") or "",
            "candidateReadyForOperatorReview": scene.get("candidateReadyForOperatorReview") is True,
            "freshSourceProofReady": False,
            "proofBlockers": scene.get("proofBlockers") or [],
            "proofBlockerCount": int(scene.get("proofBlockerCount") or 0),
            "operatorDecision": "needs-review",
            "accepted": False,
            "rejected": False,
            "requiredManualChecks": [
                "Watch the moving clip at phone size, including the first two seconds.",
                "Confirm source provenance and selected-file binding.",
                "Reject AI slop, stock/source mismatch, continuity drift, low-motion footage, text/logo/watermark, or caption-safe-zone risk.",
                "Only then record accepted/pass/ready source review evidence in a non-template proof artifact.",
            ],
        }
        for scene in scenes
    ]
    review_payload = {
        "schema": "video-studio.fresh-source-review-evidence.v1",
        "createdAt": created_at,
        "source": "video-studio-fresh-source-evidence-prep",
        "projectId": project_id,
        "renderedProjectId": project_id,
        "status": "needs-operator-review",
        "reviewStatus": "needs-operator-review",
        "acceptedSceneCount": 0,
        "rejectedSceneCount": 0,
        "reviewRequiredSceneCount": len(scenes),
        "candidateReadySceneCount": len(candidate_ready_scene_ids),
        "candidateReadySceneIds": candidate_ready_scene_ids,
        "operatorAcceptedSceneCount": 0,
        "freshSourceProofReadySceneCount": 0,
        "proofBlockerCount": proof_blocker_count,
        "scenesWithProofBlockers": scenes_with_proof_blockers,
        "sourceRecoveryAcceptanceStatus": source_recovery_acceptance,
        "sourceRecoveryAcceptanceBlockerCount": source_recovery_acceptance_blocker_count,
        "freshSourceProofBlockedBySourceRecoveryAcceptance": source_recovery_blocks_proof,
        "scenes": review_scenes,
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "operatorReviewRequired": True,
        "proofArtifactCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "goalBoundary": boundary,
        "doesNotSatisfy": [
            "source review accepted/pass/ready evidence",
            "fresh-source-proof.json",
            "phone-review.json",
            "platform-analytics.json",
            "same-day upload decision",
            "broad live-channel operating-system Goal",
        ],
    }
    return {
        "packetDir": packet_dir,
        "projectId": project_id,
        "renderManifestPath": render_manifest_path,
        "handoffPath": handoff_path,
        "reviewPath": review_path,
        "handoffPayload": handoff_payload,
        "reviewPayload": review_payload,
        "sceneCount": len(scenes),
        "candidateReadySceneCount": len(candidate_ready_scene_ids),
        "reviewRequiredSceneCount": len(scenes),
        "operatorAcceptedSceneCount": 0,
        "freshSourceProofReadySceneCount": 0,
        "proofBlockerCount": proof_blocker_count,
        "scenesWithProofBlockers": scenes_with_proof_blockers,
        "sourceRecoveryAcceptanceStatus": source_recovery_acceptance,
        "sourceRecoveryAcceptanceBlockerCount": source_recovery_acceptance_blocker_count,
        "freshSourceProofBlockedBySourceRecoveryAcceptance": source_recovery_blocks_proof,
        "candidateReadySceneIds": candidate_ready_scene_ids,
        "goalBoundary": boundary,
    }


@media_bp.route("/api/final-video-library/fresh-source-evidence", methods=["POST"])
def final_video_library_fresh_source_evidence_route():
    """Prepare packet-local fresh-source handoff/review drafts without creating proof."""
    data = flask_request.get_json(silent=True) or {}
    limit = _coerce_final_video_library_limit(data.get("limit", 20))
    project_id = str(data.get("projectId") or "").strip()
    snapshot = _final_video_library_snapshot(limit)
    packets = snapshot["packets"]
    best_packet = snapshot["bestPacket"]
    if project_id:
        best_packet = next((item for item in packets if item.get("projectId") == project_id), None)
    if not isinstance(best_packet, dict):
        return jsonify({
            "ok": False,
            "error": "No final-video packet is available for fresh-source evidence prep.",
            "proofArtifactsCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
        }), 404

    latest_handoff_context = _latest_grok_handoff_context()
    latest_handoff = _latest_grok_handoff_summary(latest_handoff_context)
    handoff_project_id = str(latest_handoff.get("projectId") or latest_handoff_context.get("projectId") or "")
    source_recovery_plan = _source_recovery_plan(
        latest_handoff,
        _latest_pexels_replacement_research_summary(handoff_project_id),
        _latest_local_candidate_review_summary(handoff_project_id),
        _latest_pexels_expanded_search_summary(handoff_project_id),
    )
    source_recovery_acceptance = _source_recovery_acceptance_status(handoff_project_id, source_recovery_plan)
    payloads = _fresh_source_evidence_payloads(best_packet, source_recovery_acceptance)
    if payloads["sceneCount"] <= 0:
        return jsonify({
            "ok": False,
            "status": "missing-render-manifest-scenes",
            "projectId": best_packet.get("projectId"),
            "packetDir": best_packet.get("packetDir"),
            "error": "render-manifest.json has no scene evidence to prepare.",
            "artifactPaths": {},
            "proofArtifactsCreated": False,
            "freshSourceProofCreated": False,
            "goalComplete": False,
            "goalBoundary": payloads["goalBoundary"],
        }), 409

    handoff_path = payloads["handoffPath"]
    review_path = payloads["reviewPath"]
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(payloads["handoffPayload"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_path.write_text(json.dumps(payloads["reviewPayload"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fresh_source_repeatability = _fresh_source_repeatability_audit(best_packet, False)
    template = fresh_source_repeatability.get("template") if isinstance(fresh_source_repeatability.get("template"), dict) else {}
    template.update({
        "handoffProjectId": payloads["projectId"],
        "handoffManifestPath": str(handoff_path),
        "sourceReviewPath": str(review_path),
        "sourceEvidencePrep": {
            "status": "written-not-proof",
            "templateOnly": True,
            "operatorReviewRequired": True,
            "candidateReadySceneCount": payloads["candidateReadySceneCount"],
            "reviewRequiredSceneCount": payloads["reviewRequiredSceneCount"],
            "operatorAcceptedSceneCount": 0,
            "freshSourceProofReadySceneCount": 0,
            "proofBlockerCount": payloads["proofBlockerCount"],
            "scenesWithProofBlockers": payloads["scenesWithProofBlockers"],
            "sourceRecoveryAcceptanceStatus": payloads["sourceRecoveryAcceptanceStatus"],
            "sourceRecoveryAcceptanceBlockerCount": payloads["sourceRecoveryAcceptanceBlockerCount"],
            "freshSourceProofBlockedBySourceRecoveryAcceptance": payloads["freshSourceProofBlockedBySourceRecoveryAcceptance"],
            "handoffManifestPath": str(handoff_path),
            "sourceReviewPath": str(review_path),
            "goalBoundary": payloads["goalBoundary"],
        },
    })
    fresh_source_repeatability["template"] = template
    fresh_source_template = _goal_evidence_template_write(fresh_source_repeatability, "freshSourceRepeatability")
    return jsonify({
        "ok": True,
        "status": "written-not-proof",
        "projectId": best_packet.get("projectId"),
        "packetDir": best_packet.get("packetDir"),
        "artifactPaths": {
            "handoffManifestPath": str(handoff_path),
            "sourceReviewPath": str(review_path),
            "renderManifestPath": str(payloads["renderManifestPath"]),
        },
        "sceneCount": payloads["sceneCount"],
        "candidateReadySceneCount": payloads["candidateReadySceneCount"],
        "candidateReadySceneIds": payloads["candidateReadySceneIds"],
        "reviewRequiredSceneCount": payloads["reviewRequiredSceneCount"],
        "acceptedSceneCount": 0,
        "rejectedSceneCount": 0,
        "operatorAcceptedSceneCount": 0,
        "freshSourceProofReadySceneCount": 0,
        "proofBlockerCount": payloads["proofBlockerCount"],
        "scenesWithProofBlockers": payloads["scenesWithProofBlockers"],
        "sourceRecoveryAcceptanceStatus": payloads["sourceRecoveryAcceptanceStatus"],
        "sourceRecoveryAcceptanceBlockerCount": payloads["sourceRecoveryAcceptanceBlockerCount"],
        "freshSourceProofBlockedBySourceRecoveryAcceptance": payloads["freshSourceProofBlockedBySourceRecoveryAcceptance"],
        "freshSourceTemplate": fresh_source_template,
        "proofArtifactsCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "goalBoundary": payloads["goalBoundary"],
    })


@media_bp.route("/api/final-video-library/evidence-templates", methods=["POST"])
def final_video_library_evidence_templates_route():
    """Write operator worksheets for missing broad-Goal proof without creating proof artifacts."""
    data = flask_request.get_json(silent=True) or {}
    limit = _coerce_final_video_library_limit(data.get("limit", 20))
    project_id = str(data.get("projectId") or "").strip()
    snapshot = _final_video_library_snapshot(limit)
    packets = snapshot["packets"]
    best_packet = snapshot["bestPacket"]
    if project_id:
        best_packet = next((item for item in packets if item.get("projectId") == project_id), None)
    if not isinstance(best_packet, dict):
        return jsonify({
            "ok": False,
            "error": "No final-video packet is available for evidence templates.",
            "proofArtifactsCreated": False,
            "goalComplete": False,
        }), 404

    phone_review = _phone_sized_human_review_audit(best_packet, False)
    platform_analytics = _platform_analytics_audit(best_packet, False)
    fresh_source_repeatability = _fresh_source_repeatability_audit(best_packet, False)
    phone_template = _goal_evidence_template_write(phone_review, "phoneSizedHumanReview")
    analytics_template = _goal_evidence_template_write(platform_analytics, "platformAnalytics")
    fresh_source_template = _goal_evidence_template_write(fresh_source_repeatability, "freshSourceRepeatability")
    return jsonify({
        "ok": bool(phone_template.get("written") and analytics_template.get("written") and fresh_source_template.get("written")),
        "projectId": best_packet.get("projectId"),
        "packetDir": best_packet.get("packetDir"),
        "templates": {
            "freshSourceRepeatability": fresh_source_template,
            "phoneSizedHumanReview": phone_template,
            "platformAnalytics": analytics_template,
        },
        "proofArtifactsCreated": False,
        "goalComplete": False,
        "goalBoundary": (
            "Template materialization is operator prep only. It does not satisfy fresh-source repeatability, "
            "phone-sized human review, platform analytics, or the broad live-channel operating Goal."
        ),
    })


def _dashboard_smoke_visible_texts(value: object) -> list[str]:
    if isinstance(value, str):
        source_values = value.splitlines()
    elif isinstance(value, list):
        source_values = [str(item) for item in value]
    else:
        source_values = []
    visible_texts: list[str] = []
    for item in source_values:
        text = " ".join(str(item).split()).strip()
        if text:
            visible_texts.append(text)
    return visible_texts[:200]


@media_bp.route("/api/final-video-library/dashboard-smoke", methods=["POST"])
def final_video_library_dashboard_smoke_route():
    """Record browser-rendered final-library dashboard evidence inside a final-video packet."""
    data = flask_request.get_json(silent=True) or {}
    limit = _coerce_final_video_library_limit(data.get("limit", 20))
    project_id = str(data.get("projectId") or "").strip()
    snapshot = _final_video_library_snapshot(limit)
    packets = snapshot["packets"]
    best_packet = snapshot["bestPacket"]
    if project_id:
        best_packet = next((item for item in packets if item.get("projectId") == project_id), None)
    if not isinstance(best_packet, dict):
        return jsonify({
            "ok": False,
            "error": "No final-video packet is available for dashboard smoke capture.",
            "proofArtifactsCreated": False,
            "goalComplete": False,
        }), 404

    packet_dir_raw = str(best_packet.get("packetDir") or "").strip()
    packet_dir = Path(packet_dir_raw) if packet_dir_raw else None
    if not packet_dir:
        return jsonify({
            "ok": False,
            "error": "Final-video packet directory is missing.",
            "proofArtifactsCreated": False,
            "goalComplete": False,
        }), 400

    rendered_project_id = str(best_packet.get("projectId") or project_id).strip()
    smoke_path = packet_dir / "dashboard-smoke.json"
    smoke_payload = {
        "schema": "video-studio.final-library-dashboard-smoke.v1",
        "capturedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "video-studio-dashboard-ui",
        "projectId": rendered_project_id,
        "renderedProjectId": rendered_project_id,
        "surface": str(data.get("surface") or "final-library-dashboard").strip(),
        "browserRendered": data.get("browserRendered") is True,
        "bridgeConnected": data.get("bridgeConnected") is True,
        "finalLibraryPanelVisible": data.get("finalLibraryPanelVisible") is True,
        "preUploadReady": data.get("preUploadReady") is True,
        "visibleTexts": _dashboard_smoke_visible_texts(data.get("visibleTexts") or data.get("visibleText")),
        "url": str(data.get("url") or "").strip(),
        "userAgent": str(data.get("userAgent") or "").strip(),
        "proofArtifactsCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "goalBoundary": (
            "This browser-rendered dashboard smoke is packet-local evidence only. It does not create "
            "fresh-source-proof.json, phone-review.json, platform analytics, or broad Goal completion."
        ),
    }
    smoke_payload["ok"] = True
    issues = _fresh_source_dashboard_smoke_issues(smoke_payload, rendered_project_id)
    if issues:
        smoke_payload["ok"] = False
        smoke_payload["issues"] = issues
    smoke_payload["status"] = "pass" if smoke_payload["ok"] is True else "fail"

    packet_dir.mkdir(parents=True, exist_ok=True)
    smoke_path.write_text(json.dumps(smoke_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    smoke_sha256 = _sha256_file_digest(smoke_path)
    fresh_source_repeatability = _fresh_source_repeatability_audit(best_packet, False)
    fresh_source_template = _goal_evidence_template_write(fresh_source_repeatability, "freshSourceRepeatability")
    return jsonify({
        "ok": smoke_payload["ok"],
        "status": smoke_payload["status"],
        "projectId": rendered_project_id,
        "path": str(smoke_path),
        "sha256": smoke_sha256,
        "issues": issues,
        "smoke": smoke_payload,
        "freshSourceTemplate": fresh_source_template,
        "proofArtifactsCreated": False,
        "freshSourceProofCreated": False,
        "goalComplete": False,
        "goalBoundary": smoke_payload["goalBoundary"],
    })


def _phone_review_evidence_timestamp(best_packet: dict, fallback: float) -> float:
    try:
        duration = float(((best_packet or {}).get("ffprobe") or {}).get("durationSeconds") or 0)
    except (TypeError, ValueError, AttributeError):
        duration = 0.0
    if duration <= 0:
        return fallback
    timestamp = duration * fallback if 0 < fallback <= 1.0 else fallback
    return max(0.1, min(duration - 0.2, timestamp))


def _extract_phone_review_frame(final_video: Path, frame_path: Path, timestamp: float, viewport: str) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "path": str(frame_path), "issues": ["ffmpeg not found"]}
    if viewport == "phone":
        video_filter = "scale=390:844:force_original_aspect_ratio=decrease,pad=390:844:(ow-iw)/2:(oh-ih)/2,setsar=1"
    else:
        video_filter = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    result = _run_ffmpeg_command([
        ffmpeg,
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(final_video),
        "-frames:v",
        "1",
        "-vf",
        video_filter,
        "-q:v",
        "3",
        str(frame_path),
    ])
    issues: list[str] = []
    if not result or result.returncode != 0:
        issues.append("ffmpeg frame extraction failed")
    if not frame_path.exists():
        issues.append("frame was not created")
    return {"ok": not issues, "path": str(frame_path), "issues": issues}


def _write_phone_review_evidence_artifacts(best_packet: dict, data: dict) -> dict:
    packet_dir_raw = str(best_packet.get("packetDir") or "").strip()
    final_video_path = str(best_packet.get("finalVideoPath") or "").strip()
    packet_dir = Path(packet_dir_raw) if packet_dir_raw else None
    final_video = Path(final_video_path) if final_video_path else None
    if final_video and not final_video.is_absolute():
        final_video = _project_root / final_video
    if not packet_dir or not final_video or not final_video.exists():
        return {
            "ok": False,
            "status": "fail",
            "artifactPaths": {},
            "artifactChecks": {},
            "pendingFields": [],
            "issues": ["final-video packet or MP4 is missing"],
        }

    packet_dir.mkdir(parents=True, exist_ok=True)
    frame_specs = {
        "reviewSnapshotPath": (
            packet_dir / "phone-review-snapshot.jpg",
            _phone_review_evidence_timestamp(best_packet, 0.50),
            "phone",
        ),
        "captionSafeZoneFramePath": (
            packet_dir / "phone-caption-safe-zone.jpg",
            _phone_review_evidence_timestamp(best_packet, 0.45),
            "full",
        ),
        "thumbnailFirstFramePath": (
            packet_dir / "phone-thumbnail-first-frame.jpg",
            _phone_review_evidence_timestamp(best_packet, 0.10),
            "full",
        ),
    }
    artifact_paths: dict[str, str] = {}
    artifact_checks: dict[str, dict] = {}
    issues: list[str] = []
    for field, (frame_path, timestamp, viewport) in frame_specs.items():
        extraction = _extract_phone_review_frame(final_video, frame_path, timestamp, viewport)
        if extraction.get("ok") is not True:
            artifact_checks[field] = extraction
            issues.extend(str(item) for item in (extraction.get("issues") or []))
            continue
        check = _phone_review_artifact_check(field, frame_path)
        artifact_checks[field] = check
        artifact_paths[field] = str(frame_path)
        if check.get("ok") is not True:
            issues.extend(str(item) for item in (check.get("issues") or []))

    audio_path = packet_dir / "phone-audio-mix-evidence.json"
    audio_payload = {
        "schema": "video-studio.phone-audio-mix-evidence.v1",
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "video-studio-phone-review-evidence-prep",
        "finalVideoPath": final_video_path,
        "finalVideoSha256": _final_video_digest_value(final_video_path),
        "audioMeasurement": _measure_audio_level(final_video),
        "audioDevice": str(data.get("audioDevice") or "operator-phone-headphones-required").strip(),
        "headphonesUsed": data.get("headphonesUsed") is True,
        "bgmVoiceBalancePass": data.get("bgmVoiceBalancePass") is True,
        "voiceoverPolicyPass": data.get("voiceoverPolicyPass") is True,
        "bgmNonPlaceholderPass": data.get("bgmNonPlaceholderPass") is True,
        "audioMixReviewPass": data.get("audioMixReviewPass") is True,
        "operatorReviewRequired": True,
        "proofArtifactsCreated": False,
        "phoneReviewProofCreated": False,
        "goalComplete": False,
        "goalBoundary": (
            "This audio-mix evidence file is operator prep only until a human headphone review records pass fields."
        ),
    }
    audio_path.write_text(json.dumps(audio_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audio_check = _phone_review_artifact_check("audioMixEvidencePath", audio_path)
    artifact_paths["audioMixEvidencePath"] = str(audio_path)
    artifact_checks["audioMixEvidencePath"] = audio_check
    pending_fields = []
    if audio_check.get("ok") is not True:
        pending_fields.append("audioMixEvidencePath")

    image_fields = {"reviewSnapshotPath", "captionSafeZoneFramePath", "thumbnailFirstFramePath"}
    images_ready = all(artifact_checks.get(field, {}).get("ok") is True for field in image_fields)
    return {
        "ok": bool(images_ready and audio_path.exists()),
        "status": "prepared" if images_ready and audio_path.exists() else "fail",
        "artifactPaths": artifact_paths,
        "artifactChecks": artifact_checks,
        "pendingFields": pending_fields,
        "issues": sorted(set(issues)),
    }


@media_bp.route("/api/final-video-library/phone-review-evidence", methods=["POST"])
def final_video_library_phone_review_evidence_route():
    """Prepare packet-local phone-review evidence files without creating phone-review proof."""
    data = flask_request.get_json(silent=True) or {}
    limit = _coerce_final_video_library_limit(data.get("limit", 20))
    project_id = str(data.get("projectId") or "").strip()
    snapshot = _final_video_library_snapshot(limit)
    packets = snapshot["packets"]
    best_packet = snapshot["bestPacket"]
    if project_id:
        best_packet = next((item for item in packets if item.get("projectId") == project_id), None)
    if not isinstance(best_packet, dict):
        return jsonify({
            "ok": False,
            "error": "No final-video packet is available for phone-review evidence prep.",
            "proofArtifactsCreated": False,
            "phoneReviewProofCreated": False,
            "goalComplete": False,
        }), 404

    prep = _write_phone_review_evidence_artifacts(best_packet, data)
    phone_review = _phone_sized_human_review_audit(best_packet, False)
    template = phone_review.get("template") if isinstance(phone_review.get("template"), dict) else {}
    for field, path_value in (prep.get("artifactPaths") or {}).items():
        if field in _PHONE_REVIEW_ARTIFACT_PATH_FIELDS:
            template[field] = path_value
    phone_review["template"] = template
    phone_template = _goal_evidence_template_write(phone_review, "phoneSizedHumanReview")
    return jsonify({
        "ok": prep.get("ok") is True,
        "status": prep.get("status") or "fail",
        "projectId": best_packet.get("projectId"),
        "packetDir": best_packet.get("packetDir"),
        "artifactPaths": prep.get("artifactPaths") or {},
        "artifactChecks": prep.get("artifactChecks") or {},
        "pendingFields": prep.get("pendingFields") or [],
        "issues": prep.get("issues") or [],
        "phoneTemplate": phone_template,
        "proofArtifactsCreated": False,
        "phoneReviewProofCreated": False,
        "goalComplete": False,
        "goalBoundary": (
            "Phone-review evidence prep writes packet-local image/audio evidence and refreshes the worksheet only. "
            "It does not create phone-review.json, does not mark human review passed, and does not approve upload."
        ),
    })


def _goal_requirement(key: str, label: str, status: str, evidence: str, missing: list[str] | None = None) -> dict:
    return {
        "key": key,
        "label": label,
        "status": status,
        "evidence": evidence,
        "missing": missing or [],
    }


def _live_channel_operator_decision(
    goal_complete: bool,
    artifact_gate_complete: bool,
    artifact_ready: bool,
    upload_ready: bool,
    top_tier_ready: bool,
    source_motion: bool,
    all_remaining_gaps: list[str],
) -> dict:
    if goal_complete:
        return {
            "status": "upload",
            "label": "업로드 가능",
            "detail": "The artifact gate and broad live-channel operating-system requirements are complete.",
            "nextAction": "Use the publish packet for upload, then record live platform analytics.",
        }
    if not artifact_ready or not upload_ready or not top_tier_ready or not source_motion:
        return {
            "status": "rerender",
            "label": "재렌더 필요",
            "detail": "The best artifact is missing upload/top-tier/source-motion evidence, so it cannot be treated as a live-channel candidate.",
            "nextAction": "Fix the current packet, rerender/finalize, then rerun ffprobe, quality audit, and dashboard smoke.",
        }
    if artifact_gate_complete:
        gap_summary = "; ".join(all_remaining_gaps[:3]) if all_remaining_gaps else "Live-channel operating evidence is still incomplete."
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": f"Artifact gate is ready, but live-channel operation is not proven: {gap_summary}",
            "nextAction": "Finish fresh-source repeatability, phone-sized human review, and platform analytics before claiming channel operation readiness.",
        }
    gap_summary = "; ".join(all_remaining_gaps[:3]) if all_remaining_gaps else "Artifact gate is incomplete."
    return {
        "status": "edit",
        "label": "수정 필요",
        "detail": f"Audit pass is not enough for live upload: {gap_summary}",
        "nextAction": "Clear the listed artifact and operating-system gaps before any live-channel upload decision.",
    }


def _pre_upload_operator_decision(
    artifact_gate_complete: bool,
    artifact_ready: bool,
    upload_ready: bool,
    top_tier_ready: bool,
    source_motion: bool,
    fresh_source_batch_proven: bool,
    fresh_source_repeatability: dict,
    phone_review_proven: bool,
    phone_sized_human_review: dict,
    artifact_remaining_gaps: list[str],
) -> dict:
    if not artifact_ready or not upload_ready or not top_tier_ready or not source_motion:
        return {
            "status": "rerender",
            "label": "재렌더 필요",
            "detail": "The best packet is missing MP4/upload/top-tier/source-motion evidence, so it is not a same-day upload candidate.",
            "nextAction": "Rerender/finalize a moving-clip stitched 1080x1920/30fps/audio packet, then rerun ffprobe, quality audit, and dashboard smoke.",
        }
    if not artifact_gate_complete:
        gap_summary = "; ".join(artifact_remaining_gaps[:3]) if artifact_remaining_gaps else "Artifact gate is incomplete."
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": f"Same-day upload is blocked before human review: {gap_summary}",
            "nextAction": "Clear artifact-level gaps first: Grok/manual source provenance, caption safe zone, non-placeholder audio, source motion, publish packet, and top-tier audit evidence.",
        }
    if not fresh_source_batch_proven:
        fresh_status = str(fresh_source_repeatability.get("status") or "missing")
        fresh_action = str(
            fresh_source_repeatability.get("operatorAction")
            or "Run the fresh-source batch/manual Chrome intake, import moving Grok/manual MP4s, accept them through review, rerender/finalize, and rerun the library audit."
        )
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": f"Artifact gate is ready, but this is not a repeatable live-channel upload until explicit fresh-source proof is {fresh_status}.",
            "nextAction": fresh_action,
        }
    if not phone_review_proven:
        phone_status = str(phone_sized_human_review.get("status") or "missing")
        phone_action = str(phone_sized_human_review.get("operatorAction") or "Complete phone-review.json after a real phone-sized full watch.")
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": f"Automatic gates are not enough for a same-day channel upload; phone-sized human review is {phone_status}.",
            "nextAction": phone_action,
        }
    return {
        "status": "upload",
        "label": "업로드 가능",
        "detail": "Artifact gate, fresh-source repeatability proof, and phone-sized human review are ready for a same-day Shorts/TikTok/Reels upload decision.",
        "nextAction": "Upload or archive this packet, then record platform analytics after the sample window; analytics are required for broad operating-system completion.",
    }


def _goal_runway_checklist(
    *,
    artifact_gate_complete: bool,
    artifact_ready: bool,
    upload_ready: bool,
    top_tier_ready: bool,
    source_motion: bool,
    fresh_source_batch_proven: bool,
    fresh_source_repeatability: dict,
    latest_handoff: dict,
    source_recovery_plan: dict | None,
    source_recovery_acceptance: dict | None,
    phone_review_proven: bool,
    phone_sized_human_review: dict,
    pre_upload_ready: bool,
    pre_upload_decision: dict,
    platform_analytics_proven: bool,
    platform_analytics: dict,
    goal_complete: bool,
) -> dict:
    def item(
        key: str,
        label: str,
        status: str,
        detail: str,
        next_action: str,
        *,
        blocks_today_upload: bool,
        blocks_operating_goal: bool = True,
    ) -> dict:
        return {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "nextAction": next_action,
            "blocksTodayUpload": blocks_today_upload,
            "blocksOperatingGoal": blocks_operating_goal,
        }

    if artifact_gate_complete:
        artifact_status = "pass"
        artifact_detail = "Best packet has final MP4, ffprobe-ready output, upload/channel/top-tier audit evidence, publish packet, source motion, and live Grok/direct-import proof."
        artifact_action = "Keep artifact evidence attached to the packet; do not use it alone to close the broad operating-system Goal."
    elif not (artifact_ready and upload_ready and top_tier_ready and source_motion):
        artifact_status = "rerender"
        artifact_detail = "The best packet still lacks one or more same-day artifact gates: MP4/upload/top-tier/source-motion evidence."
        artifact_action = "Rerender/finalize a moving-clip stitched 1080x1920/30fps/audio packet, then rerun ffprobe, quality audit, publish packet audit, and dashboard smoke."
    else:
        artifact_status = "edit"
        artifact_detail = "The artifact has a candidate packet, but strict artifact proof is still incomplete."
        artifact_action = "Clear artifact-level gaps such as direct-import/source provenance, caption safety, non-placeholder audio, and publish packet content."

    latest_handoff = latest_handoff if isinstance(latest_handoff, dict) else {}
    handoff_available = latest_handoff.get("available") is True
    handoff_status = str(latest_handoff.get("status") or "missing")
    imported = int(latest_handoff.get("importedScenes") or 0)
    accepted = int(latest_handoff.get("acceptedScenes") or 0)
    total = int(latest_handoff.get("totalScenes") or 0)
    source_recovery_plan = source_recovery_plan if isinstance(source_recovery_plan, dict) else {}
    source_recovery_acceptance = source_recovery_acceptance if isinstance(source_recovery_acceptance, dict) else {}
    if fresh_source_batch_proven:
        source_status = "pass"
        source_detail = str(fresh_source_repeatability.get("detail") or "Fresh-source repeatability proof is bound to the audited final MP4.")
        source_action = "Use this proof only with the matching final MP4; next same-day gate is phone-sized human review."
    elif handoff_available:
        import_preflight = latest_handoff.get("importPreflightSummary") if isinstance(latest_handoff.get("importPreflightSummary"), dict) else {}
        if not import_preflight:
            import_preflight = latest_handoff.get("importPreflight") if isinstance(latest_handoff.get("importPreflight"), dict) else {}
        preflight_total = int(import_preflight.get("totalScenes") or total)
        preflight_ready = int(import_preflight.get("readyScenes") or 0)
        preflight_present = int(import_preflight.get("presentScenes") or imported)
        preflight_missing = import_preflight.get("missingScenes") or []
        preflight_stale = import_preflight.get("staleScenes") or []
        preflight_invalid = import_preflight.get("invalidScenes") or []
        rejected_scene_ids = [str(scene_id) for scene_id in (latest_handoff.get("rejectedSceneIds") or []) if scene_id]
        live_fail_categories = [str(category) for category in (latest_handoff.get("liveFailCategories") or []) if category]
        source_status = "missing" if imported == 0 else "edit"
        source_detail = (
            f"Current fresh-source handoff {latest_handoff.get('projectId') or 'unknown'} is {handoff_status}; "
            f"imported {imported}/{total}, accepted {accepted}/{total}; "
            f"import preflight ready {preflight_ready}/{preflight_total}, present {preflight_present} "
            f"(missing {len(preflight_missing)}, stale {len(preflight_stale)}, invalid {len(preflight_invalid)})."
        )
        if rejected_scene_ids:
            source_detail += (
                f" Rejected {len(rejected_scene_ids)} scene(s): {', '.join(rejected_scene_ids[:5])}; "
                f"live fail categories: {', '.join(live_fail_categories[:6]) or 'not recorded'}."
            )
        if int(source_recovery_plan.get("totalScenes") or 0) > 0:
            source_detail += (
                " Source recovery lanes: "
                f"local review {source_recovery_plan.get('localReviewScenes') or 0}, "
                f"selected-stock rewrite {source_recovery_plan.get('selectedStockRewriteAvailableScenes') or 0}, "
                f"direct-import regenerate {source_recovery_plan.get('regenerateDirectImportScenes') or 0}, "
                f"expanded Pexels {source_recovery_plan.get('expandedPexelsSearchScenes') or 0}, "
                f"import runway {source_recovery_plan.get('directImportRunwayScenes') or 0}."
            )
        acceptance_total = int(source_recovery_acceptance.get("totalScenes") or 0)
        if acceptance_total > 0:
            source_detail += (
                " Acceptance gate: "
                f"{source_recovery_acceptance.get('status') or 'unchecked'}, "
                f"accepted {source_recovery_acceptance.get('acceptedSceneCount') or 0}/{acceptance_total}, "
                f"incomplete {source_recovery_acceptance.get('incompleteSceneCount') or 0}; "
                f"required artifact {source_recovery_acceptance.get('requiredArtifactPath') or 'source-recovery-acceptance.json'}."
            )
        source_action = str(
            (latest_handoff.get("operatorDecision") or {}).get("nextAction")
            or latest_handoff.get("operatorAction")
            or fresh_source_repeatability.get("operatorAction")
            or "Import fresh native Grok/manual Chrome MP4s, review/accept every scene, rerender/finalize, then create fresh-source-proof.json."
        )
        if source_recovery_acceptance.get("blocksRender") is True:
            source_action = str(
                source_recovery_acceptance.get("operatorAction")
                or "Fill source-recovery-acceptance.json for every rejected scene before rerender or proof creation."
            )
        elif source_recovery_acceptance.get("status") == "accepted-replacements-ready-for-rerender":
            source_action = "Rerender with the accepted replacement sources, finalize/audit the packet, dashboard-smoke it, then create fresh-source-proof.json."
    else:
        source_status = "missing"
        source_detail = "No current fresh-source handoff is available to prove repeatable source acquisition."
        source_action = str(
            fresh_source_repeatability.get("operatorAction")
            or "Create a fresh Grok/manual Chrome source handoff, import moving MP4 scenes, review/accept them, rerender/finalize, then create fresh-source-proof.json."
        )

    proof_status = "pass" if fresh_source_batch_proven else "missing"
    proof_detail = str(
        fresh_source_repeatability.get("detail")
        or "fresh-source-proof.json is missing or not accepted as proof for the audited final MP4."
    )
    proof_action = str(
        fresh_source_repeatability.get("operatorAction")
        or "Create fresh-source-proof.json only after a different-topic moving-clip source run is imported, accepted, rendered, finalized, audited, packeted, and dashboard-smoked."
    )

    phone_status = "pass" if phone_review_proven else str(phone_sized_human_review.get("status") or "missing")
    phone_detail = str(phone_sized_human_review.get("detail") or "Phone-sized human review is missing.")
    phone_action = str(
        phone_sized_human_review.get("operatorAction")
        or "Watch the full MP4 on a phone-sized viewport with headphones and create phone-review.json before same-day upload approval."
    )

    upload_status = "pass" if pre_upload_ready else str(pre_upload_decision.get("status") or "edit")
    upload_detail = str(pre_upload_decision.get("detail") or "Same-day upload readiness is not approved.")
    upload_action = str(pre_upload_decision.get("nextAction") or "Finish the blocking source, proof, and phone-review gates before upload.")

    analytics_status = "pass" if platform_analytics_proven else str(platform_analytics.get("status") or "missing")
    analytics_detail = str(platform_analytics.get("detail") or "Live platform analytics proof is missing.")
    analytics_action = str(
        platform_analytics.get("operatorAction")
        or "After upload, record platform-analytics.json with 2s hold, 5s hold, AVD, rewatch, swipe-away, and next improvement action."
    )

    items = [
        item(
            "artifact-gate",
            "Artifact gate",
            artifact_status,
            artifact_detail,
            artifact_action,
            blocks_today_upload=True,
        ),
        item(
            "fresh-source-import-review",
            "Fresh source import and review",
            source_status,
            source_detail,
            source_action,
            blocks_today_upload=True,
        ),
        item(
            "fresh-source-proof",
            "Fresh source proof artifact",
            proof_status,
            proof_detail,
            proof_action,
            blocks_today_upload=True,
        ),
        item(
            "phone-sized-human-review",
            "Phone-sized human review",
            phone_status,
            phone_detail,
            phone_action,
            blocks_today_upload=True,
        ),
        item(
            "same-day-upload-decision",
            "Same-day upload decision",
            upload_status,
            upload_detail,
            upload_action,
            blocks_today_upload=not pre_upload_ready,
            blocks_operating_goal=False,
        ),
        item(
            "platform-analytics-loop",
            "Platform analytics loop",
            analytics_status,
            analytics_detail,
            analytics_action,
            blocks_today_upload=False,
        ),
    ]
    today_blocker = next((entry for entry in items if entry["status"] != "pass" and entry["blocksTodayUpload"]), None)
    operating_blocker = next((entry for entry in items if entry["status"] != "pass" and entry["blocksOperatingGoal"]), None)
    return {
        "items": items,
        "summary": {
            "readyForTodayUpload": pre_upload_ready,
            "readyForOperatingGoal": goal_complete,
            "primaryBlockerKey": (today_blocker or operating_blocker or {}).get("key", ""),
            "primaryBlockerLabel": (today_blocker or operating_blocker or {}).get("label", ""),
            "primaryBlockerDetail": (today_blocker or operating_blocker or {}).get("detail", ""),
            "nextAction": (today_blocker or operating_blocker or {}).get("nextAction", "Maintain the upload packet and record post-upload analytics."),
        },
    }


def _proof_path_matches_final_video(value: object, final_video_path: str) -> bool:
    text = str(value or "").strip()
    expected = str(final_video_path or "").strip()
    if not text or not expected:
        return False

    def normalized(path_text: str) -> str:
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = _project_root / candidate
        return os.path.normcase(os.path.abspath(str(candidate)))

    try:
        return normalized(text) == normalized(expected)
    except (OSError, ValueError):
        return text.replace("\\", "/").casefold() == expected.replace("\\", "/").casefold()


def _packet_artifact_path(packet_dir: Path | None, value: object) -> Path | None:
    if not packet_dir:
        return None
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    candidates = [candidate] if candidate.is_absolute() else [packet_dir / candidate, _project_root / candidate]
    try:
        packet_root = packet_dir.resolve()
    except (OSError, ValueError):
        return None
    for item in candidates:
        try:
            resolved = item.resolve()
        except (OSError, ValueError):
            continue
        try:
            in_current_packet = resolved.is_relative_to(packet_root)
        except ValueError:
            in_current_packet = False
        if in_current_packet and resolved.exists() and resolved.is_file():
            return resolved
    return None


def _final_video_digest_value(final_video_path: str) -> str:
    text = str(final_video_path or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = _project_root / candidate
    try:
        if not candidate.exists():
            return ""
        return _sha256_file_digest(candidate)
    except OSError:
        return ""


def _final_video_digest_check(final_video_path: str, expected_value: object) -> dict:
    expected = str(expected_value or "").strip().lower()
    actual = ""
    issues: list[str] = []
    if not expected:
        issues.append("finalVideoSha256 is missing")
    elif not re.fullmatch(r"[0-9a-f]{64}", expected):
        issues.append("finalVideoSha256 must be a 64-character lowercase hex SHA-256 digest")
    text = str(final_video_path or "").strip()
    candidate = Path(text) if text else None
    if candidate and not candidate.is_absolute():
        candidate = _project_root / candidate
    if candidate and candidate.exists():
        try:
            actual = _sha256_file_digest(candidate)
        except OSError:
            issues.append("audited final MP4 could not be read for SHA-256 verification")
        if expected and re.fullmatch(r"[0-9a-f]{64}", expected) and actual and actual != expected:
            issues.append("finalVideoSha256 does not match finalVideoPath bytes")
    elif expected:
        issues.append("audited final MP4 is unavailable for SHA-256 verification")
    return {
        "ok": not issues,
        "expectedSha256": expected,
        "actualSha256": actual,
        "path": str(candidate) if candidate else "",
        "issues": issues,
    }


def _evidence_artifact_digest_check(
    digest_field: str,
    path_field: str,
    path: Path | None,
    expected_value: object,
) -> dict:
    expected = str(expected_value or "").strip().lower()
    actual = ""
    issues: list[str] = []
    if not expected:
        issues.append(f"{digest_field} is missing")
    elif not re.fullmatch(r"[0-9a-f]{64}", expected):
        issues.append(f"{digest_field} must be a 64-character lowercase hex SHA-256 digest")
    if path and path.exists():
        try:
            actual = _sha256_file_digest(path)
        except OSError:
            issues.append(f"{path_field} could not be read for SHA-256 verification")
        if expected and re.fullmatch(r"[0-9a-f]{64}", expected) and actual and actual != expected:
            issues.append(f"{digest_field} does not match {path_field} bytes")
    elif expected:
        issues.append(f"{path_field} is unavailable for {digest_field} verification")
    return {
        "ok": not issues,
        "expectedSha256": expected,
        "actualSha256": actual,
        "path": str(path) if path else "",
        "pathField": path_field,
        "issues": issues,
    }


_PHONE_REVIEW_TEXT_FIELD_ALIASES = {
    "reviewedAt": ("reviewedAt",),
    "deviceClass": ("deviceClass",),
    "deviceViewport": ("deviceViewport", "viewport", "phoneViewport"),
    "reviewerType": ("reviewerType",),
    "reviewerId": ("reviewerId", "reviewer", "reviewerName"),
    "reviewMethod": ("reviewMethod", "method"),
    "audioDevice": ("audioDevice", "headphonesModel", "audioReviewDevice"),
    "finalVideoPath": ("finalVideoPath", "finalMp4", "finalVideo"),
    "finalVideoSha256": ("finalVideoSha256", "finalMp4Sha256", "finalVideoDigest"),
    "reviewSnapshotPath": ("reviewSnapshotPath", "phoneReviewSnapshotPath", "phonePlaybackSnapshotPath", "deviceSnapshotPath"),
    "captionSafeZoneFramePath": ("captionSafeZoneFramePath", "captionSafeZoneArtifactPath", "mobileCaptionReviewPath"),
    "thumbnailFirstFramePath": ("thumbnailFirstFramePath", "firstFramePath", "firstFrameReviewPath", "thumbnailReviewPath"),
    "audioMixEvidencePath": ("audioMixEvidencePath", "audioReviewPath", "audioMixReviewPath"),
    "reviewSnapshotSha256": ("reviewSnapshotSha256", "phoneReviewSnapshotSha256", "reviewSnapshotDigest"),
    "captionSafeZoneFrameSha256": ("captionSafeZoneFrameSha256", "captionSafeZoneSha256", "captionSafeZoneDigest"),
    "thumbnailFirstFrameSha256": ("thumbnailFirstFrameSha256", "thumbnailSha256", "firstFrameSha256", "thumbnailDigest"),
    "audioMixEvidenceSha256": ("audioMixEvidenceSha256", "audioMixSha256", "audioReviewSha256", "audioMixDigest"),
    "reviewerDecision": ("reviewerDecision", "decision"),
}
_PHONE_REVIEW_NUMBER_FIELDS = ("watchDurationSeconds",)
_PHONE_REVIEW_TRUE_FIELD_ALIASES = {
    "fullWatchCompleted": ("fullWatchCompleted",),
    "headphonesUsed": ("headphonesUsed", "headphones"),
    "captionSafeZonePass": ("captionSafeZonePass",),
    "mobileReadabilityPass": ("mobileReadabilityPass",),
    "voiceoverPolicyPass": ("voiceoverPolicyPass", "ttsVoiceoverPolicyPass", "voicePolicyPass", "ttsNarrationPass"),
    "bgmVoiceBalancePass": ("bgmVoiceBalancePass",),
    "bgmNonPlaceholderPass": ("bgmNonPlaceholderPass",),
    "firstTwoSecondHookPass": ("firstTwoSecondHookPass",),
    "cutDensityPass": ("cutDensityPass",),
    "aiSlopVisualFitPass": ("aiSlopVisualFitPass",),
    "stockAiClipFitPass": ("stockAiClipFitPass", "stockClipFitPass", "sourceClipFitPass"),
    "thumbnailFirstFramePass": ("thumbnailFirstFramePass",),
}
_PHONE_REVIEW_REQUIRED_FIELDS = [
    *_PHONE_REVIEW_TEXT_FIELD_ALIASES.keys(),
    *_PHONE_REVIEW_NUMBER_FIELDS,
    *_PHONE_REVIEW_TRUE_FIELD_ALIASES.keys(),
]
_PHONE_REVIEW_ARTIFACT_PATH_FIELDS = {
    "reviewSnapshotPath",
    "captionSafeZoneFramePath",
    "thumbnailFirstFramePath",
    "audioMixEvidencePath",
}
_PHONE_REVIEW_ARTIFACT_DIGEST_FIELDS = {
    "reviewSnapshotPath": "reviewSnapshotSha256",
    "captionSafeZoneFramePath": "captionSafeZoneFrameSha256",
    "thumbnailFirstFramePath": "thumbnailFirstFrameSha256",
    "audioMixEvidencePath": "audioMixEvidenceSha256",
}
_PHONE_REVIEW_IMAGE_ARTIFACT_REQUIREMENTS = {
    "reviewSnapshotPath": {"min_width": 360, "min_height": 640, "min_bytes": 1024, "require_portrait": True},
    "captionSafeZoneFramePath": {"min_width": 720, "min_height": 1280, "min_bytes": 1024, "require_portrait": True},
    "thumbnailFirstFramePath": {"min_width": 720, "min_height": 1280, "min_bytes": 1024, "require_portrait": True},
}
_PHONE_REVIEW_CSS_VIEWPORT_RANGE = {
    "minWidth": 320,
    "maxWidth": 480,
    "minHeight": 568,
    "maxHeight": 1000,
}
_PHONE_REVIEW_NATIVE_VIEWPORT_RANGE = {
    "minWidth": 720,
    "maxWidth": 1440,
    "minHeight": 1280,
    "maxHeight": 3200,
}
_PHONE_AUDIO_EVIDENCE_DEVICE_FIELDS = ("audioDevice", "headphonesModel", "device", "reviewDevice")
_PHONE_AUDIO_EVIDENCE_TRUE_FIELDS = (
    "headphonesUsed",
    "headphones",
    "bgmVoiceBalancePass",
    "voiceoverPolicyPass",
    "bgmNonPlaceholderPass",
    "audioMixReviewPass",
)
_PHONE_REVIEW_HUMAN_REVIEWER_TYPES = {"human", "operator", "creator", "human-reviewer", "human_reviewer"}
_PHONE_REVIEW_FULL_WATCH_METHODS = {
    "real-phone-full-watch",
    "phone-sized-full-watch",
    "phone-sized-human-full-watch",
    "mobile-full-watch",
    "mobile-human-full-watch",
}
_PHONE_REVIEW_PASS_DECISIONS = {"pass", "approved", "upload-ready", "upload_ready", "ready"}
_PHONE_REVIEW_FAIL_DECISIONS = {
    "fail",
    "failed",
    "reject",
    "rejected",
    "blocked",
    "needs-edit",
    "needs_edit",
    "needs-rerender",
    "needs_rerender",
}


def _phone_review_text(review: dict, field: str) -> str:
    for alias in _PHONE_REVIEW_TEXT_FIELD_ALIASES.get(field, (field,)):
        text = str(review.get(alias) or "").strip()
        if text:
            return text
    return str(review.get(field) or "").strip()


def _phone_review_number_present(record: dict, field: str, expected_duration_seconds: float | None) -> tuple[bool, bool]:
    if field not in record:
        return False, False
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return True, False
    if field == "watchDurationSeconds":
        minimum_duration = max(1.0, float(expected_duration_seconds or 0) - 0.5)
        return True, float(value) >= minimum_duration
    return True, value >= 0


def _phone_review_bool(review: dict, field: str) -> tuple[bool, bool]:
    for alias in _PHONE_REVIEW_TRUE_FIELD_ALIASES.get(field, (field,)):
        if alias in review:
            return True, review.get(alias) is True
    return False, False


def _phone_review_viewport_check(value: object) -> dict:
    text = str(value or "").strip()
    width = None
    height = None
    dimension_match = re.search(r"(\d{2,4})\s*(?:x|X|×|by)\s*(\d{2,4})", text)
    if dimension_match:
        width = int(dimension_match.group(1))
        height = int(dimension_match.group(2))
    else:
        width_match = re.search(r"(?:width|w)\D{0,8}(\d{2,4})", text, flags=re.IGNORECASE)
        height_match = re.search(r"(?:height|h)\D{0,8}(\d{2,4})", text, flags=re.IGNORECASE)
        if width_match and height_match:
            width = int(width_match.group(1))
            height = int(height_match.group(1))

    issues: list[str] = []
    if width is None or height is None:
        issues.append("deviceViewport must include parseable dimensions such as 390x844")
    else:
        ratio = height / width if width else 0
        css_range = _PHONE_REVIEW_CSS_VIEWPORT_RANGE
        native_range = _PHONE_REVIEW_NATIVE_VIEWPORT_RANGE
        css_phone_sized = (
            css_range["minWidth"] <= width <= css_range["maxWidth"]
            and css_range["minHeight"] <= height <= css_range["maxHeight"]
        )
        native_phone_sized = (
            native_range["minWidth"] <= width <= native_range["maxWidth"]
            and native_range["minHeight"] <= height <= native_range["maxHeight"]
        )
        if height <= width:
            issues.append("deviceViewport must be portrait")
        if not 1.5 <= ratio <= 2.8:
            issues.append("deviceViewport aspect ratio is outside phone portrait range")
        if not (css_phone_sized or native_phone_sized):
            issues.append("deviceViewport must be phone-sized CSS pixels or native portrait phone pixels")

    return {
        "ok": not issues,
        "value": text,
        "width": width,
        "height": height,
        "cssPhoneRange": _PHONE_REVIEW_CSS_VIEWPORT_RANGE,
        "nativePhoneRange": _PHONE_REVIEW_NATIVE_VIEWPORT_RANGE,
        "issues": issues,
    }


def _phone_review_artifact_path(packet_dir: Path | None, value: object) -> Path | None:
    return _packet_artifact_path(packet_dir, value)


def _phone_review_artifact_digest_check(
    digest_field: str,
    path_field: str,
    path: Path | None,
    expected_value: object,
) -> dict:
    return _evidence_artifact_digest_check(digest_field, path_field, path, expected_value)


def _phone_audio_mix_evidence_check(path: Path) -> dict:
    issues: list[str] = []
    try:
        byte_count = path.stat().st_size
    except OSError:
        byte_count = 0
        issues.append("file is unreadable")
    parsed = _read_json_artifact(path) if path.suffix.lower() == ".json" else None
    if path.suffix.lower() != ".json" or not isinstance(parsed, dict):
        issues.append("expected JSON object audio-mix evidence")
    if isinstance(parsed, dict):
        has_device = any(_truthy_text(parsed.get(field)) for field in _PHONE_AUDIO_EVIDENCE_DEVICE_FIELDS)
        has_headphones = any(parsed.get(field) is True for field in ("headphonesUsed", "headphones"))
        has_audio_pass = any(parsed.get(field) is True for field in _PHONE_AUDIO_EVIDENCE_TRUE_FIELDS)
        if not has_device:
            issues.append("audio device evidence is missing")
        if not has_headphones:
            issues.append("headphones evidence is missing")
        if not has_audio_pass:
            issues.append("audio pass evidence is missing")
    return {
        "ok": not issues,
        "kind": "audio-mix-json",
        "path": str(path),
        "bytes": byte_count,
        "issues": issues,
    }


def _phone_review_artifact_check(field: str, path: Path) -> dict:
    image_requirements = _PHONE_REVIEW_IMAGE_ARTIFACT_REQUIREMENTS.get(field)
    if image_requirements:
        return _image_evidence_check(path, **image_requirements)
    if field == "audioMixEvidencePath":
        return _phone_audio_mix_evidence_check(path)
    return {
        "ok": True,
        "kind": "file",
        "path": str(path),
        "issues": [],
    }


def _phone_sized_human_review_audit(best_packet: dict | None, legacy_summary_ready: bool) -> dict:
    packet_dir_raw = str(best_packet.get("packetDir") or "").strip() if isinstance(best_packet, dict) else ""
    artifact_path = Path(packet_dir_raw) / "phone-review.json" if packet_dir_raw else None
    template_path = Path(packet_dir_raw) / "phone-review.template.json" if packet_dir_raw else None
    final_video_path = str(best_packet.get("finalVideoPath") or "").strip() if isinstance(best_packet, dict) else ""
    final_video_sha256 = _final_video_digest_value(final_video_path)
    template = {
        "reviewedAt": "",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "",
        "finalVideoPath": final_video_path,
        "finalVideoSha256": final_video_sha256,
        "reviewSnapshotPath": "",
        "captionSafeZoneFramePath": "",
        "thumbnailFirstFramePath": "",
        "audioMixEvidencePath": "",
        "reviewSnapshotSha256": "",
        "captionSafeZoneFrameSha256": "",
        "thumbnailFirstFrameSha256": "",
        "audioMixEvidenceSha256": "",
        "evidenceRequirements": {
            "reviewedAt": "ISO-8601 timestamp with timezone offset for when the phone full-watch review was completed.",
            "finalVideoSha256": "SHA-256 digest of the exact finalVideoPath MP4 bytes reviewed on phone.",
            "deviceViewport": "Portrait phone-sized viewport such as 390x844 CSS pixels, or native portrait phone pixels such as 1080x1920.",
            "reviewSnapshotPath": "PNG/JPEG phone playback snapshot stored inside this final-video packet, at least 360x640 and 1024 bytes.",
            "captionSafeZoneFramePath": "PNG/JPEG caption safe-zone frame stored inside this final-video packet, at least 720x1280 and 1024 bytes.",
            "thumbnailFirstFramePath": "PNG/JPEG thumbnail or first-frame evidence stored inside this final-video packet, at least 720x1280 and 1024 bytes.",
            "audioMixEvidencePath": "JSON object stored inside this final-video packet with audio device, headphones, and audio pass evidence.",
            "reviewSnapshotSha256": "SHA-256 digest of reviewSnapshotPath bytes captured in this phone review.",
            "captionSafeZoneFrameSha256": "SHA-256 digest of captionSafeZoneFramePath bytes captured in this phone review.",
            "thumbnailFirstFrameSha256": "SHA-256 digest of thumbnailFirstFramePath bytes captured in this phone review.",
            "audioMixEvidenceSha256": "SHA-256 digest of audioMixEvidencePath bytes captured in this phone review.",
        },
        "watchDurationSeconds": 0,
        "fullWatchCompleted": False,
        "headphonesUsed": False,
        "captionSafeZonePass": False,
        "mobileReadabilityPass": False,
        "voiceoverPolicyPass": False,
        "bgmVoiceBalancePass": False,
        "bgmNonPlaceholderPass": False,
        "firstTwoSecondHookPass": False,
        "cutDensityPass": False,
        "aiSlopVisualFitPass": False,
        "stockAiClipFitPass": False,
        "thumbnailFirstFramePass": False,
        "reviewerDecision": "needs-review",
        "notes": "",
    }
    base = {
        "recorded": False,
        "ready": False,
        "status": "missing",
        "artifactPath": str(artifact_path) if artifact_path else "",
        "templateArtifactPath": str(template_path) if template_path else "",
        "template": template,
        "requiredFields": _PHONE_REVIEW_REQUIRED_FIELDS,
        "missingFields": list(_PHONE_REVIEW_REQUIRED_FIELDS),
        "failedFields": [],
        "evidenceArtifactPaths": {},
        "evidenceArtifactChecks": {},
        "evidenceDigestChecks": {},
        "finalVideoDigestCheck": {},
        "reviewedAtCheck": {},
        "deviceViewportCheck": {},
        "reviewerDecision": "",
        "legacySummaryReady": legacy_summary_ready,
        "detail": "Phone-sized pre-upload review artifact is missing.",
        "operatorAction": "Watch the full MP4 as a human/operator on a phone-sized viewport with headphones, then create phone-review.json with reviewer identity, review method, audio device, watch duration, every required pass field, and viewer-facing quality checks before treating the candidate as live-upload approved.",
    }
    if not artifact_path:
        base["detail"] = "No best final-video packet is available for phone-sized human review."
        return base
    if not artifact_path.exists():
        if legacy_summary_ready:
            base["status"] = "summary-only"
            base["detail"] = "A report summary claims phone review readiness, but phone-review.json is missing; summary-only evidence is not enough for the broad operating Goal."
        return base

    parsed = _read_json_artifact(artifact_path)
    if not isinstance(parsed, dict):
        return {
            **base,
            "recorded": True,
            "status": "fail",
            "detail": "phone-review.json exists but is not valid JSON object evidence.",
            "operatorAction": "Fix phone-review.json, then rerun the final-library audit before any upload decision.",
        }

    missing_fields: list[str] = []
    failed_fields: list[str] = []
    failed_fields.extend(_proof_template_boundary_failed_fields(parsed))
    expected_duration_seconds = None
    try:
        expected_duration_seconds = float(((best_packet or {}).get("ffprobe") or {}).get("durationSeconds") or 0)
    except (TypeError, ValueError, AttributeError):
        expected_duration_seconds = None
    for field in _PHONE_REVIEW_TEXT_FIELD_ALIASES:
        if not _phone_review_text(parsed, field):
            missing_fields.append(field)
    reviewed_at = _phone_review_text(parsed, "reviewedAt")
    reviewed_at_check = _audit_timestamp_check("reviewedAt", reviewed_at) if reviewed_at else {}
    if reviewed_at and reviewed_at_check.get("ok") is not True:
        failed_fields.append("reviewedAt")
    reviewed_final_video_path = _phone_review_text(parsed, "finalVideoPath")
    if (
        reviewed_final_video_path
        and final_video_path
        and not _proof_path_matches_final_video(reviewed_final_video_path, final_video_path)
    ):
        failed_fields.append("finalVideoPath")
    reviewed_final_video_sha256 = _phone_review_text(parsed, "finalVideoSha256")
    final_video_digest_check = _final_video_digest_check(final_video_path, reviewed_final_video_sha256)
    if reviewed_final_video_sha256 and final_video_digest_check.get("ok") is not True:
        failed_fields.append("finalVideoSha256")
    device_viewport = _phone_review_text(parsed, "deviceViewport")
    device_viewport_check = _phone_review_viewport_check(device_viewport) if device_viewport else {}
    if device_viewport and device_viewport_check.get("ok") is not True:
        failed_fields.append("deviceViewport")
    packet_dir = Path(packet_dir_raw) if packet_dir_raw else None
    evidence_artifact_paths: dict[str, str] = {}
    evidence_artifact_checks: dict[str, dict] = {}
    evidence_artifact_resolved_paths: dict[str, Path] = {}
    for field in _PHONE_REVIEW_ARTIFACT_PATH_FIELDS:
        path_text = _phone_review_text(parsed, field)
        if path_text:
            artifact_path_value = _phone_review_artifact_path(packet_dir, path_text)
            if artifact_path_value:
                evidence_artifact_resolved_paths[field] = artifact_path_value
                artifact_check = _phone_review_artifact_check(field, artifact_path_value)
                evidence_artifact_checks[field] = artifact_check
                if artifact_check.get("ok") is True:
                    evidence_artifact_paths[field] = str(artifact_path_value)
                else:
                    failed_fields.append(field)
            else:
                evidence_artifact_checks[field] = {
                    "ok": False,
                    "kind": "path",
                    "path": path_text,
                    "issues": ["artifact path is missing, outside the current final-video packet, or not a file"],
                }
                failed_fields.append(field)
    evidence_digest_checks: dict[str, dict] = {}
    for path_field, digest_field in _PHONE_REVIEW_ARTIFACT_DIGEST_FIELDS.items():
        digest_text = _phone_review_text(parsed, digest_field)
        artifact_path_value = evidence_artifact_resolved_paths.get(path_field)
        digest_check = _phone_review_artifact_digest_check(
            digest_field,
            path_field,
            artifact_path_value,
            digest_text,
        )
        evidence_digest_checks[digest_field] = digest_check
        if digest_text and digest_check.get("ok") is not True:
            failed_fields.append(digest_field)
    reviewer_type = _phone_review_text(parsed, "reviewerType").lower()
    if reviewer_type and reviewer_type not in _PHONE_REVIEW_HUMAN_REVIEWER_TYPES:
        failed_fields.append("reviewerType")
    review_method = _phone_review_text(parsed, "reviewMethod").lower()
    if review_method and review_method not in _PHONE_REVIEW_FULL_WATCH_METHODS:
        failed_fields.append("reviewMethod")
    for field in _PHONE_REVIEW_NUMBER_FIELDS:
        present, valid = _phone_review_number_present(parsed, field, expected_duration_seconds)
        if not present:
            missing_fields.append(field)
        elif not valid:
            failed_fields.append(field)
    for field in _PHONE_REVIEW_TRUE_FIELD_ALIASES:
        present, passed = _phone_review_bool(parsed, field)
        if not present:
            missing_fields.append(field)
        elif not passed:
            failed_fields.append(field)

    reviewer_decision = _phone_review_text(parsed, "reviewerDecision").lower()
    if reviewer_decision in _PHONE_REVIEW_FAIL_DECISIONS and "reviewerDecision" not in failed_fields:
        failed_fields.append("reviewerDecision")
    ready = bool(not missing_fields and not failed_fields and reviewer_decision in _PHONE_REVIEW_PASS_DECISIONS)
    if ready:
        status = "pass"
        detail = "Phone-sized full-watch review passed with headphones and mobile readability evidence."
        operator_action = "Keep this phone-review.json with the publish packet; broad Goal still also requires fresh-source repeatability and platform analytics."
    elif failed_fields:
        status = "fail"
        detail = f"Phone-sized review failed fields: {', '.join(failed_fields)}."
        operator_action = "Fix the failed viewer-facing issues, rerender if needed, and repeat the phone-sized full-watch review."
    else:
        status = "needs-review"
        detail = "phone-review.json is present but incomplete or lacks reviewerDecision=pass."
        operator_action = "Complete every required field after a real phone-sized full watch before claiming upload readiness."

    return {
        **base,
        "recorded": True,
        "ready": ready,
        "status": status,
        "missingFields": missing_fields,
        "failedFields": failed_fields,
        "reviewerDecision": reviewer_decision,
        "evidenceArtifactPaths": evidence_artifact_paths,
        "evidenceArtifactChecks": evidence_artifact_checks,
        "evidenceDigestChecks": evidence_digest_checks,
        "finalVideoDigestCheck": final_video_digest_check,
        "reviewedAtCheck": reviewed_at_check,
        "deviceViewportCheck": device_viewport_check,
        "detail": detail,
        "operatorAction": operator_action,
    }


_PLATFORM_ANALYTICS_TEXT_FIELD_ALIASES = {
    "recordedAt": ("recordedAt",),
    "platform": ("platform",),
    "publishUrl": ("publishUrl", "postUrl", "url"),
    "publishedAt": ("publishedAt",),
    "metricSource": ("metricSource", "source"),
    "analyticsSnapshotPath": ("analyticsSnapshotPath", "metricSnapshotPath", "metricScreenshotPath", "analyticsArtifactPath"),
    "analyticsSnapshotSha256": ("analyticsSnapshotSha256", "snapshotSha256", "analyticsScreenshotSha256"),
    "finalVideoPath": ("finalVideoPath", "finalMp4", "finalVideo"),
    "finalVideoSha256": ("finalVideoSha256", "finalMp4Sha256", "finalVideoDigest"),
    "decision": ("decision", "operatorDecision", "reviewerDecision"),
    "nextImprovementAction": ("nextImprovementAction", "nextAction", "improvementAction"),
}
_PLATFORM_ANALYTICS_NUMBER_FIELDS = (
    "sampleWindowHours",
    "views",
    "twoSecondHoldRate",
    "fiveSecondHoldRate",
    "averageViewDurationSeconds",
    "rewatchRate",
    "swipeAwayRate",
)
_PLATFORM_ANALYTICS_REQUIRED_FIELDS = [
    *_PLATFORM_ANALYTICS_TEXT_FIELD_ALIASES.keys(),
    *_PLATFORM_ANALYTICS_NUMBER_FIELDS,
]
_PLATFORM_ANALYTICS_READY_DECISIONS = {
    "recorded",
    "iterate",
    "iterating",
    "pass",
    "scale",
    "archive",
    "improve-next",
    "improve_next",
}
_PLATFORM_ANALYTICS_FAIL_DECISIONS = {"missing", "invalid", "blocked", "not-uploaded", "not_uploaded", "fail"}
_PLATFORM_ANALYTICS_ALLOWED_PLATFORMS = {
    "youtube_shorts": ("youtube.com", "youtu.be"),
    "tiktok": ("tiktok.com",),
    "instagram_reels": ("instagram.com",),
}
_PLATFORM_ANALYTICS_RATE_FIELDS = {
    "twoSecondHoldRate",
    "fiveSecondHoldRate",
    "rewatchRate",
    "swipeAwayRate",
}
_PLATFORM_ANALYTICS_NEXT_ACTION_MIN_CHARS = 24
_PLATFORM_ANALYTICS_ACTIONABLE_TERMS = (
    "hook",
    "opening",
    "title",
    "caption",
    "safe zone",
    "thumbnail",
    "first-frame",
    "first frame",
    "source",
    "clip",
    "cut",
    "pacing",
    "bgm",
    "voiceover",
    "tts",
    "audio",
    "retention",
    "rewatch",
    "swipe",
    "hold",
    "views",
    "description",
    "hashtag",
    "훅",
    "오프닝",
    "제목",
    "자막",
    "썸네일",
    "첫프레임",
    "첫 프레임",
    "소스",
    "클립",
    "컷",
    "음악",
    "보이스",
    "음성",
    "리텐션",
    "재시청",
    "스와이프",
    "조회",
    "설명",
    "해시태그",
)
_PLATFORM_ANALYTICS_GENERIC_ACTIONS = {
    "ok",
    "okay",
    "done",
    "n/a",
    "na",
    "none",
    "todo",
    "test",
    "try",
    "fix",
    "improve",
    "improve next",
    "next time",
}


def _analytics_text(record: dict, field: str) -> str:
    for alias in _PLATFORM_ANALYTICS_TEXT_FIELD_ALIASES.get(field, (field,)):
        text = str(record.get(alias) or "").strip()
        if text:
            return text
    return ""


def _analytics_snapshot_exists(packet_dir: Path | None, value: object) -> bool:
    if not packet_dir:
        return False
    return _artifact_path_exists(packet_dir, value)


def _analytics_snapshot_artifact_path(packet_dir: Path | None, value: object) -> Path | None:
    return _phone_review_artifact_path(packet_dir, value)


def _analytics_publish_url_matches_platform(publish_url: str, platform: str) -> bool:
    allowed_hosts = _PLATFORM_ANALYTICS_ALLOWED_PLATFORMS.get(platform) or ()
    try:
        hostname = str(urlparse(publish_url).hostname or "").lower()
    except ValueError:
        hostname = ""
    return bool(hostname and any(hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts))


def _parse_audit_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _audit_timestamp_check(field: str, value: object, require_timezone: bool = True) -> dict:
    text = str(value or "").strip()
    parsed = _parse_audit_datetime(text)
    issues: list[str] = []
    timezone_provided = False
    if not text:
        issues.append(f"{field} is missing")
    elif not parsed:
        issues.append(f"{field} must be ISO-8601 datetime evidence")
    else:
        timezone_provided = parsed.tzinfo is not None and parsed.utcoffset() is not None
        if require_timezone and not timezone_provided:
            issues.append(f"{field} must include timezone offset")
    return {
        "ok": not issues,
        "value": text,
        "timezoneRequired": require_timezone,
        "timezoneProvided": timezone_provided,
        "issues": issues,
    }


def _analytics_sample_window_check(record: dict) -> dict:
    issues: list[str] = []
    failed_fields: list[str] = []
    recorded_text = _analytics_text(record, "recordedAt")
    published_text = _analytics_text(record, "publishedAt")
    recorded_at = _parse_audit_datetime(recorded_text)
    published_at = _parse_audit_datetime(published_text)
    sample_window = record.get("sampleWindowHours")
    sample_window_hours = float(sample_window) if isinstance(sample_window, (int, float)) and not isinstance(sample_window, bool) else None
    recorded_aware = False
    published_aware = False

    if recorded_text and not recorded_at:
        issues.append("recordedAt must be ISO-8601 datetime evidence")
        failed_fields.append("recordedAt")
    if published_text and not published_at:
        issues.append("publishedAt must be ISO-8601 datetime evidence")
        failed_fields.append("publishedAt")
    if recorded_at:
        recorded_aware = recorded_at.tzinfo is not None and recorded_at.utcoffset() is not None
        if not recorded_aware:
            issues.append("recordedAt must include timezone offset")
            failed_fields.append("recordedAt")
    if published_at:
        published_aware = published_at.tzinfo is not None and published_at.utcoffset() is not None
        if not published_aware:
            issues.append("publishedAt must include timezone offset")
            failed_fields.append("publishedAt")
    if sample_window_hours is not None and sample_window_hours <= 0:
        issues.append("sampleWindowHours must be positive")
        failed_fields.append("sampleWindowHours")
    if recorded_at and published_at:
        if recorded_aware != published_aware:
            issues.append("recordedAt and publishedAt must both include timezone offsets")
            failed_fields.extend(["recordedAt", "publishedAt"])
        else:
            comparable_recorded = recorded_at.astimezone(timezone.utc).replace(tzinfo=None) if recorded_aware else recorded_at
            comparable_published = published_at.astimezone(timezone.utc).replace(tzinfo=None) if published_aware else published_at
            elapsed_seconds = (comparable_recorded - comparable_published).total_seconds()
            required_seconds = float(sample_window_hours or 0) * 3600
            if sample_window_hours is not None and elapsed_seconds + 60 < required_seconds:
                issues.append("recordedAt is before the declared platform sample window has elapsed")
                failed_fields.append("recordedAt")
            if elapsed_seconds < -60:
                issues.append("recordedAt cannot be before publishedAt")
                failed_fields.append("recordedAt")
    return {
        "ok": not issues,
        "recordedAt": recorded_text,
        "publishedAt": published_text,
        "sampleWindowHours": sample_window_hours,
        "timezoneRequired": True,
        "timezoneProvided": {
            "recordedAt": recorded_aware,
            "publishedAt": published_aware,
        },
        "failedFields": sorted(set(failed_fields)),
        "issues": issues,
    }


def _analytics_next_improvement_action_check(value: object) -> dict:
    text = str(value or "").strip()
    normalized = re.sub(r"\s+", " ", text).strip()
    normalized_key = normalized.lower().strip(" .!?")
    matched_terms = [term for term in _PLATFORM_ANALYTICS_ACTIONABLE_TERMS if term in normalized_key]
    issues: list[str] = []
    if normalized_key in _PLATFORM_ANALYTICS_GENERIC_ACTIONS:
        issues.append("nextImprovementAction is too generic for a platform learning loop")
    if len(normalized) < _PLATFORM_ANALYTICS_NEXT_ACTION_MIN_CHARS:
        issues.append(
            f"nextImprovementAction must be at least {_PLATFORM_ANALYTICS_NEXT_ACTION_MIN_CHARS} characters"
        )
    if not matched_terms:
        issues.append("nextImprovementAction must name a metric or creative lever to test")
    return {
        "ok": not issues,
        "value": normalized,
        "minCharacters": _PLATFORM_ANALYTICS_NEXT_ACTION_MIN_CHARS,
        "matchedTerms": matched_terms,
        "issues": issues,
    }


def _sha256_file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _analytics_snapshot_digest_check(path: Path | None, expected_value: object) -> dict:
    expected = str(expected_value or "").strip().lower()
    actual = ""
    issues: list[str] = []
    if not expected:
        issues.append("analyticsSnapshotSha256 is missing")
    elif not re.fullmatch(r"[0-9a-f]{64}", expected):
        issues.append("analyticsSnapshotSha256 must be a 64-character lowercase hex SHA-256 digest")
    if path and path.exists():
        try:
            actual = _sha256_file_digest(path)
        except OSError:
            issues.append("analytics snapshot file could not be read for SHA-256 verification")
        if expected and re.fullmatch(r"[0-9a-f]{64}", expected) and actual and actual != expected:
            issues.append("analyticsSnapshotSha256 does not match analyticsSnapshotPath bytes")
    elif expected:
        issues.append("analyticsSnapshotPath is unavailable for SHA-256 verification")
    return {
        "ok": not issues,
        "expectedSha256": expected,
        "actualSha256": actual,
        "path": str(path) if path else "",
        "issues": issues,
    }


def _analytics_number_present(record: dict, field: str, expected_duration_seconds: float | None = None) -> tuple[bool, bool]:
    if field not in record:
        return False, False
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return True, False
    if field == "sampleWindowHours":
        return True, value > 0
    if field == "views":
        return True, value > 0
    if field in _PLATFORM_ANALYTICS_RATE_FIELDS:
        return True, 0 <= value <= 1
    if field == "averageViewDurationSeconds":
        max_duration = float(expected_duration_seconds or 0) + 0.5
        return True, value > 0 and (max_duration <= 0.5 or value <= max_duration)
    return True, value >= 0


def _platform_analytics_audit(best_packet: dict | None, legacy_summary_ready: bool) -> dict:
    packet_dir_raw = str(best_packet.get("packetDir") or "").strip() if isinstance(best_packet, dict) else ""
    artifact_path = Path(packet_dir_raw) / "platform-analytics.json" if packet_dir_raw else None
    template_path = Path(packet_dir_raw) / "platform-analytics.template.json" if packet_dir_raw else None
    final_video_path = str(best_packet.get("finalVideoPath") or "").strip() if isinstance(best_packet, dict) else ""
    final_video_sha256 = _final_video_digest_value(final_video_path)
    template = {
        "recordedAt": "",
        "platform": "youtube_shorts",
        "publishUrl": "",
        "publishedAt": "",
        "metricSource": "manual platform analytics snapshot",
        "analyticsSnapshotPath": str(Path(packet_dir_raw) / "platform-analytics-snapshot.png") if packet_dir_raw else "",
        "analyticsSnapshotSha256": "",
        "evidenceRequirements": {
            "finalVideoSha256": "SHA-256 digest of the exact finalVideoPath MP4 bytes that produced this platform post.",
            "analyticsSnapshotPath": "PNG/JPEG platform analytics screenshot stored inside this final-video packet, at least 320x240 and 1024 bytes.",
            "analyticsSnapshotSha256": "SHA-256 digest of analyticsSnapshotPath bytes, captured in the same platform analytics record.",
            "sampleWindow": "recordedAt and publishedAt must be ISO-8601 timestamps with timezone offsets; recordedAt must be at least publishedAt + sampleWindowHours.",
            "nextImprovementAction": "Concrete next experiment naming a metric or creative lever, such as hook, title, caption, thumbnail, source, cut pacing, audio, retention, or swipe-away.",
        },
        "finalVideoPath": final_video_path,
        "finalVideoSha256": final_video_sha256,
        "sampleWindowHours": 0,
        "views": 0,
        "twoSecondHoldRate": 0,
        "fiveSecondHoldRate": 0,
        "averageViewDurationSeconds": 0,
        "rewatchRate": 0,
        "swipeAwayRate": 0,
        "decision": "missing",
        "nextImprovementAction": "",
        "notes": "",
    }
    base = {
        "recorded": False,
        "ready": False,
        "status": "missing",
        "artifactPath": str(artifact_path) if artifact_path else "",
        "templateArtifactPath": str(template_path) if template_path else "",
        "template": template,
        "requiredFields": _PLATFORM_ANALYTICS_REQUIRED_FIELDS,
        "missingFields": list(_PLATFORM_ANALYTICS_REQUIRED_FIELDS),
        "failedFields": [],
        "evidenceArtifactPaths": {},
        "evidenceArtifactChecks": {},
        "finalVideoDigestCheck": {},
        "snapshotDigestCheck": {},
        "sampleWindowCheck": {},
        "nextImprovementActionCheck": {},
        "decision": "",
        "legacySummaryReady": legacy_summary_ready,
        "detail": "Live platform analytics artifact is missing.",
        "operatorAction": "After upload, create platform-analytics.json with publish URL, sample window, 2s hold, 5s hold, average view duration, rewatch, swipe-away, and next-improvement notes.",
    }
    if not artifact_path:
        base["detail"] = "No best final-video packet is available for platform analytics."
        return base
    if not artifact_path.exists():
        if legacy_summary_ready:
            base["status"] = "summary-only"
            base["detail"] = "A report summary claims platform analytics are recorded, but platform-analytics.json is missing; summary-only evidence is not enough for the broad operating Goal."
        return base

    parsed = _read_json_artifact(artifact_path)
    if not isinstance(parsed, dict):
        return {
            **base,
            "recorded": True,
            "status": "fail",
            "detail": "platform-analytics.json exists but is not valid JSON object evidence.",
            "operatorAction": "Fix platform-analytics.json, then rerun the final-library audit before claiming the analytics loop is recorded.",
        }

    missing_fields: list[str] = []
    failed_fields: list[str] = []
    failed_fields.extend(_proof_template_boundary_failed_fields(parsed))
    for field in _PLATFORM_ANALYTICS_TEXT_FIELD_ALIASES:
        if not _analytics_text(parsed, field):
            missing_fields.append(field)
    analytics_final_video_path = _analytics_text(parsed, "finalVideoPath")
    if (
        analytics_final_video_path
        and final_video_path
        and not _proof_path_matches_final_video(analytics_final_video_path, final_video_path)
    ):
        failed_fields.append("finalVideoPath")
    analytics_final_video_sha256 = _analytics_text(parsed, "finalVideoSha256")
    final_video_digest_check = _final_video_digest_check(final_video_path, analytics_final_video_sha256)
    if analytics_final_video_sha256 and final_video_digest_check.get("ok") is not True:
        failed_fields.append("finalVideoSha256")
    platform = _analytics_text(parsed, "platform").lower()
    publish_url = _analytics_text(parsed, "publishUrl")
    if platform and platform not in _PLATFORM_ANALYTICS_ALLOWED_PLATFORMS:
        failed_fields.append("platform")
    if platform and publish_url:
        if not _analytics_publish_url_matches_platform(publish_url, platform):
            failed_fields.append("publishUrl")
    sample_window_check = _analytics_sample_window_check(parsed)
    for field in sample_window_check.get("failedFields") or []:
        if field not in failed_fields:
            failed_fields.append(field)
    next_improvement_action = _analytics_text(parsed, "nextImprovementAction")
    next_improvement_action_check = (
        _analytics_next_improvement_action_check(next_improvement_action) if next_improvement_action else {}
    )
    if next_improvement_action and next_improvement_action_check.get("ok") is not True:
        failed_fields.append("nextImprovementAction")
    snapshot_path = _analytics_text(parsed, "analyticsSnapshotPath")
    snapshot_sha256 = _analytics_text(parsed, "analyticsSnapshotSha256")
    packet_dir = Path(packet_dir_raw) if packet_dir_raw else None
    evidence_artifact_paths: dict[str, str] = {}
    evidence_artifact_checks: dict[str, dict] = {}
    snapshot_artifact_path = None
    if snapshot_path:
        snapshot_artifact_path = _analytics_snapshot_artifact_path(packet_dir, snapshot_path)
        if snapshot_artifact_path:
            artifact_check = _image_evidence_check(
                snapshot_artifact_path,
                min_width=320,
                min_height=240,
                min_bytes=1024,
            )
            evidence_artifact_checks["analyticsSnapshotPath"] = artifact_check
            if artifact_check.get("ok") is True:
                evidence_artifact_paths["analyticsSnapshotPath"] = str(snapshot_artifact_path)
            else:
                failed_fields.append("analyticsSnapshotPath")
        else:
            evidence_artifact_checks["analyticsSnapshotPath"] = {
                "ok": False,
                "kind": "path",
                "path": snapshot_path,
                "issues": ["artifact path is missing, outside the current final-video packet, or not a file"],
            }
            failed_fields.append("analyticsSnapshotPath")
    snapshot_digest_check = _analytics_snapshot_digest_check(snapshot_artifact_path, snapshot_sha256)
    if snapshot_sha256 and snapshot_digest_check.get("ok") is not True:
        failed_fields.append("analyticsSnapshotSha256")
    expected_duration_seconds = None
    try:
        expected_duration_seconds = float(((best_packet or {}).get("ffprobe") or {}).get("durationSeconds") or 0)
    except (TypeError, ValueError, AttributeError):
        expected_duration_seconds = None
    for field in _PLATFORM_ANALYTICS_NUMBER_FIELDS:
        present, valid = _analytics_number_present(parsed, field, expected_duration_seconds)
        if not present:
            missing_fields.append(field)
        elif not valid:
            failed_fields.append(field)

    decision = _analytics_text(parsed, "decision").lower()
    if decision in _PLATFORM_ANALYTICS_FAIL_DECISIONS and "decision" not in failed_fields:
        failed_fields.append("decision")
    ready = bool(not missing_fields and not failed_fields and decision in _PLATFORM_ANALYTICS_READY_DECISIONS)
    if ready:
        status = "recorded"
        detail = "Live platform analytics loop is recorded with retention metrics and next-improvement action."
        operator_action = "Use this analytics record to choose the next hook, title, caption, and source experiment; broad Goal still also requires fresh-source repeatability and phone review."
    elif failed_fields:
        status = "fail"
        detail = f"Platform analytics failed fields: {', '.join(failed_fields)}."
        operator_action = "Fix invalid analytics values or decision, then rerun final-library audit."
    else:
        status = "needs-analytics"
        detail = "platform-analytics.json is present but incomplete or lacks a recorded/iterate/pass decision."
        operator_action = "Complete every required metric and next-improvement action after the live platform sample window."

    return {
        **base,
        "recorded": True,
        "ready": ready,
        "status": status,
        "missingFields": missing_fields,
        "failedFields": failed_fields,
        "decision": decision,
        "evidenceArtifactPaths": evidence_artifact_paths,
        "evidenceArtifactChecks": evidence_artifact_checks,
        "finalVideoDigestCheck": final_video_digest_check,
        "snapshotDigestCheck": snapshot_digest_check,
        "sampleWindowCheck": sample_window_check,
        "nextImprovementActionCheck": next_improvement_action_check,
        "detail": detail,
        "operatorAction": operator_action,
    }


_FRESH_SOURCE_TEXT_FIELD_ALIASES = {
    "recordedAt": ("recordedAt",),
    "sourceFlow": ("sourceFlow", "flow", "sourceRail"),
    "topic": ("topic", "sourceTopic", "prompt"),
    "finalVideoPath": ("finalVideoPath", "finalMp4", "finalVideo"),
    "finalVideoSha256": ("finalVideoSha256", "finalMp4Sha256", "finalVideoDigest"),
    "handoffProjectId": ("handoffProjectId", "sourceProjectId", "grokHandoffProjectId"),
    "renderedProjectId": ("renderedProjectId", "finalProjectId", "projectId"),
    "handoffManifestPath": ("handoffManifestPath", "handoffPath", "sourceHandoffPath"),
    "sourceReviewPath": ("sourceReviewPath", "sourceReviewArtifactPath", "reviewArtifactPath"),
    "renderManifestPath": ("renderManifestPath", "manifestPath", "renderManifestArtifactPath"),
    "qualityAuditPath": ("qualityAuditPath", "qualityAuditArtifactPath"),
    "publishPacketPath": ("publishPacketPath", "publishPacketArtifactPath"),
    "dashboardSmokePath": ("dashboardSmokePath", "dashboardSmokeArtifactPath", "dashboardReadinessPath"),
    "handoffManifestSha256": ("handoffManifestSha256", "handoffManifestDigest"),
    "sourceReviewSha256": ("sourceReviewSha256", "sourceReviewDigest"),
    "renderManifestSha256": ("renderManifestSha256", "renderManifestDigest"),
    "qualityAuditSha256": ("qualityAuditSha256", "qualityAuditDigest"),
    "publishPacketSha256": ("publishPacketSha256", "publishPacketDigest"),
    "dashboardSmokeSha256": ("dashboardSmokeSha256", "dashboardSmokeDigest"),
}
_FRESH_SOURCE_TRUE_FIELD_ALIASES = {
    "differentTopic": ("differentTopic", "newTopic", "differentTopicFromBaseline"),
    "movingClipStitching": ("movingClipStitching", "stitchedMovingClips", "movingClips"),
    "sourceProvenanceReviewed": ("sourceProvenanceReviewed", "sourceProvenancePass"),
    "qualityAuditPass": ("qualityAuditPass", "qualityAuditReady"),
    "publishPacketComplete": ("publishPacketComplete", "publishPacketReady"),
    "dashboardSmokePass": ("dashboardSmokePass", "dashboardReadinessPass"),
}
_FRESH_SOURCE_NUMBER_FIELDS = ("importedSceneCount", "acceptedSceneCount")
_FRESH_SOURCE_ARTIFACT_PATH_FIELDS = {
    "handoffManifestPath",
    "sourceReviewPath",
    "renderManifestPath",
    "qualityAuditPath",
    "publishPacketPath",
    "dashboardSmokePath",
}
_FRESH_SOURCE_ARTIFACT_DIGEST_FIELDS = {
    "handoffManifestPath": "handoffManifestSha256",
    "sourceReviewPath": "sourceReviewSha256",
    "renderManifestPath": "renderManifestSha256",
    "qualityAuditPath": "qualityAuditSha256",
    "publishPacketPath": "publishPacketSha256",
    "dashboardSmokePath": "dashboardSmokeSha256",
}
_FRESH_SOURCE_SOURCE_RECOVERY_ARTIFACT_DIGEST_FIELDS = {
    "sourceRecoveryAcceptanceArtifactPath": "sourceRecoveryAcceptanceSha256",
    "sourceRecoveryRerenderPlanPath": "sourceRecoveryRerenderPlanSha256",
}
_FRESH_SOURCE_SOURCE_RECOVERY_LINK_REQUIRED_STATUSES = {
    "accepted-replacements-ready-for-rerender",
}
_FRESH_SOURCE_DASHBOARD_SMOKE_SURFACES = {
    "final-library-dashboard",
    "video-studio-final-library",
    "render-review-final-library",
}
_FRESH_SOURCE_ALLOWED_FLOW_TERMS = (
    "uploadendpoint",
    "direct import",
    "direct fetch",
    "bookmarklet",
    "operator-owned",
    "already-saved",
    "already saved",
    "manual batch upload",
    "manual chrome native mp4 import",
)
_FRESH_SOURCE_FORBIDDEN_FLOW_TERMS = (
    "grok download",
    "chrome download",
    "download prompt",
    "native browser download",
    "native download prompt",
    "downloads watcher",
    "download watcher",
    "direct mp4 asset tab",
    "download/save/export",
    "save/export",
)
_FRESH_SOURCE_REQUIRED_FIELDS = [
    *_FRESH_SOURCE_TEXT_FIELD_ALIASES.keys(),
    *_FRESH_SOURCE_NUMBER_FIELDS,
    *_FRESH_SOURCE_TRUE_FIELD_ALIASES.keys(),
]
_FRESH_SOURCE_READY_STATUS_TERMS = {"accepted", "pass", "ready", "ok", "complete", "completed", "channel-ready", "top-tier-ready"}
_FRESH_SOURCE_FAIL_STATUS_TERMS = {"fail", "failed", "reject", "rejected", "blocked", "missing", "needs-review"}


def _fresh_source_text(record: dict, field: str) -> str:
    for alias in _FRESH_SOURCE_TEXT_FIELD_ALIASES.get(field, (field,)):
        text = str(record.get(alias) or "").strip()
        if text:
            return text
    return ""


def _fresh_source_bool(record: dict, field: str) -> tuple[bool, bool]:
    for alias in _FRESH_SOURCE_TRUE_FIELD_ALIASES.get(field, (field,)):
        if alias in record:
            return True, record.get(alias) is True
    return False, False


def _fresh_source_number_present(record: dict, field: str) -> tuple[bool, bool]:
    if field not in record:
        return False, False
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return True, False
    return True, value >= 3


def _fresh_source_flow_allowed(value: str) -> bool:
    lowered = value.lower()
    if any(term in lowered for term in _FRESH_SOURCE_FORBIDDEN_FLOW_TERMS):
        return False
    return any(term in lowered for term in _FRESH_SOURCE_ALLOWED_FLOW_TERMS)


def _fresh_source_artifact_path(packet_dir: Path | None, value: object) -> Path | None:
    return _packet_artifact_path(packet_dir, value)


def _fresh_source_project_artifact_path_check(field: str, value: object) -> tuple[Path | None, dict]:
    raw = str(value or "").strip()
    issues: list[str] = []
    if not raw:
        issues.append(f"{field} is missing")
        return None, {
            "ok": False,
            "kind": "path",
            "path": "",
            "issues": issues,
        }

    candidate = _resolve_project_artifact_path(raw)
    if not candidate:
        issues.append(f"{field} could not be resolved")
        return None, {
            "ok": False,
            "kind": "path",
            "path": raw,
            "issues": issues,
        }

    try:
        resolved = candidate.resolve()
        project_root = _project_root.resolve()
    except (OSError, ValueError):
        issues.append(f"{field} could not be resolved under the project root")
        return None, {
            "ok": False,
            "kind": "path",
            "path": raw,
            "issues": issues,
        }

    try:
        under_project = resolved.is_relative_to(project_root)
    except ValueError:
        under_project = False
    if not under_project:
        issues.append(f"{field} is outside the project root")
    if not resolved.exists() or not resolved.is_file():
        issues.append(f"{field} is not an existing file")

    return (resolved if not issues else None), {
        "ok": not issues,
        "kind": "path",
        "path": str(resolved),
        "issues": issues,
    }


def _fresh_source_artifact_paths_match(left: object, right: object) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    try:
        left_path = _resolve_project_artifact_path(left_text)
        right_path = _resolve_project_artifact_path(right_text)
        if not left_path or not right_path:
            return False
        return os.path.normcase(os.path.abspath(str(left_path.resolve()))) == os.path.normcase(
            os.path.abspath(str(right_path.resolve()))
        )
    except (OSError, ValueError):
        return left_text.replace("\\", "/").casefold() == right_text.replace("\\", "/").casefold()


def _fresh_source_source_recovery_link_requirement(source_review: dict) -> dict:
    status_record = source_review.get("sourceRecoveryAcceptanceStatus")
    if isinstance(status_record, dict):
        status = str(status_record.get("status") or "").strip()
        accepted_scene_count = status_record.get("acceptedSceneCount")
        incomplete_scene_count = status_record.get("incompleteSceneCount")
        required_artifact_path = str(status_record.get("artifactPath") or status_record.get("requiredArtifactPath") or "").strip()
    else:
        status = str(status_record or source_review.get("sourceRecoveryAcceptanceStatusText") or "").strip()
        accepted_scene_count = source_review.get("sourceRecoveryAcceptedSceneCount")
        incomplete_scene_count = source_review.get("sourceRecoveryAcceptanceBlockerCount")
        required_artifact_path = str(source_review.get("sourceRecoveryAcceptanceArtifactPath") or "").strip()

    blocker_count_value = source_review.get("sourceRecoveryAcceptanceBlockerCount")
    if isinstance(blocker_count_value, (int, float)) and not isinstance(blocker_count_value, bool):
        incomplete_scene_count = blocker_count_value
    required = (
        status in _FRESH_SOURCE_SOURCE_RECOVERY_LINK_REQUIRED_STATUSES
        or source_review.get("sourceRecoveryRerenderRequired") is True
        or source_review.get("sourceRecoveryRerenderPlanRequired") is True
    )
    return {
        "required": required,
        "status": status,
        "acceptedSceneCount": accepted_scene_count if isinstance(accepted_scene_count, (int, float)) and not isinstance(accepted_scene_count, bool) else 0,
        "incompleteSceneCount": incomplete_scene_count if isinstance(incomplete_scene_count, (int, float)) and not isinstance(incomplete_scene_count, bool) else 0,
        "requiredArtifactPath": required_artifact_path,
        "reason": (
            "source review records accepted source-recovery replacements ready for rerender"
            if required
            else "source review does not require source-recovery rerender linkage"
        ),
    }


def _fresh_source_source_recovery_json_check(path: Path, field: str, proof: dict, link_requirement: dict) -> dict:
    issues: list[str] = []
    parsed = _read_json_artifact(path)
    try:
        byte_count = path.stat().st_size
    except OSError:
        byte_count = 0
        issues.append("file is unreadable")
    if not isinstance(parsed, dict):
        issues.append("expected JSON object evidence")
        parsed = {}

    if field == "sourceRecoveryAcceptanceArtifactPath":
        if parsed.get("schema") != "video-studio.source-recovery-acceptance.v1":
            issues.append("source recovery acceptance schema is not video-studio.source-recovery-acceptance.v1")
        if parsed.get("templateOnly") is True:
            issues.append("source recovery acceptance artifact is still template-only")
        scenes = parsed.get("acceptanceScenes") if isinstance(parsed.get("acceptanceScenes"), list) else []
        accepted_decisions: list[dict] = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            decision = scene.get("operatorDecision") if isinstance(scene.get("operatorDecision"), dict) else {}
            if decision.get("accepted") is True:
                accepted_decisions.append(decision)
                for required_field in (
                    "acceptedReplacementFileName",
                    "acceptedReplacementPath",
                    "acceptedReplacementSha256",
                    "reviewerId",
                    "acceptedAt",
                ):
                    if not str(decision.get(required_field) or "").strip():
                        scene_id = str(scene.get("sceneId") or "unknown").strip()
                        issues.append(f"{required_field} is missing for accepted source recovery scene {scene_id}")
        if not scenes:
            issues.append("source recovery acceptance artifact has no acceptanceScenes")
        if not accepted_decisions:
            issues.append("source recovery acceptance artifact has no accepted operator decisions")
    elif field == "sourceRecoveryRerenderPlanPath":
        if parsed.get("schema") != "video-studio.source-recovery-rerender-plan.v1":
            issues.append("source recovery rerender plan schema is not video-studio.source-recovery-rerender-plan.v1")
        if parsed.get("sourceRecoveryAcceptanceCleared") is not True:
            issues.append("source recovery rerender plan does not show acceptance cleared")
        if parsed.get("rerenderInputReady") is not True:
            issues.append("source recovery rerender plan does not show rerender input ready")
        scene_replacements = parsed.get("sceneReplacements") if isinstance(parsed.get("sceneReplacements"), list) else []
        if not scene_replacements:
            issues.append("source recovery rerender plan has no sceneReplacements")
        acceptance_path = str(parsed.get("sourceRecoveryAcceptanceArtifactPath") or "").strip()
        proof_acceptance_path = _fresh_source_text(proof, "sourceRecoveryAcceptanceArtifactPath")
        if not acceptance_path:
            issues.append("source recovery rerender plan is missing sourceRecoveryAcceptanceArtifactPath")
        elif proof_acceptance_path and not _fresh_source_artifact_paths_match(acceptance_path, proof_acceptance_path):
            issues.append("source recovery rerender plan acceptance path does not match proof sourceRecoveryAcceptanceArtifactPath")
        acceptance_sha256 = str(parsed.get("sourceRecoveryAcceptanceSha256") or "").strip().lower()
        proof_acceptance_sha256 = _fresh_source_text(proof, "sourceRecoveryAcceptanceSha256").lower()
        if not acceptance_sha256:
            issues.append("source recovery rerender plan is missing sourceRecoveryAcceptanceSha256")
        elif proof_acceptance_sha256 and acceptance_sha256 != proof_acceptance_sha256:
            issues.append("source recovery rerender plan acceptance SHA-256 does not match proof sourceRecoveryAcceptanceSha256")
        render_plan = parsed.get("renderPlan") if isinstance(parsed.get("renderPlan"), dict) else {}
        if render_plan.get("freshSourceProofRequiredAfterRerender") is not True:
            issues.append("source recovery rerender plan must require fresh-source proof after rerender")

    return {
        "ok": not issues,
        "kind": "json",
        "path": str(path),
        "bytes": byte_count,
        "sourceRecoveryLinkRequired": link_requirement.get("required") is True,
        "issues": issues,
    }


def _fresh_source_source_recovery_link_audit(proof: dict, link_requirement: dict) -> dict:
    required = link_requirement.get("required") is True
    audit = {
        "required": required,
        "requirement": link_requirement,
        "artifactPaths": {},
        "artifactChecks": {},
        "digestChecks": {},
        "missingFields": [],
        "failedFields": [],
    }
    if not required:
        return audit

    resolved_paths: dict[str, Path] = {}
    for field in _FRESH_SOURCE_SOURCE_RECOVERY_ARTIFACT_DIGEST_FIELDS:
        path_text = _fresh_source_text(proof, field)
        if not path_text:
            audit["missingFields"].append(field)
            audit["artifactChecks"][field] = {
                "ok": False,
                "kind": "path",
                "path": "",
                "issues": [f"{field} is required when source recovery replacements are ready for rerender"],
            }
            continue
        resolved_path, path_check = _fresh_source_project_artifact_path_check(field, path_text)
        if not resolved_path:
            audit["artifactChecks"][field] = path_check
            audit["failedFields"].append(field)
            continue
        resolved_paths[field] = resolved_path
        artifact_check = _fresh_source_source_recovery_json_check(resolved_path, field, proof, link_requirement)
        audit["artifactChecks"][field] = artifact_check
        if artifact_check.get("ok") is True:
            audit["artifactPaths"][field] = str(resolved_path)
        else:
            audit["failedFields"].append(field)

    for path_field, digest_field in _FRESH_SOURCE_SOURCE_RECOVERY_ARTIFACT_DIGEST_FIELDS.items():
        digest_text = _fresh_source_text(proof, digest_field)
        resolved_path = resolved_paths.get(path_field)
        digest_check = _evidence_artifact_digest_check(digest_field, path_field, resolved_path, digest_text)
        audit["digestChecks"][digest_field] = digest_check
        if not digest_text:
            audit["missingFields"].append(digest_field)
        elif digest_check.get("ok") is not True:
            audit["failedFields"].append(digest_field)
    return audit


def _dashboard_smoke_text_values(parsed: dict) -> list[str]:
    values: list[str] = []
    for field in ("visibleText", "observedText", "renderedText", "observedTexts", "visibleTexts"):
        value = parsed.get(field)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, list):
            values.extend(str(item).strip() for item in value if str(item).strip())
    return values


def _fresh_source_dashboard_smoke_issues(parsed: dict, proof_rendered_id: str) -> list[str]:
    issues: list[str] = []
    smoke_project_id = str(parsed.get("projectId") or parsed.get("renderedProjectId") or "").strip()
    smoke_surface = str(parsed.get("surface") or parsed.get("dashboardSurface") or "").strip()
    observed_texts = _dashboard_smoke_text_values(parsed)
    observed_joined = "\n".join(observed_texts)
    if parsed.get("ok") is not True:
        issues.append("dashboard smoke did not record ok=true")
    if proof_rendered_id and smoke_project_id and smoke_project_id != proof_rendered_id:
        issues.append("dashboard smoke projectId does not match proof renderedProjectId")
    if not smoke_surface or smoke_surface not in _FRESH_SOURCE_DASHBOARD_SMOKE_SURFACES:
        issues.append("dashboard smoke surface must be final-library-dashboard")
    if parsed.get("browserRendered") is not True:
        issues.append("dashboard smoke must record browserRendered=true")
    if parsed.get("bridgeConnected") is not True:
        issues.append("dashboard smoke must record bridgeConnected=true")
    if parsed.get("finalLibraryPanelVisible") is not True:
        issues.append("dashboard smoke must record finalLibraryPanelVisible=true")
    if proof_rendered_id and proof_rendered_id not in observed_joined:
        issues.append("dashboard smoke visible text must include renderedProjectId")
    if "today upload" not in observed_joined.lower():
        issues.append("dashboard smoke visible text must include today upload decision")
    return issues


def _fresh_source_project_id(record: dict, field: str) -> str:
    return _fresh_source_text(record, field)


def _fresh_source_count(record: dict, field: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _fresh_source_json_check(path: Path, field: str, proof: dict, packet_dir: Path | None, final_video_path: str, project_id: str) -> dict:
    issues: list[str] = []
    source_recovery_link_requirement: dict = {}
    parsed = _read_json_artifact(path)
    try:
        byte_count = path.stat().st_size
    except OSError:
        byte_count = 0
        issues.append("file is unreadable")
    if not isinstance(parsed, dict):
        issues.append("expected JSON object evidence")
        parsed = {}

    proof_handoff_id = _fresh_source_project_id(proof, "handoffProjectId")
    proof_rendered_id = _fresh_source_project_id(proof, "renderedProjectId") or project_id
    proof_imported_count = _fresh_source_count(proof, "importedSceneCount")
    proof_accepted_count = _fresh_source_count(proof, "acceptedSceneCount")

    if field == "handoffManifestPath":
        manifest_project_id = str(parsed.get("projectId") or parsed.get("handoffProjectId") or "").strip()
        scenes = parsed.get("scenes") if isinstance(parsed.get("scenes"), list) else parsed.get("sceneIds")
        if proof_handoff_id and manifest_project_id != proof_handoff_id:
            issues.append("handoff manifest projectId does not match proof handoffProjectId")
        if not isinstance(scenes, list) or len(scenes) < max(1, proof_imported_count):
            issues.append("handoff manifest scene count is below proof importedSceneCount")
    elif field == "sourceReviewPath":
        status = str(parsed.get("status") or parsed.get("reviewStatus") or "").strip().lower()
        accepted = parsed.get("acceptedSceneCount")
        rejected = parsed.get("rejectedSceneCount")
        accepted_count = int(accepted) if isinstance(accepted, (int, float)) and not isinstance(accepted, bool) else 0
        rejected_count = int(rejected) if isinstance(rejected, (int, float)) and not isinstance(rejected, bool) else 0
        source_recovery_link_requirement = _fresh_source_source_recovery_link_requirement(parsed)
        source_recovery_status = str(source_recovery_link_requirement.get("status") or "").strip()
        if status in _FRESH_SOURCE_FAIL_STATUS_TERMS or status not in _FRESH_SOURCE_READY_STATUS_TERMS:
            issues.append("source review status is not accepted/pass/ready")
        if accepted_count < max(1, proof_accepted_count):
            issues.append("source review acceptedSceneCount is below proof acceptedSceneCount")
        if rejected_count > 0:
            issues.append("source review still has rejected scenes")
        if parsed.get("freshSourceProofBlockedBySourceRecoveryAcceptance") is True:
            issues.append("source review is still blocked by source recovery acceptance")
        if (
            source_recovery_status
            and source_recovery_status not in {"no-source-recovery-required", *_FRESH_SOURCE_SOURCE_RECOVERY_LINK_REQUIRED_STATUSES}
        ):
            issues.append(f"source recovery acceptance status is not rerender-ready: {source_recovery_status}")
    elif field == "renderManifestPath":
        manifest_project_id = str(parsed.get("projectId") or "").strip()
        output_path = str(parsed.get("outputPath") or parsed.get("finalVideoPath") or "").strip()
        if proof_rendered_id and manifest_project_id != proof_rendered_id:
            issues.append("render manifest projectId does not match proof renderedProjectId")
        if output_path and final_video_path and not _proof_path_matches_final_video(output_path, final_video_path):
            issues.append("render manifest outputPath does not match audited final MP4")
        if not output_path:
            issues.append("render manifest outputPath is missing")
    elif field == "qualityAuditPath":
        summary = parsed.get("summary") if isinstance(parsed.get("summary"), dict) else {}
        upload = parsed.get("uploadReview") if isinstance(parsed.get("uploadReview"), dict) else {}
        channel = parsed.get("channelReadiness") if isinstance(parsed.get("channelReadiness"), dict) else {}
        publish = parsed.get("publishReadiness") if isinstance(parsed.get("publishReadiness"), dict) else {}
        if summary.get("readyForUpload") is not True and upload.get("status") != "ready":
            issues.append("quality audit does not show upload readiness")
        if summary.get("channelReady") is not True and channel.get("status") != "channel-ready":
            issues.append("quality audit does not show channel readiness")
        if summary.get("topTierEvidenceReady") is not True:
            issues.append("quality audit does not show top-tier evidence readiness")
        if publish and publish.get("status") not in {"ready", "artifact-packet-ready"}:
            issues.append("quality audit publishReadiness is not ready")
    elif field == "publishPacketPath":
        packet_root = packet_dir if packet_dir else path.parent
        final_path = Path(final_video_path) if final_video_path else None
        packet_audit = _publish_packet_content_audit(packet_root, path, final_path)
        if packet_audit.get("ready") is not True:
            missing = ", ".join(str(item) for item in (packet_audit.get("missingFields") or []))
            issues.append(f"publish packet content audit is not ready: {missing or packet_audit.get('status') or 'unknown'}")
    elif field == "dashboardSmokePath":
        issues.extend(_fresh_source_dashboard_smoke_issues(parsed, proof_rendered_id))
    result = {
        "ok": not issues,
        "kind": "json",
        "path": str(path),
        "bytes": byte_count,
        "issues": issues,
    }
    if source_recovery_link_requirement:
        result["sourceRecoveryLinkRequirement"] = source_recovery_link_requirement
    return result


def _fresh_source_repeatability_audit(best_packet: dict | None, legacy_summary_ready: bool) -> dict:
    packet_dir_raw = str(best_packet.get("packetDir") or "").strip() if isinstance(best_packet, dict) else ""
    artifact_path = Path(packet_dir_raw) / "fresh-source-proof.json" if packet_dir_raw else None
    template_path = Path(packet_dir_raw) / "fresh-source-proof.template.json" if packet_dir_raw else None
    final_video_path = str(best_packet.get("finalVideoPath") or "").strip() if isinstance(best_packet, dict) else ""
    final_video_sha256 = _final_video_digest_value(final_video_path)
    project_id = str(best_packet.get("projectId") or "").strip() if isinstance(best_packet, dict) else ""
    template = {
        "recordedAt": "",
        "sourceFlow": "operator-owned manual download/import or explicit already-saved MP4 batch upload",
        "topic": "",
        "finalVideoPath": final_video_path,
        "finalVideoSha256": final_video_sha256,
        "handoffProjectId": "",
        "renderedProjectId": project_id,
        "handoffManifestPath": "",
        "sourceReviewPath": "",
        "renderManifestPath": str(Path(packet_dir_raw) / "render-manifest.json") if packet_dir_raw else "",
        "qualityAuditPath": str(Path(packet_dir_raw) / "quality-audit.json") if packet_dir_raw else "",
        "publishPacketPath": str(Path(packet_dir_raw) / "publish-packet.json") if packet_dir_raw else "",
        "dashboardSmokePath": str(Path(packet_dir_raw) / "dashboard-smoke.json") if packet_dir_raw else "",
        "sourceRecoveryAcceptanceArtifactPath": "",
        "sourceRecoveryRerenderPlanPath": "",
        "handoffManifestSha256": "",
        "sourceReviewSha256": "",
        "renderManifestSha256": "",
        "qualityAuditSha256": "",
        "publishPacketSha256": "",
        "dashboardSmokeSha256": "",
        "sourceRecoveryAcceptanceSha256": "",
        "sourceRecoveryRerenderPlanSha256": "",
        "evidenceRequirements": {
            "recordedAt": "ISO-8601 timestamp with timezone offset for when the fresh-source proof packet was recorded.",
            "finalVideoSha256": "SHA-256 digest of the exact finalVideoPath MP4 bytes produced by the fresh-source run.",
            "handoffManifestPath": "JSON handoff manifest stored inside this final-video packet whose projectId matches handoffProjectId and whose scene count covers importedSceneCount.",
            "sourceReviewPath": "JSON source review stored inside this final-video packet with accepted/pass/ready status, acceptedSceneCount covering proof acceptedSceneCount, and no rejected scenes.",
            "renderManifestPath": "JSON render manifest stored inside this final-video packet whose projectId matches renderedProjectId and outputPath matches the audited final MP4.",
            "qualityAuditPath": "JSON quality audit stored inside this final-video packet showing upload, channel, and top-tier evidence readiness.",
            "publishPacketPath": "publish-packet.json stored inside this final-video packet that passes the publish packet content audit.",
            "dashboardSmokePath": "Browser-rendered final-library dashboard smoke JSON stored inside this final-video packet with ok=true, browserRendered=true, bridgeConnected=true, finalLibraryPanelVisible=true, rendered project text, and today upload decision text.",
            "sourceRecoveryAcceptanceArtifactPath": "Required only when sourceReviewPath records sourceRecoveryAcceptanceStatus=accepted-replacements-ready-for-rerender; points at the actual non-template source-recovery-acceptance.json with accepted replacement operator decisions.",
            "sourceRecoveryRerenderPlanPath": "Required only when source recovery replacements were accepted for rerender; points at source-recovery-rerender-plan.template.json with sourceRecoveryAcceptanceCleared=true, rerenderInputReady=true, and sceneReplacements.",
            "handoffManifestSha256": "SHA-256 digest of handoffManifestPath bytes captured for this fresh-source proof.",
            "sourceReviewSha256": "SHA-256 digest of sourceReviewPath bytes captured for this fresh-source proof.",
            "renderManifestSha256": "SHA-256 digest of renderManifestPath bytes captured for this fresh-source proof.",
            "qualityAuditSha256": "SHA-256 digest of qualityAuditPath bytes captured for this fresh-source proof.",
            "publishPacketSha256": "SHA-256 digest of publishPacketPath bytes captured for this fresh-source proof.",
            "dashboardSmokeSha256": "SHA-256 digest of dashboardSmokePath bytes captured for this fresh-source proof.",
            "sourceRecoveryAcceptanceSha256": "Required only when source recovery replacements were accepted for rerender; SHA-256 digest of sourceRecoveryAcceptanceArtifactPath bytes.",
            "sourceRecoveryRerenderPlanSha256": "Required only when source recovery replacements were accepted for rerender; SHA-256 digest of sourceRecoveryRerenderPlanPath bytes.",
        },
        "importedSceneCount": 0,
        "acceptedSceneCount": 0,
        "differentTopic": False,
        "movingClipStitching": False,
        "sourceProvenanceReviewed": False,
        "qualityAuditPass": False,
        "publishPacketComplete": False,
        "dashboardSmokePass": False,
        "notes": "",
    }
    base = {
        "recorded": False,
        "ready": False,
        "status": "missing",
        "artifactPath": str(artifact_path) if artifact_path else "",
        "templateArtifactPath": str(template_path) if template_path else "",
        "template": template,
        "requiredFields": _FRESH_SOURCE_REQUIRED_FIELDS,
        "missingFields": list(_FRESH_SOURCE_REQUIRED_FIELDS),
        "failedFields": [],
        "evidenceArtifactPaths": {},
        "evidenceArtifactChecks": {},
        "evidenceDigestChecks": {},
        "finalVideoDigestCheck": {},
        "recordedAtCheck": {},
        "legacySummaryReady": legacy_summary_ready,
        "detail": "Fresh-source repeatability proof artifact is missing.",
        "operatorAction": "Create fresh-source-proof.json only after a different-topic Grok/manual Chrome MP4 source run is imported, accepted, rendered, finalized, audited, and dashboard-smoked.",
    }
    if not artifact_path:
        base["detail"] = "No best final-video packet is available for fresh-source repeatability proof."
        return base
    if not artifact_path.exists():
        if legacy_summary_ready:
            base["status"] = "summary-only"
            base["detail"] = "A report summary claims fresh-source proof, but fresh-source-proof.json is missing; summary-only evidence is not enough for repeatable live-channel operation."
        return base

    parsed = _read_json_artifact(artifact_path)
    if not isinstance(parsed, dict):
        return {
            **base,
            "recorded": True,
            "status": "fail",
            "detail": "fresh-source-proof.json exists but is not valid JSON object evidence.",
            "operatorAction": "Fix fresh-source-proof.json, then rerun the final-library audit before any pre-upload decision.",
        }

    missing_fields: list[str] = []
    failed_fields: list[str] = []
    failed_fields.extend(_proof_template_boundary_failed_fields(parsed))
    for field in _FRESH_SOURCE_TEXT_FIELD_ALIASES:
        if not _fresh_source_text(parsed, field):
            missing_fields.append(field)
    recorded_at = _fresh_source_text(parsed, "recordedAt")
    recorded_at_check = _audit_timestamp_check("recordedAt", recorded_at) if recorded_at else {}
    if recorded_at and recorded_at_check.get("ok") is not True:
        failed_fields.append("recordedAt")
    source_flow = _fresh_source_text(parsed, "sourceFlow")
    if source_flow and not _fresh_source_flow_allowed(source_flow):
        failed_fields.append("sourceFlow")
    proof_final_video_path = _fresh_source_text(parsed, "finalVideoPath")
    if (
        proof_final_video_path
        and final_video_path
        and not _proof_path_matches_final_video(proof_final_video_path, final_video_path)
    ):
        failed_fields.append("finalVideoPath")
    proof_final_video_sha256 = _fresh_source_text(parsed, "finalVideoSha256")
    final_video_digest_check = _final_video_digest_check(final_video_path, proof_final_video_sha256)
    if proof_final_video_sha256 and final_video_digest_check.get("ok") is not True:
        failed_fields.append("finalVideoSha256")
    packet_dir = Path(packet_dir_raw) if packet_dir_raw else None
    evidence_artifact_paths: dict[str, str] = {}
    evidence_artifact_checks: dict[str, dict] = {}
    evidence_artifact_resolved_paths: dict[str, Path] = {}
    for field in _FRESH_SOURCE_ARTIFACT_PATH_FIELDS:
        path_text = _fresh_source_text(parsed, field)
        if path_text:
            artifact_path_value = _fresh_source_artifact_path(packet_dir, path_text)
            if artifact_path_value:
                evidence_artifact_resolved_paths[field] = artifact_path_value
                artifact_check = _fresh_source_json_check(
                    artifact_path_value,
                    field,
                    parsed,
                    packet_dir,
                    final_video_path,
                    project_id,
                )
                evidence_artifact_checks[field] = artifact_check
                if artifact_check.get("ok") is True:
                    evidence_artifact_paths[field] = str(artifact_path_value)
                else:
                    failed_fields.append(field)
            else:
                evidence_artifact_checks[field] = {
                    "ok": False,
                    "kind": "path",
                    "path": path_text,
                    "issues": ["artifact path is missing, outside the current final-video packet, or not a file"],
                }
                failed_fields.append(field)
    evidence_digest_checks: dict[str, dict] = {}
    for path_field, digest_field in _FRESH_SOURCE_ARTIFACT_DIGEST_FIELDS.items():
        digest_text = _fresh_source_text(parsed, digest_field)
        resolved_path = evidence_artifact_resolved_paths.get(path_field)
        if digest_text or resolved_path:
            digest_check = _evidence_artifact_digest_check(digest_field, path_field, resolved_path, digest_text)
            evidence_digest_checks[digest_field] = digest_check
            if digest_text and digest_check.get("ok") is not True:
                failed_fields.append(digest_field)
    source_recovery_link_requirement = {}
    source_review_check = evidence_artifact_checks.get("sourceReviewPath")
    if isinstance(source_review_check, dict):
        source_recovery_link_requirement = (
            source_review_check.get("sourceRecoveryLinkRequirement")
            if isinstance(source_review_check.get("sourceRecoveryLinkRequirement"), dict)
            else {}
        )
    source_recovery_link_audit = _fresh_source_source_recovery_link_audit(parsed, source_recovery_link_requirement)
    evidence_artifact_paths.update(source_recovery_link_audit.get("artifactPaths") or {})
    evidence_artifact_checks.update(source_recovery_link_audit.get("artifactChecks") or {})
    evidence_digest_checks.update(source_recovery_link_audit.get("digestChecks") or {})
    for field in source_recovery_link_audit.get("missingFields") or []:
        if field not in missing_fields:
            missing_fields.append(field)
    for field in source_recovery_link_audit.get("failedFields") or []:
        if field not in failed_fields:
            failed_fields.append(field)
    for field in _FRESH_SOURCE_NUMBER_FIELDS:
        present, valid = _fresh_source_number_present(parsed, field)
        if not present:
            missing_fields.append(field)
        elif not valid:
            failed_fields.append(field)
    imported_count = parsed.get("importedSceneCount")
    accepted_count = parsed.get("acceptedSceneCount")
    if (
        isinstance(imported_count, (int, float))
        and not isinstance(imported_count, bool)
        and isinstance(accepted_count, (int, float))
        and not isinstance(accepted_count, bool)
        and accepted_count > imported_count
        and "acceptedSceneCount" not in failed_fields
    ):
        failed_fields.append("acceptedSceneCount")
    for field in _FRESH_SOURCE_TRUE_FIELD_ALIASES:
        present, passed = _fresh_source_bool(parsed, field)
        if not present:
            missing_fields.append(field)
        elif not passed:
            failed_fields.append(field)

    ready = not missing_fields and not failed_fields
    if ready:
        status = "pass"
        detail = "Fresh-source repeatability proof is bound to this final MP4 and includes source intake, review, render, packet, audit, and dashboard evidence."
        operator_action = "Proceed to phone-sized human review for same-day upload readiness; platform analytics remain post-upload proof."
    elif failed_fields:
        status = "fail"
        detail = f"Fresh-source repeatability proof failed fields: {', '.join(failed_fields)}."
        operator_action = "Fix stale, mismatched, or insufficient fresh-source proof before treating this packet as repeatable live-channel output."
    else:
        status = "needs-proof"
        detail = f"Fresh-source repeatability proof is missing required fields: {', '.join(missing_fields)}."
        operator_action = "Complete fresh-source-proof.json after the fresh source run is imported, accepted, rendered, finalized, audited, and dashboard-smoked."

    return {
        **base,
        "recorded": True,
        "ready": ready,
        "status": status,
        "missingFields": missing_fields,
        "failedFields": failed_fields,
        "sourceFlow": _fresh_source_text(parsed, "sourceFlow"),
        "topic": _fresh_source_text(parsed, "topic"),
        "handoffProjectId": _fresh_source_text(parsed, "handoffProjectId"),
        "renderedProjectId": _fresh_source_text(parsed, "renderedProjectId"),
        "evidenceArtifactPaths": evidence_artifact_paths,
        "evidenceArtifactChecks": evidence_artifact_checks,
        "evidenceDigestChecks": evidence_digest_checks,
        "sourceRecoveryLinkRequired": source_recovery_link_audit.get("required") is True,
        "sourceRecoveryLinkRequirement": source_recovery_link_requirement,
        "finalVideoDigestCheck": final_video_digest_check,
        "recordedAtCheck": recorded_at_check,
        "detail": detail,
        "operatorAction": operator_action,
    }


_GROK_DIRECT_IMPORT_SOURCE_KINDS = {
    "companion-direct-fetch",
    "visible-video-blob-direct-fetch",
    "bookmarklet-direct-video-fetch",
    "bookmarklet-blob-direct-fetch",
    "bookmarklet-post-direct-video-fetch",
    "bookmarklet-post-blob-direct-fetch",
    "codex-chrome-page-assets-direct-fetch",
}
_GROK_DIRECT_IMPORT_EVENT_TYPES = {
    "companion-direct-import",
    "companion-blob-direct-import",
    "bookmarklet-direct-import",
    "bookmarklet-post-direct-import",
    "codex-chrome-page-assets-direct-import",
}
_GROK_DIRECT_IMPORT_SUCCESS_STATUSES = {"imported"}
_GROK_HANDOFF_ID_KEYS = {
    "grokHandoffProjectId",
    "grokHandoffProjectIds",
    "grokHandoffId",
    "grokHandoffIds",
    "handoffProjectId",
    "handoffProjectIds",
    "sourceHandoffProjectId",
    "sourceHandoffProjectIds",
}
_GROK_SCENE_ID_KEYS = {"sceneId", "scene_id"}
_GROK_FILE_NAME_KEYS = {
    "expectedFileName",
    "fileName",
    "selectedFileName",
    "uploadedFileName",
}


def _iter_mapping_values(value: object):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _iter_mapping_values(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_mapping_values(item)


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _values_for_keys(source: object, keys: set[str]) -> set[str]:
    values: set[str] = set()
    for item in _iter_mapping_values(source):
        for key in keys:
            if key in item:
                values.update(_as_string_list(item.get(key)))
    return values


def _basename(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("browser-upload:"):
        text = text.split(":", 1)[1]
    text = text.replace("\\", "/").split("?", 1)[0].split("#", 1)[0]
    return Path(text).name.strip()


def _file_name_values_for_keys(source: object, keys: set[str]) -> set[str]:
    names = {_basename(value) for value in _values_for_keys(source, keys)}
    return {name for name in names if name}


def _grok_direct_import_empty_proof() -> dict:
    return {
        "proven": False,
        "sourceKind": "",
        "eventType": "",
        "importMode": "",
        "qualityNote": "",
    }


def _read_jsonl_dicts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                events.append(parsed)
    except (OSError, json.JSONDecodeError):
        return []
    return events


def _source_path_exists(source_path: object, handoff_dir: Path) -> bool:
    text = str(source_path or "").strip()
    if not text:
        return False
    candidate = Path(text)
    candidates = [candidate] if candidate.is_absolute() else [_project_root / candidate, handoff_dir / candidate]
    return any(path.exists() for path in candidates)


def _is_direct_import_event(event: dict) -> bool:
    source_kind = str(event.get("sourceKind") or "").strip()
    event_type = str(event.get("eventType") or "").strip()
    status = str(event.get("status") or "").strip()
    quality_note = str(event.get("qualityNote") or event.get("detail") or "").strip()
    avoids_download_prompt = "no-browser-download-prompt" in quality_note
    companion_direct = source_kind == "companion-direct-fetch"
    return bool(
        source_kind in _GROK_DIRECT_IMPORT_SOURCE_KINDS
        and event_type in _GROK_DIRECT_IMPORT_EVENT_TYPES
        and status in _GROK_DIRECT_IMPORT_SUCCESS_STATUSES
        and (avoids_download_prompt or companion_direct)
    )


def _matching_handoff_import(
    manifest: dict,
    handoff_dir: Path,
    event: dict,
    relevant_scene_ids: set[str],
    relevant_file_names: set[str],
) -> tuple[dict, dict] | tuple[None, None]:
    event_scene_id = str(event.get("sceneId") or "").strip()
    event_file_names = {
        _basename(event.get("expectedFileName")),
        _basename(event.get("fileName")),
        _basename(event.get("uploadedFileName")),
    }
    event_file_names = {name for name in event_file_names if name}
    if relevant_scene_ids and event_scene_id and event_scene_id not in relevant_scene_ids:
        return None, None

    for history in reversed(manifest.get("importHistory") or []):
        if not isinstance(history, dict):
            continue
        import_mode = str(history.get("importMode") or "").strip()
        for imported in reversed(history.get("imported") or []):
            if not isinstance(imported, dict):
                continue
            imported_scene_id = str(imported.get("sceneId") or history.get("sceneId") or "").strip()
            if event_scene_id and imported_scene_id and imported_scene_id != event_scene_id:
                continue
            imported_names = {
                _basename(imported.get("expectedFileName")),
                _basename(imported.get("fileName")),
                _basename(history.get("uploadedFileName")),
                _basename(imported.get("originalPath")),
            }
            imported_names = {name for name in imported_names if name}
            if event_file_names and not (event_file_names & imported_names):
                continue
            if relevant_file_names and not (relevant_file_names & imported_names) and not (
                relevant_scene_ids and imported_scene_id in relevant_scene_ids
            ):
                continue
            if imported.get("sourcePath") and not _source_path_exists(imported.get("sourcePath"), handoff_dir):
                continue
            if not import_mode:
                import_mode = str(imported.get("importMode") or "").strip()
            return history, imported
    return None, None


def _grok_handoff_direct_import_proof(report: dict, best_summary: dict) -> dict:
    proof_scope = [report, best_summary]
    relevant_scene_ids = _values_for_keys(proof_scope, _GROK_SCENE_ID_KEYS)
    relevant_file_names = _file_name_values_for_keys(proof_scope, _GROK_FILE_NAME_KEYS)
    handoff_project_ids = _values_for_keys(proof_scope, _GROK_HANDOFF_ID_KEYS)
    grok_handoff_recorded = bool(
        handoff_project_ids
        or relevant_scene_ids
        or any(
            str(item.get("grokHandoffScenes") or "").strip()
            for source in proof_scope
            for item in _iter_mapping_values(source)
            if isinstance(item, dict)
        )
    )
    if not grok_handoff_recorded:
        return _grok_direct_import_empty_proof()

    handoff_root = _project_root / "storage" / "grok-handoffs"
    if not handoff_root.exists():
        return _grok_direct_import_empty_proof()
    if handoff_project_ids:
        handoff_dirs = [handoff_root / project_id for project_id in sorted(handoff_project_ids)]
    else:
        handoff_dirs = sorted(
            [path for path in handoff_root.iterdir() if path.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    for handoff_dir in handoff_dirs:
        if not handoff_dir.exists():
            continue
        manifest = _read_json_artifact(handoff_dir / "handoff.json") or {}
        events = _read_jsonl_dicts(handoff_dir / "extension-events.jsonl")
        for event in reversed(events):
            if not _is_direct_import_event(event):
                continue
            history, imported = _matching_handoff_import(
                manifest,
                handoff_dir,
                event,
                relevant_scene_ids,
                relevant_file_names,
            )
            if not history or not imported:
                continue
            source_kind = str(event.get("sourceKind") or "").strip()
            event_type = str(event.get("eventType") or "").strip()
            quality_note = str(event.get("qualityNote") or event.get("detail") or "").strip()
            import_mode = str(history.get("importMode") or imported.get("importMode") or "").strip()
            return {
                "proven": True,
                "sourceKind": source_kind,
                "eventType": event_type,
                "importMode": import_mode,
                "qualityNote": quality_note,
                "handoffProjectId": str(manifest.get("projectId") or handoff_dir.name),
                "sceneId": str(event.get("sceneId") or imported.get("sceneId") or ""),
                "expectedFileName": _basename(event.get("expectedFileName")) or _basename(imported.get("expectedFileName")),
                "sceneImported": True,
                "sceneQueueAdvanced": True,
                "queueEvidence": "uploadEndpoint importHistory",
                "eventUpdatedAt": str(event.get("updatedAt") or ""),
                "importedAt": str(history.get("importedAt") or ""),
            }
    return _grok_direct_import_empty_proof()


def _grok_direct_import_proof(report: dict, best_summary: dict) -> dict:
    """Find explicit signed-in browser direct-import evidence without accepting local/unverified files."""
    proof_sources = [report, best_summary]
    for source in proof_sources:
        for item in _iter_mapping_values(source):
            source_kind = str(item.get("sourceKind") or "").strip()
            event_type = str(item.get("eventType") or "").strip()
            quality_note = str(item.get("qualityNote") or item.get("detail") or "").strip()
            import_mode = str(item.get("importMode") or "").strip()
            is_direct_source = source_kind in _GROK_DIRECT_IMPORT_SOURCE_KINDS
            is_direct_event = event_type in _GROK_DIRECT_IMPORT_EVENT_TYPES
            avoids_download_prompt = "no-browser-download-prompt" in quality_note
            if is_direct_source and (is_direct_event or avoids_download_prompt or source_kind == "companion-direct-fetch"):
                return {
                    "proven": True,
                    "sourceKind": source_kind,
                    "eventType": event_type,
                    "importMode": import_mode,
                    "qualityNote": quality_note,
                }
    return _grok_handoff_direct_import_proof(report, best_summary)


def _goal_readiness_audit(
    packets: list[dict],
    best_packet: dict | None,
    best_report: dict,
    source_pipeline_status: dict | None = None,
) -> dict:
    best_summary = best_packet.get("summary") if isinstance(best_packet, dict) else {}
    checks = best_report.get("checks") if isinstance(best_report.get("checks"), dict) else {}
    production = best_report.get("productionReview") if isinstance(best_report.get("productionReview"), dict) else {}
    production_summary = production.get("summary") if isinstance(production.get("summary"), dict) else {}
    top_tier = best_report.get("topTierReadiness") if isinstance(best_report.get("topTierReadiness"), dict) else {}
    top_tier_summary = top_tier.get("summary") if isinstance(top_tier.get("summary"), dict) else {}
    upload_review = best_report.get("uploadReview") if isinstance(best_report.get("uploadReview"), dict) else {}
    stock_curation = _stock_candidate_curation_summary(best_report)
    if not stock_curation.get("recorded") and isinstance(best_summary, dict):
        stock_curation = _stock_candidate_curation_summary({"summary": best_summary})
    stock_curation_blocks = stock_curation.get("ready") is False

    source_pipeline_status = source_pipeline_status or {}
    grok_status = source_pipeline_status.get("grok") if isinstance(source_pipeline_status.get("grok"), dict) else {}
    bookmarklet_status = grok_status.get("bookmarkletDirectImport") if isinstance(grok_status.get("bookmarkletDirectImport"), dict) else {}
    latest_handoff = grok_status.get("latestHandoff") if isinstance(grok_status.get("latestHandoff"), dict) else {}
    proof_monitor_url = str(grok_status.get("proofMonitorUrl") or "").strip()
    observed_post_url = str(grok_status.get("observedPostUrl") or "").strip()
    direct_import_proof = _grok_direct_import_proof(best_report, best_summary)

    artifact_ready = bool(best_summary.get("topTierReady"))
    top_tier_packet_count = sum(1 for item in packets if (item.get("summary") or {}).get("topTierReady"))
    browser_handoff_surface_ready = bool(
        grok_status.get("nextAction")
        or latest_handoff
        or proof_monitor_url
        or observed_post_url
    )
    bookmarklet_operator_ready = bookmarklet_status.get("operatorReady") is True
    live_grok_direct_import_proven = bool(
        production_summary.get("liveSignedInGrokDirectImportProof") is True
        or top_tier_summary.get("liveSignedInGrokDirectImportProof") is True
        or best_summary.get("liveSignedInGrokDirectImportProof") is True
        or direct_import_proof.get("proven") is True
    )
    caption_safe = (checks.get("captionSafePresets") or {}).get("status") == "pass"
    source_motion = (checks.get("sourceMotionEvidence") or {}).get("status") == "pass"
    zero_paid = (checks.get("zeroPaidProviders") or {}).get("status") == "pass"
    upload_ready = upload_review.get("status") == "ready" or best_summary.get("uploadReady") is True
    top_tier_ready = top_tier.get("status") == "top-tier-ready" or best_summary.get("topTierReady") is True
    top_tier_missing = [] if top_tier_ready and source_motion else ["Complete top-tier readiness and source-motion proof on the best packet."]
    if stock_curation_blocks:
        missing_stock_scenes = stock_curation.get("missingScenes") or []
        top_tier_missing.append(
            "Complete Pexels stock candidate curation proof"
            + (f" for scenes: {', '.join(missing_stock_scenes)}." if missing_stock_scenes else ".")
        )

    requirements = [
        _goal_requirement(
            "A-quality-cause-remediation",
            "A) quality cause remediation",
            "pass" if browser_handoff_surface_ready and zero_paid else "partial",
            "Final library audit exposes no-paid policy, browser-control Grok handoff, Pexels support role, and local adapter readiness.",
            [] if browser_handoff_surface_ready and zero_paid else ["Re-run quality diagnosis after provider policy or source rail changes."],
        ),
        _goal_requirement(
            "B-dashboard-production-flow",
            "B) real dashboard production flow",
            "pass" if browser_handoff_surface_ready and live_grok_direct_import_proven else "partial" if browser_handoff_surface_ready else "missing",
            "Scene upload/Pexels/Grok/local source rails exist and audit reports browser-control plus operator-owned local MP4 import as the primary Grok handoff.",
            []
            if (browser_handoff_surface_ready or bookmarklet_operator_ready) and live_grok_direct_import_proven
            else [
                item
                for item in [
                    None
                    if browser_handoff_surface_ready or bookmarklet_operator_ready
                    else "Use browser-control against the existing signed-in Chrome/Grok tab, then have the operator import the local MP4 through Downloads import or explicit batch upload.",
                    None
                    if live_grok_direct_import_proven
                    else "Capture live signed-in Chrome/Grok generation proof plus local MP4 import/review advancement.",
                ]
                if item
            ],
        ),
        _goal_requirement(
            "C-caption-layout-quality",
            "C) caption and layout quality",
            "pass" if caption_safe else "partial",
            "Best packet quality report includes caption safe preset checks.",
            [] if caption_safe else ["Regenerate or review caption preset evidence against RENDERING-SPEC safe zones."],
        ),
        _goal_requirement(
            "D-top-tier-ai-assisted-standard",
            "D) top-tier AI-assisted standard",
            "pass" if top_tier_ready and source_motion and not stock_curation_blocks else "partial",
            f"topTierReadiness={top_tier.get('status') or best_summary.get('topTierStatus') or 'unknown'}; sourceMotionEvidence={(checks.get('sourceMotionEvidence') or {}).get('status') or 'unknown'}; stockCandidateCuration={stock_curation.get('status') or 'unknown'}.",
            top_tier_missing,
        ),
        _goal_requirement(
            "E-real-test-mp4",
            "E) real test MP4 and publish gates",
            "pass" if artifact_ready and upload_ready else "partial",
            f"bestPacket={best_packet.get('projectId') if isinstance(best_packet, dict) else 'none'}; topTierReady={best_summary.get('topTierReady')}; uploadReady={best_summary.get('uploadReady')}.",
            [] if artifact_ready and upload_ready else ["Produce or finalize a 1080x1920/30fps/audio MP4 with upload/channel/top-tier gates."],
        ),
    ]
    remaining_gaps: list[str] = []
    for item in requirements:
        remaining_gaps.extend(item.get("missing") or [])
    if not packets:
        remaining_gaps.append("No final-video packets were found.")
    if artifact_ready and not live_grok_direct_import_proven:
        remaining_gaps.append("Artifact-level top-tier proof exists, but the current live signed-in Grok Import MP4 handoff is still unproven.")

    artifact_gate_complete = bool(
        artifact_ready
        and upload_ready
        and zero_paid
        and caption_safe
        and top_tier_ready
        and source_motion
        and not stock_curation_blocks
        and live_grok_direct_import_proven
        and not remaining_gaps
    )
    artifact_remaining_gaps = list(remaining_gaps)

    legacy_fresh_source_ready = bool(
        production_summary.get("freshGrokBatchProof") is True
        or production_summary.get("freshManualChromeSourceFlowProof") is True
        or top_tier_summary.get("freshGrokBatchProof") is True
        or best_summary.get("freshGrokBatchProof") is True
    )
    fresh_source_repeatability = _fresh_source_repeatability_audit(best_packet, legacy_fresh_source_ready)
    fresh_source_batch_proven = fresh_source_repeatability.get("ready") is True
    legacy_phone_review_ready = bool(
        production_summary.get("phoneSizedHumanReviewReady") is True
        or top_tier_summary.get("phoneSizedHumanReviewReady") is True
        or best_summary.get("phoneSizedHumanReviewReady") is True
    )
    phone_sized_human_review = _phone_sized_human_review_audit(best_packet, legacy_phone_review_ready)
    phone_review_proven = phone_sized_human_review.get("ready") is True
    legacy_platform_analytics_ready = bool(
        production_summary.get("platformAnalyticsRecorded") is True
        or top_tier_summary.get("platformAnalyticsRecorded") is True
        or best_summary.get("platformAnalyticsRecorded") is True
    )
    platform_analytics = _platform_analytics_audit(best_packet, legacy_platform_analytics_ready)
    platform_analytics_proven = platform_analytics.get("ready") is True
    multi_topic_repeatability_ready = bool(top_tier_packet_count >= 2 and fresh_source_batch_proven)
    operating_system_requirements = [
        _goal_requirement(
            "F-fresh-source-repeatability",
            "F) fresh source repeatability",
            "pass" if multi_topic_repeatability_ready else "partial" if top_tier_packet_count >= 2 else "missing",
            f"topTierPacketCount={top_tier_packet_count}; freshSourceBatchProven={fresh_source_batch_proven}; status={fresh_source_repeatability.get('status')}; artifact={fresh_source_repeatability.get('artifactPath') or 'missing'}.",
            []
            if multi_topic_repeatability_ready
            else [
                str(fresh_source_repeatability.get("operatorAction") or "Run a fresh Grok batch or current manual Chrome source-flow on a different topic and carry it through render, audit, publish packet, and dashboard smoke."),
            ],
        ),
        _goal_requirement(
            "G-phone-sized-human-review",
            "G) phone-sized human pre-upload review",
            "pass" if phone_review_proven else "missing",
            f"phoneSizedHumanReviewReady={phone_review_proven}; status={phone_sized_human_review.get('status')}; artifact={phone_sized_human_review.get('artifactPath') or 'missing'}.",
            [] if phone_review_proven else [str(phone_sized_human_review.get("operatorAction") or "Record a phone-sized human watch with headphones before treating any candidate as live-upload approved.")],
        ),
        _goal_requirement(
            "H-platform-analytics-loop",
            "H) live platform analytics loop",
            "pass" if platform_analytics_proven else "missing",
            f"platformAnalyticsRecorded={platform_analytics_proven}; status={platform_analytics.get('status')}; artifact={platform_analytics.get('artifactPath') or 'missing'}.",
            [] if platform_analytics_proven else [str(platform_analytics.get("operatorAction") or "Record platform analytics after upload: 2s hold, 5s hold, AVD, rewatch, and swipe-away.")],
        ),
    ]
    operating_system_remaining_gaps: list[str] = []
    for item in operating_system_requirements:
        operating_system_remaining_gaps.extend(item.get("missing") or [])

    goal_complete = bool(
        artifact_gate_complete
        and multi_topic_repeatability_ready
        and phone_review_proven
        and platform_analytics_proven
        and not operating_system_remaining_gaps
    )
    all_remaining_gaps = list(dict.fromkeys([*artifact_remaining_gaps, *operating_system_remaining_gaps]))
    overall_status = "complete" if goal_complete else "artifact-gate-ready" if artifact_gate_complete else "incomplete"
    operator_decision = _live_channel_operator_decision(
        goal_complete,
        artifact_gate_complete,
        artifact_ready,
        upload_ready,
        top_tier_ready,
        source_motion,
        all_remaining_gaps,
    )
    pre_upload_decision = _pre_upload_operator_decision(
        artifact_gate_complete,
        artifact_ready,
        upload_ready,
        top_tier_ready,
        source_motion,
        fresh_source_batch_proven,
        fresh_source_repeatability,
        phone_review_proven,
        phone_sized_human_review,
        artifact_remaining_gaps,
    )
    pre_upload_ready = pre_upload_decision.get("status") == "upload"
    runway_checklist = _goal_runway_checklist(
        artifact_gate_complete=artifact_gate_complete,
        artifact_ready=artifact_ready,
        upload_ready=upload_ready,
        top_tier_ready=top_tier_ready,
        source_motion=source_motion,
        fresh_source_batch_proven=fresh_source_batch_proven,
        fresh_source_repeatability=fresh_source_repeatability,
        latest_handoff=latest_handoff,
        source_recovery_plan=source_pipeline_status.get("sourceRecoveryPlan") if isinstance(source_pipeline_status.get("sourceRecoveryPlan"), dict) else {},
        source_recovery_acceptance=source_pipeline_status.get("sourceRecoveryAcceptance") if isinstance(source_pipeline_status.get("sourceRecoveryAcceptance"), dict) else {},
        phone_review_proven=phone_review_proven,
        phone_sized_human_review=phone_sized_human_review,
        pre_upload_ready=pre_upload_ready,
        pre_upload_decision=pre_upload_decision,
        platform_analytics_proven=platform_analytics_proven,
        platform_analytics=platform_analytics,
        goal_complete=goal_complete,
    )
    result = {
        "goalComplete": goal_complete,
        "overallStatus": overall_status,
        "operatorDecision": operator_decision,
        "preUploadDecision": pre_upload_decision,
        "preUploadReady": pre_upload_ready,
        "preUploadBoundary": "Same-day upload readiness requires artifact gate, fresh-source proof, and phone-sized human review. It does not satisfy the post-upload analytics loop or the broad operating-system Goal.",
        "operatingRunwayChecklist": runway_checklist["items"],
        "runwayChecklistSummary": runway_checklist["summary"],
        "artifactGateComplete": artifact_gate_complete,
        "artifactGateStatus": "ready" if artifact_gate_complete else "incomplete",
        "artifactRemainingGaps": artifact_remaining_gaps,
        "operatingSystemComplete": goal_complete,
        "operatingSystemRequirements": operating_system_requirements,
        "operatingSystemRemainingGaps": operating_system_remaining_gaps,
        "artifactReady": artifact_ready,
        "topTierPacketCount": top_tier_packet_count,
        "freshSourceBatchProven": fresh_source_batch_proven,
        "freshSourceRepeatability": fresh_source_repeatability,
        "phoneSizedHumanReviewReady": phone_review_proven,
        "phoneSizedHumanReview": phone_sized_human_review,
        "platformAnalyticsRecorded": platform_analytics_proven,
        "platformAnalytics": platform_analytics,
        "liveGrokDirectImportProven": live_grok_direct_import_proven,
        "liveGrokDirectImportProof": direct_import_proof,
        "proofMonitorUrl": proof_monitor_url,
        "observedPostUrl": observed_post_url,
        "requirements": requirements,
        "remainingGaps": all_remaining_gaps,
        "completionPolicy": "Do not close the broad Video Studio operating-system Goal from artifact readiness, final-library audit pass, or Grok direct-import proof alone. Artifact gates only prove a candidate packet; broad completion also requires fresh-source repeatability, phone-sized human review, and live platform analytics.",
    }
    result["gateSystem"] = build_final_readiness_gate_system(result)
    return result


def _sanitize_grok_observed_post_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.match(r"^https?://(?:[^/]+\.)?grok\.com/imagine/post/[A-Za-z0-9_-]+", raw)
    return match.group(0) if match else ""


def _grok_handoff_selection_record(handoff_path: Path) -> dict:
    project_id = handoff_path.parent.name
    modified_at = 0.0
    try:
        modified_at = handoff_path.stat().st_mtime
    except OSError:
        pass
    record = {
        "projectId": project_id,
        "path": str(handoff_path),
        "modifiedAtEpoch": modified_at,
        "productionScore": 0,
        "productionReasons": [],
        "sceneCount": 0,
        "promptReadyScenes": 0,
        "promptNeedsRewriteScenes": 0,
    }
    try:
        manifest = json.loads(handoff_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        record["productionReasons"].append("manifest-unreadable")
        record["productionScore"] = -500
        return record

    manifest_project_id = str(manifest.get("projectId") or project_id)
    scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
    scene_count = len([item for item in scenes if isinstance(item, dict)])
    source_mix_total = int(manifest.get("sourceMixTotalScenes") or scene_count or 0)
    prompt_ready = 0
    prompt_needs_rewrite = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        prompt_quality = scene.get("promptQuality") if isinstance(scene.get("promptQuality"), dict) else {}
        status = str(prompt_quality.get("status") or "").strip()
        if status == "ready":
            prompt_ready += 1
        elif status == "needs-rewrite":
            prompt_needs_rewrite += 1

    score = 0
    reasons: list[str] = []
    if manifest_project_id.startswith("live-channel-") or project_id.startswith("live-channel-"):
        score += 600
        reasons.append("live-channel-project")
    if manifest.get("qualityGateRequired") is True:
        score += 250
        reasons.append("quality-gate-required")
    if manifest.get("grokMainSourceRequired") is True:
        score += 250
        reasons.append("grok-main-source-required")
    if source_mix_total >= 2:
        score += min(source_mix_total, 10) * 20
        reasons.append("multi-scene-source-mix")
    if scene_count and prompt_ready == scene_count:
        score += 120
        reasons.append("all-prompts-ready")
    if prompt_needs_rewrite:
        score -= 300
        reasons.append("prompt-needs-rewrite")
    if scene_count <= 1 and not manifest.get("qualityGateRequired"):
        score -= 80
        reasons.append("single-scene-non-quality-gated")

    record.update({
        "projectId": manifest_project_id or project_id,
        "productionScore": score,
        "productionReasons": reasons,
        "sceneCount": scene_count,
        "sourceMixTotalScenes": source_mix_total,
        "qualityGateRequired": manifest.get("qualityGateRequired") is True,
        "grokMainSourceRequired": manifest.get("grokMainSourceRequired") is True,
        "promptReadyScenes": prompt_ready,
        "promptNeedsRewriteScenes": prompt_needs_rewrite,
    })
    return record


def _latest_grok_handoff_context() -> dict:
    default_project_id = "grok-main-reset-routine-20260526-01"
    default_scene_id = "scene-01"
    context = {
        "projectId": default_project_id,
        "sceneId": default_scene_id,
        "observedPostUrl": "",
    }
    handoff_root = _project_root / "storage" / "grok-handoffs"
    if not handoff_root.exists():
        return context

    candidates: list[dict] = []
    for child in handoff_root.iterdir():
        handoff_path = child / "handoff.json"
        if child.is_dir() and handoff_path.exists():
            candidates.append(_grok_handoff_selection_record(handoff_path))
    if not candidates:
        return context

    latest_by_mtime = sorted(candidates, key=lambda item: float(item.get("modifiedAtEpoch") or 0), reverse=True)[0]
    selected = sorted(
        candidates,
        key=lambda item: (
            int(item.get("productionScore") or 0),
            float(item.get("modifiedAtEpoch") or 0),
        ),
        reverse=True,
    )[0]
    handoff_path = Path(str(selected.get("path") or ""))
    project_id = handoff_path.parent.name or default_project_id
    scene_id = default_scene_id
    observed_post_url = ""
    try:
        manifest = json.loads(handoff_path.read_text(encoding="utf-8"))
        scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
        for scene in scenes:
            if isinstance(scene, dict) and str(scene.get("sceneId") or "").strip():
                scene_id = str(scene.get("sceneId") or "").strip()
                break

        observation_candidates: list[dict] = []
        for key in ("latestCodexChromeObservation", "codexChromeObservation", "latestGenerationObservation", "generationObservation"):
            value = manifest.get(key)
            if isinstance(value, dict):
                observation_candidates.append(value)
        for key in ("codexChromeObservations", "generationObservations"):
            value = manifest.get(key)
            if isinstance(value, list):
                observation_candidates.extend(item for item in reversed(value) if isinstance(item, dict))
        for item in observation_candidates:
            observed_post_url = _sanitize_grok_observed_post_url(item.get("postUrl") or item.get("currentUrl"))
            if observed_post_url:
                break
    except Exception:
        logger.debug("Could not read Grok handoff manifest for proof monitor URL", exc_info=True)
    context.update({
        "projectId": project_id,
        "sceneId": scene_id,
        "observedPostUrl": observed_post_url,
        "handoffSelection": {
            "selectedProjectId": project_id,
            "selectedScore": selected.get("productionScore") or 0,
            "selectedReasons": selected.get("productionReasons") or [],
            "latestByMtimeProjectId": latest_by_mtime.get("projectId") or "",
            "latestByMtimeScore": latest_by_mtime.get("productionScore") or 0,
            "preferredProductionHandoff": str(latest_by_mtime.get("path") or "") != str(selected.get("path") or ""),
            "nonSelectedLatestReason": (
                f"{latest_by_mtime.get('projectId') or 'unknown'} was newer by mtime but scored lower for live-channel production readiness."
                if str(latest_by_mtime.get("path") or "") != str(selected.get("path") or "")
                else ""
            ),
            "candidates": [
                {
                    "projectId": item.get("projectId") or "",
                    "productionScore": item.get("productionScore") or 0,
                    "sceneCount": item.get("sceneCount") or 0,
                    "qualityGateRequired": item.get("qualityGateRequired") is True,
                    "grokMainSourceRequired": item.get("grokMainSourceRequired") is True,
                    "promptNeedsRewriteScenes": item.get("promptNeedsRewriteScenes") or 0,
                }
                for item in sorted(
                    candidates,
                    key=lambda entry: (
                        int(entry.get("productionScore") or 0),
                        float(entry.get("modifiedAtEpoch") or 0),
                    ),
                    reverse=True,
                )[:8]
            ],
        },
    })
    return context


def _parse_local_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _file_mtime_datetime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _compact_ffprobe(ffprobe: dict) -> dict:
    return {key: value for key, value in ffprobe.items() if key != "raw"}


def _grok_handoff_scene_import_preflight(source_path: Path, created_at: datetime | None) -> dict:
    exists = source_path.exists()
    modified_at = _file_mtime_datetime(source_path) if exists else None
    fresh_enough = bool(exists and (created_at is None or (modified_at is not None and modified_at >= created_at)))
    size_bytes = 0
    if exists:
        try:
            size_bytes = source_path.stat().st_size
        except OSError:
            size_bytes = 0
    ffprobe = _run_final_video_ffprobe(source_path) if exists and size_bytes > 0 else {
        "ok": False,
        "error": "source MP4 missing",
        "specReady": False,
    }
    duration = ffprobe.get("durationSeconds")
    usable_video_ready = bool(
        ffprobe.get("ok")
        and ffprobe.get("width")
        and ffprobe.get("height")
        and isinstance(duration, (int, float))
        and duration > 0
    )
    if not exists:
        status = "missing"
        detail = "Expected Grok MP4 is missing from the handoff incoming directory."
    elif not fresh_enough:
        status = "stale"
        detail = "Imported MP4 predates the handoff and cannot prove fresh-source repeatability."
    elif not usable_video_ready:
        status = "invalid-video"
        detail = ffprobe.get("error") or "ffprobe did not confirm a usable video stream."
    else:
        status = "ready"
        detail = "Fresh imported MP4 has a usable video stream for scene review."
    return {
        "sourcePath": str(source_path),
        "exists": exists,
        "sizeBytes": size_bytes,
        "modifiedAt": modified_at.isoformat(timespec="seconds") if modified_at else "",
        "freshEnough": fresh_enough,
        "usableVideoReady": usable_video_ready,
        "readyForReview": status == "ready",
        "status": status,
        "detail": detail,
        "ffprobe": _compact_ffprobe(ffprobe),
    }


def _grok_handoff_import_preflight_summary(scene_summaries: list[dict]) -> dict:
    missing = [item.get("sceneId") for item in scene_summaries if (item.get("importPreflight") or {}).get("status") == "missing"]
    stale = [item.get("sceneId") for item in scene_summaries if (item.get("importPreflight") or {}).get("status") == "stale"]
    invalid = [item.get("sceneId") for item in scene_summaries if (item.get("importPreflight") or {}).get("status") == "invalid-video"]
    ready = [item.get("sceneId") for item in scene_summaries if (item.get("importPreflight") or {}).get("status") == "ready"]
    needs_import = [
        item.get("sceneId")
        for item in scene_summaries
        if (item.get("importPreflight") or {}).get("status") != "ready"
    ]
    present = [
        item.get("sceneId")
        for item in scene_summaries
        if (item.get("importPreflight") or {}).get("exists") is True
    ]
    ready_for_review = bool(scene_summaries) and len(ready) == len(scene_summaries)
    return {
        "totalScenes": len(scene_summaries),
        "presentScenes": len(present),
        "readyScenes": len(ready),
        "missingScenes": [scene_id for scene_id in missing if scene_id],
        "staleScenes": [scene_id for scene_id in stale if scene_id],
        "invalidScenes": [scene_id for scene_id in invalid if scene_id],
        "needsImportScenes": [scene_id for scene_id in needs_import if scene_id],
        "nextSceneId": next((scene_id for scene_id in needs_import if scene_id), ""),
        "readyForReview": ready_for_review,
        "operatorAction": (
            "Review and accept every ready imported MP4 before rendering."
            if ready_for_review
            else "Import fresh native Grok MP4s and fix any stale or ffprobe-invalid scenes before review acceptance."
        ),
    }


def _grok_handoff_browser_generation_summary(handoff_dir: Path, scene_summaries: list[dict]) -> dict:
    proof_path = handoff_dir / "browser-generation-proof.json"
    scene_ids = [str(item.get("sceneId") or "") for item in scene_summaries if str(item.get("sceneId") or "")]
    base = {
        "artifactPath": str(proof_path),
        "exists": proof_path.exists(),
        "status": "missing",
        "generatedScenes": 0,
        "generatedSceneIds": [],
        "missingSceneIds": scene_ids,
        "scenes": {},
        "readyForImport": False,
        "proofOnly": True,
        "doesNotSatisfyFreshSourceProof": True,
        "operatorAction": (
            "Generate Grok browser posts, then have the operator save/download the MP4 and import the local file "
            "through Downloads import or explicit batch upload. Do not use Grok Download/Save/Export or any "
            "Chrome native download prompt from Codex automation."
        ),
    }
    if not proof_path.exists():
        return base

    payload = _read_json_artifact(proof_path)
    if not isinstance(payload, dict):
        return {
            **base,
            "status": "invalid",
            "detail": "browser-generation-proof.json exists but is not valid JSON object evidence.",
            "operatorAction": "Fix browser-generation-proof.json, then rerun the final-library audit.",
        }

    generated_by_scene: dict[str, dict] = {}
    raw_scenes = payload.get("generatedScenes") if isinstance(payload.get("generatedScenes"), list) else []
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        scene_id = str(item.get("sceneId") or "").strip()
        if not scene_id:
            continue
        video = item.get("video") if isinstance(item.get("video"), dict) else {}
        duration = video.get("durationSeconds")
        width = video.get("width")
        height = video.get("height")
        dimensions_ready = bool(
            isinstance(duration, (int, float))
            and duration > 0
            and isinstance(width, int)
            and width > 0
            and isinstance(height, int)
            and height > 0
        )
        post_url = _sanitize_grok_observed_post_url(item.get("postUrl") or item.get("shareUrl"))
        generated_by_scene[scene_id] = {
            "sceneId": scene_id,
            "generated": bool(post_url and dimensions_ready),
            "postUrl": post_url,
            "shareUrl": _sanitize_grok_observed_post_url(item.get("shareUrl")),
            "observedAt": str(item.get("observedAt") or ""),
            "expectedFileName": str(item.get("expectedFileName") or ""),
            "video": {
                "width": width if isinstance(width, int) else None,
                "height": height if isinstance(height, int) else None,
                "durationSeconds": duration if isinstance(duration, (int, float)) else None,
                "sourceHost": str(video.get("sourceHost") or ""),
            },
            "downloadStatus": str(item.get("downloadStatus") or payload.get("downloadStatus") or ""),
            "importedNativeMp4": item.get("importedNativeMp4") is True,
        }

    generated_scene_ids = [
        scene_id
        for scene_id in scene_ids
        if (generated_by_scene.get(scene_id) or {}).get("generated") is True
    ]
    missing_scene_ids = [scene_id for scene_id in scene_ids if scene_id not in generated_scene_ids]
    if generated_scene_ids and missing_scene_ids:
        status = "partial-generated-not-imported"
    elif generated_scene_ids:
        status = "generated-not-imported"
    else:
        status = "present-without-valid-generated-scenes"

    return {
        **base,
        "status": status,
        "createdAt": str(payload.get("createdAt") or ""),
        "sourceFlow": str(payload.get("sourceFlow") or "existing signed-in Chrome/Grok Imagine web"),
        "generatedScenes": len(generated_scene_ids),
        "generatedSceneIds": generated_scene_ids,
        "missingSceneIds": missing_scene_ids,
        "scenes": generated_by_scene,
        "readyForImport": bool(generated_scene_ids),
        "downloadStatus": str(payload.get("downloadStatus") or ""),
        "downloadAttempts": payload.get("downloadAttempts") if isinstance(payload.get("downloadAttempts"), list) else [],
        "proofOnly": True,
        "doesNotSatisfyFreshSourceProof": True,
        "detail": (
            f"Grok browser generation observed for {len(generated_scene_ids)}/{len(scene_ids)} scenes, "
            "but this is not native MP4 import or review acceptance proof."
        ),
        "operatorAction": (
            "Use the generated Grok post pages as provenance, then import operator-owned local MP4 files into the "
            "handoff incoming folder through Downloads import or explicit batch upload before review acceptance, render, or upload decisions. "
            "Codex automation must not press Grok Download/Save/Export or any Chrome native download prompt."
        ),
    }


def _grok_handoff_review_failure_categories(decision: dict) -> list[str]:
    """Classify live-channel source-review failures for operator triage."""
    if not decision:
        return ["review-not-recorded"]
    if decision.get("accepted") is True:
        return []

    text = " ".join(
        str(decision.get(key) or "")
        for key in (
            "qualityReviewNote",
            "captionLayoutReviewNote",
            "operatorNote",
            "hookNote",
            "selectedCandidateSummary",
            "visualQualityVerdict",
        )
    ).lower()
    categories: list[str] = []
    if decision.get("firstTwoSecondHook") is False or "hook" in text or "first-frame" in text or "first two" in text:
        categories.append("weak-first-2s-hook")
    if "first-frame" in text or "thumbnail" in text:
        categories.append("weak-thumbnail-or-first-frame")
    if decision.get("artifactFree") is False or any(
        token in text for token in ("ai", "stock", "artifact", "anatomy", "face", "body", "morph", "generated")
    ):
        categories.append("ai-slop-or-stock-mismatch")
    if decision.get("captionSafe") is False or "caption" in text or "safe" in text:
        categories.append("caption-safe-zone-risk")
    if decision.get("continuityOk") is False or decision.get("shotLockMatch") is False or "continuity" in text:
        categories.append("shot-continuity-mismatch")
    if decision.get("sceneAssemblyOk") is False:
        categories.append("scene-assembly-risk")
    if decision.get("sourceProvenanceConfirmed") is False:
        categories.append("source-provenance-missing")

    deduped: list[str] = []
    for category in categories:
        if category not in deduped:
            deduped.append(category)
    return deduped or ["upload-grade-review-failed"]


def _grok_handoff_review_payload(scene_id: str, decision: dict) -> dict:
    accepted = decision.get("accepted") is True
    fail_categories = _grok_handoff_review_failure_categories(decision)
    if not decision:
        status = "pending-review"
    elif accepted:
        status = "accepted"
    else:
        status = "rejected"
    return {
        "status": status,
        "accepted": accepted,
        "visualQualityVerdict": str(decision.get("visualQualityVerdict") or ""),
        "failCategories": fail_categories,
        "qualityReviewNote": str(decision.get("qualityReviewNote") or ""),
        "captionLayoutReviewNote": str(decision.get("captionLayoutReviewNote") or ""),
        "operatorNote": str(decision.get("operatorNote") or ""),
        "sourceRationale": str(decision.get("sourceRationale") or ""),
        "selectedCandidateSummary": str(decision.get("selectedCandidateSummary") or ""),
        "selectedFileName": str(decision.get("selectedFileName") or ""),
        "retryAttempt": int(decision.get("retryAttempt") or 0),
        "nextRetryPrompt": str(decision.get("nextRetryPrompt") or ""),
        "sourceProvenanceConfirmed": decision.get("sourceProvenanceConfirmed") is True,
        "sourceProvenanceStatus": str(decision.get("sourceProvenanceStatus") or ""),
        "firstTwoSecondHook": decision.get("firstTwoSecondHook") is True,
        "artifactFree": decision.get("artifactFree") is True,
        "captionSafe": decision.get("captionSafe") is True,
        "continuityOk": decision.get("continuityOk") is True,
        "shotLockMatch": decision.get("shotLockMatch") is True,
        "sceneAssemblyOk": decision.get("sceneAssemblyOk") is True,
        "liveFailSummary": (
            f"{scene_id}: {', '.join(fail_categories)}"
            if fail_categories
            else f"{scene_id}: accepted source review"
        ),
    }


def _grok_handoff_scene_candidate_pool(
    incoming_dir: Path,
    scene_id: str,
    expected_file: str,
    created_at: datetime | None,
    review: dict,
) -> dict:
    candidates: list[dict] = []
    seen: set[str] = set()
    selected_file = str(review.get("selectedFileName") or expected_file or "").strip()
    for candidate in sorted(incoming_dir.glob(f"{scene_id}*.mp4"), key=lambda item: item.name.lower()):
        if not candidate.is_file() or candidate.name in seen:
            continue
        seen.add(candidate.name)
        preflight = _grok_handoff_scene_import_preflight(candidate, created_at)
        selected_in_review = candidate.name == selected_file
        if selected_in_review:
            review_status = "accepted" if review.get("accepted") is True else "rejected"
        else:
            review_status = "unreviewed"
        candidates.append({
            "fileName": candidate.name,
            "sourcePath": str(candidate),
            "expectedFile": candidate.name == expected_file,
            "selectedInReview": selected_in_review,
            "reviewStatus": review_status,
            "readyForReview": preflight.get("readyForReview") is True,
            "modifiedAt": preflight.get("modifiedAt") or "",
            "sizeBytes": preflight.get("sizeBytes") or 0,
            "importPreflight": preflight,
        })

    ready_candidates = [item for item in candidates if item.get("readyForReview") is True]
    unreviewed_replacements = [
        item
        for item in candidates
        if item.get("selectedInReview") is not True
    ]
    return {
        "totalCandidates": len(candidates),
        "readyCandidates": len(ready_candidates),
        "unreviewedReplacementCandidates": [item.get("fileName") for item in unreviewed_replacements],
        "unreviewedReplacementCount": len(unreviewed_replacements),
        "selectedFileName": selected_file,
        "candidates": candidates,
        "operatorAction": (
            "Review existing local replacement candidates before generating more Grok clips."
            if unreviewed_replacements
            else "No unreviewed local replacement candidate is ready; acquire a new clean moving MP4 if this scene is rejected."
        ),
    }


def _grok_handoff_replacement_action(scene_id: str, review: dict, candidate_pool: dict | None = None) -> str:
    candidate_pool = candidate_pool or {}
    unreviewed = candidate_pool.get("unreviewedReplacementCandidates") or []
    if unreviewed:
        names = ", ".join(str(item) for item in unreviewed[:3])
        return (
            f"Review existing local replacement candidate(s) for {scene_id}: {names}. "
            "If one passes first-2s hook, AI-slop/source-fit, caption-safe, and scene-assembly review, "
            "record that review before render. If none pass, regenerate and import only through operator-owned "
            "manual download/import or explicit batch upload from an already-saved local MP4."
        )
    if review.get("nextRetryPrompt"):
        return (
            f"Regenerate {scene_id} from the stored retry prompt, import only through operator-owned manual "
            "download/import or explicit batch upload from an already-saved local MP4, then rerun first-2s hook, "
            "AI-slop/source-fit, caption-safe, and scene-assembly review."
        )
    return (
        f"Acquire a clean moving MP4 replacement for {scene_id} without Codex pressing Grok Download/Save/Export or any Chrome native download prompt, "
        "then record review acceptance before any render."
    )


def _latest_grok_handoff_operator_decision(
    status: str,
    total_scenes: int,
    imported_count: int,
    accepted_count: int,
    missing_scene_ids: list[str],
    download_freshness: dict,
    import_preflight: dict | None = None,
    browser_generation_proof: dict | None = None,
    replacement_backlog: list[dict] | None = None,
) -> dict:
    if total_scenes == 0:
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": "The latest Grok handoff has no scene rows, so it cannot support repeatable source production.",
            "nextAction": "Regenerate the Grok handoff with scene rows and motion-first prompts before source acquisition.",
        }
    if missing_scene_ids:
        generated_count = int((browser_generation_proof or {}).get("generatedScenes") or 0)
        if generated_count > 0:
            return {
                "status": "edit",
                "label": "수정 필요",
                "detail": (
                    f"Grok browser generation is observed for {generated_count}/{total_scenes} scenes, "
                    "but native MP4 imports are still missing; browser post proof alone cannot support render or upload."
                ),
                "nextAction": (
                    "Use operator-owned manual download/import or explicit batch upload from already saved MP4s for the generated posts; "
                    "do not press Grok Download/Save/Export or any Chrome native download prompt from Codex automation. "
                    "Then import each native MP4, run preflight, and review/accept every scene."
                ),
            }
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": "Fresh Grok MP4 imports are missing for this handoff; old Downloads MP4s are excluded from fresh-source proof.",
            "nextAction": "Generate or import the missing native Grok MP4 clips, then review and accept each scene before rendering.",
        }
    if import_preflight and import_preflight.get("readyForReview") is not True:
        stale = import_preflight.get("staleScenes") or []
        invalid = import_preflight.get("invalidScenes") or []
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": f"Imported Grok MP4s exist, but source import preflight is failing. stale={stale}, invalid={invalid}",
            "nextAction": "Replace stale or ffprobe-invalid imported MP4s before accepting scenes or rendering.",
        }
    if imported_count == total_scenes and accepted_count < total_scenes:
        rejected = replacement_backlog or []
        if rejected:
            scene_ids = [str(item.get("sceneId") or "") for item in rejected[:3] if item.get("sceneId")]
            categories = sorted({
                str(category)
                for item in rejected
                for category in (item.get("failCategories") or [])
                if category
            })
            detail = (
                f"Fresh Grok MP4s are imported, but upload-grade review rejected {len(rejected)} scene(s): "
                f"{', '.join(scene_ids)}. Fail categories: {', '.join(categories[:6])}."
            )
        else:
            detail = "Fresh Grok MP4s are imported, but review acceptance is incomplete."
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": detail,
            "nextAction": (
                "Replace rejected scenes with clean moving clips, then rerun review acceptance before render. "
                "Do not treat imported-but-rejected Grok MP4s as upload-ready source."
            ),
        }
    if status == "accepted" and imported_count == total_scenes and accepted_count == total_scenes:
        return {
            "status": "rerender",
            "label": "재렌더 필요",
            "detail": "Fresh source is accepted, but a channel-ready final MP4 and publish packet still need a fresh render/finalize pass.",
            "nextAction": "Render this handoff, finalize the publish packet, then run ffprobe, quality audit, dashboard, and phone-sized review.",
        }
    if int(download_freshness.get("freshCandidateCount") or 0) > 0:
        return {
            "status": "edit",
            "label": "수정 필요",
            "detail": "Fresh Grok downloads exist, but they are not yet imported into the handoff.",
            "nextAction": "Import the fresh MP4 downloads into this handoff, then review at least two takes before accepting each scene.",
        }
    return {
        "status": "edit",
        "label": "수정 필요",
        "detail": "The latest Grok handoff is not ready for render or upload.",
        "nextAction": "Finish fresh-source import, review acceptance, render, and publish-packet checks before upload decisions.",
    }


def _latest_grok_handoff_summary(context: dict | None = None) -> dict:
    context = context or _latest_grok_handoff_context()
    project_id = str(context.get("projectId") or "").strip()
    handoff_dir = _project_root / "storage" / "grok-handoffs" / project_id
    manifest_path = handoff_dir / "handoff.json"
    if not project_id or not manifest_path.exists():
        return {
            "available": False,
            "projectId": project_id,
            "status": "missing",
            "operatorAction": "Create a Grok handoff packet before claiming fresh-source repeatability.",
        }

    manifest = _read_json_artifact(manifest_path) or {}
    scenes = [scene for scene in manifest.get("scenes") or [] if isinstance(scene, dict)]
    incoming_dir = Path(str(manifest.get("incomingDir") or handoff_dir / "incoming"))
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    created_at = _parse_local_datetime(manifest.get("createdAt"))
    scene_summaries: list[dict] = []
    missing_scene_ids: list[str] = []
    imported_scene_ids: list[str] = []
    accepted_scene_ids: list[str] = []
    rejected_scene_ids: list[str] = []
    replacement_backlog: list[dict] = []
    for index, scene in enumerate(scenes):
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}").strip()
        expected_file = Path(str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")).name
        source_path = incoming_dir / expected_file
        imported = source_path.exists()
        decision = review_decisions.get(scene_id) if isinstance(review_decisions.get(scene_id), dict) else {}
        accepted = decision.get("accepted") is True
        review = _grok_handoff_review_payload(scene_id, decision)
        candidate_pool = _grok_handoff_scene_candidate_pool(incoming_dir, scene_id, expected_file, created_at, review)
        if imported:
            imported_scene_ids.append(scene_id)
        else:
            missing_scene_ids.append(scene_id)
        if accepted:
            accepted_scene_ids.append(scene_id)
        elif imported and decision:
            rejected_scene_ids.append(scene_id)
        import_preflight = _grok_handoff_scene_import_preflight(source_path, created_at)
        if imported and decision and not accepted:
            replacement_backlog.append({
                "sceneId": scene_id,
                "expectedFileName": expected_file,
                "selectedFileName": review.get("selectedFileName") or expected_file,
                "status": review.get("status"),
                "failCategories": review.get("failCategories") or [],
                "liveFailSummary": review.get("liveFailSummary") or "",
                "qualityReviewNote": review.get("qualityReviewNote") or "",
                "operatorNote": review.get("operatorNote") or "",
                "retryAttempt": review.get("retryAttempt") or 0,
                "nextRetryPrompt": review.get("nextRetryPrompt") or "",
                "localCandidateCount": candidate_pool.get("totalCandidates") or 0,
                "readyLocalCandidateCount": candidate_pool.get("readyCandidates") or 0,
                "unreviewedLocalCandidateCount": candidate_pool.get("unreviewedReplacementCount") or 0,
                "unreviewedLocalCandidates": candidate_pool.get("unreviewedReplacementCandidates") or [],
                "candidatePool": candidate_pool,
                "operatorAction": _grok_handoff_replacement_action(scene_id, review, candidate_pool),
            })
        scene_summaries.append({
            "sceneId": scene_id,
            "expectedFileName": expected_file,
            "imported": imported,
            "accepted": accepted,
            "promptQualityStatus": ((scene.get("promptQuality") or {}).get("status") if isinstance(scene.get("promptQuality"), dict) else ""),
            "importPreflight": import_preflight,
            "review": review,
            "candidatePool": candidate_pool,
        })

    import_preflight_summary = _grok_handoff_import_preflight_summary(scene_summaries)
    browser_generation_proof = _grok_handoff_browser_generation_summary(handoff_dir, scene_summaries)
    browser_generation_scenes = browser_generation_proof.get("scenes") if isinstance(browser_generation_proof.get("scenes"), dict) else {}
    for item in scene_summaries:
        scene_id = str(item.get("sceneId") or "")
        item["browserGeneration"] = browser_generation_scenes.get(scene_id) or {
            "sceneId": scene_id,
            "generated": False,
        }
    download_dir = Path(str(manifest.get("defaultDownloadDir") or ""))
    download_freshness = {
        "downloadDir": str(download_dir) if str(download_dir) else "",
        "freshCandidateCount": 0,
        "excludedOldCandidateCount": 0,
        "newestFreshCandidateAt": "",
        "newestExcludedOldCandidateAt": "",
        "freshnessPolicy": "Only MP4s modified after this handoff can support fresh-source repeatability.",
    }
    if download_dir.exists():
        fresh_times: list[datetime] = []
        old_times: list[datetime] = []
        for candidate in sorted(download_dir.glob("*.mp4")):
            name = candidate.name.lower()
            if not (name.startswith("grok-video-") or name.startswith("scene-")):
                continue
            modified_at = _file_mtime_datetime(candidate)
            if modified_at is None:
                continue
            if created_at and modified_at < created_at:
                old_times.append(modified_at)
            else:
                fresh_times.append(modified_at)
        download_freshness.update({
            "freshCandidateCount": len(fresh_times),
            "excludedOldCandidateCount": len(old_times),
            "newestFreshCandidateAt": max(fresh_times).isoformat(timespec="seconds") if fresh_times else "",
            "newestExcludedOldCandidateAt": max(old_times).isoformat(timespec="seconds") if old_times else "",
        })

    total_scenes = len(scene_summaries)
    imported_count = len(imported_scene_ids)
    accepted_count = len(accepted_scene_ids)
    rejected_count = len(rejected_scene_ids)
    if total_scenes == 0:
        status = "missing-scenes"
        operator_action = "Regenerate the Grok handoff with scene rows before source acquisition."
    elif imported_count == total_scenes and import_preflight_summary.get("readyForReview") is not True:
        status = "import-preflight-failed"
        operator_action = "Replace stale or ffprobe-invalid imported Grok MP4s before scene acceptance or render."
    elif imported_count == total_scenes and accepted_count == total_scenes:
        status = "accepted"
        operator_action = "Render this fresh-source handoff, finalize the publish packet, then run ffprobe/audit/dashboard and phone-sized review."
    elif imported_count == total_scenes:
        status = "needs-review"
        operator_action = "Open the review packet and accept or reject every imported Grok scene before rendering."
    elif download_freshness["freshCandidateCount"]:
        status = "fresh-downloads-waiting-import"
        operator_action = "Import the fresh MP4 downloads into this handoff, then review at least two takes before accepting each Grok-main scene."
    elif int(browser_generation_proof.get("generatedScenes") or 0) > 0:
        status = "browser-generated-waiting-import"
        operator_action = (
            "Grok browser posts were generated, but native MP4 files are not in the handoff incoming folder. "
            "Use operator-owned manual download/import or explicit batch upload from an already-saved local MP4; "
            "do not press Grok Download/Save/Export or any Chrome native download prompt from Codex automation. Then run import preflight and review acceptance."
        )
    else:
        status = "waiting-for-fresh-imports"
        operator_action = "Generate or import fresh native Grok MP4s for the missing scenes. Older Downloads MP4s are excluded from fresh-source proof."

    return {
        "available": True,
        "projectId": project_id,
        "createdAt": str(manifest.get("createdAt") or ""),
        "status": status,
        "operatorDecision": _latest_grok_handoff_operator_decision(
            status,
            total_scenes,
            imported_count,
            accepted_count,
            missing_scene_ids,
            download_freshness,
            import_preflight_summary,
            browser_generation_proof,
            replacement_backlog,
        ),
        "blocksOperatingGoal": status != "accepted",
        "totalScenes": total_scenes,
        "importedScenes": imported_count,
        "acceptedScenes": accepted_count,
        "rejectedScenes": rejected_count,
        "missingScenes": missing_scene_ids,
        "importedSceneIds": imported_scene_ids,
        "acceptedSceneIds": accepted_scene_ids,
        "rejectedSceneIds": rejected_scene_ids,
        "replacementBacklog": replacement_backlog,
        "liveFailCategories": sorted({
            str(category)
            for item in replacement_backlog
            for category in (item.get("failCategories") or [])
            if category
        }),
        "nextMissingSceneId": missing_scene_ids[0] if missing_scene_ids else "",
        "scenes": scene_summaries,
        "importPreflight": import_preflight_summary,
        "importPreflightSummary": import_preflight_summary,
        "browserGenerationProof": browser_generation_proof,
        "downloadFreshness": download_freshness,
        "worksheetUrl": manifest.get("worksheetUrl") or f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{quote(project_id, safe='')}/worksheet",
        "productionQueueUrl": manifest.get("productionQueueUrl") or f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{quote(project_id, safe='')}/production-queue",
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{quote(project_id, safe='')}/review-packet",
        "freshSourceIntakeTemplatePath": str(handoff_dir / "fresh-source-intake.template.json"),
        "freshSourceIntakeUrl": f"http://{_bridge_host}:{_bridge_port}/api/final-video-library/fresh-source-intake",
        "statusUrl": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{quote(project_id, safe='')}/status",
        "operatorAction": operator_action,
    }


def _latest_grok_handoff_project_and_scene() -> tuple[str, str]:
    context = _latest_grok_handoff_context()
    return str(context.get("projectId") or "grok-main-reset-routine-20260526-01"), str(context.get("sceneId") or "scene-01")


def _resolve_project_artifact_path(value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = _project_root / candidate
    return candidate


def _latest_pexels_replacement_research_summary(project_id: str) -> dict:
    project_id = str(project_id or "").strip()
    qa_dir = _project_root / "storage" / "qa" / project_id / "free-pexels-replacement-research"
    if not project_id or not qa_dir.exists():
        return {
            "available": False,
            "projectId": project_id,
            "status": "missing",
            "operatorAction": "No free Pexels direct-URL replacement research is recorded for the latest fresh-source handoff.",
        }

    review_paths = sorted(
        qa_dir.glob("replacement-review-*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    review_path = review_paths[0] if review_paths else None
    review = _read_json_artifact(review_path) if review_path else {}
    selected_downloads = _read_json_artifact(qa_dir / "selected-pexels-downloads.json") or {}
    selected_by_scene = {
        str(item.get("sceneId") or ""): item
        for item in (selected_downloads.get("selected") or [])
        if isinstance(item, dict) and str(item.get("sceneId") or "").strip()
    }

    raw_candidates = review.get("candidates") if isinstance(review.get("candidates"), list) else []
    candidates: list[dict] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        scene_id = str(raw.get("sceneId") or "").strip()
        selected = selected_by_scene.get(scene_id) or {}
        local_path = raw.get("localPath") or selected.get("localPath")
        contact_sheet_path = raw.get("contactSheetPath")
        reframe_smoke_path = raw.get("reframeSmokePath")
        reframe_smoke_review_path = raw.get("reframeSmokeReviewPath")
        resolved_local = _resolve_project_artifact_path(local_path)
        resolved_contact_sheet = _resolve_project_artifact_path(contact_sheet_path)
        resolved_reframe_smoke = _resolve_project_artifact_path(reframe_smoke_path)
        resolved_reframe_smoke_review = _resolve_project_artifact_path(reframe_smoke_review_path)
        candidates.append({
            "sceneId": scene_id,
            "provider": str(raw.get("provider") or "pexels-video"),
            "sourceOrigin": str(raw.get("sourceOrigin") or "selected-stock"),
            "candidateFileName": str(raw.get("candidateFileName") or selected.get("fileName") or ""),
            "pexelsId": str(raw.get("pexelsId") or selected.get("id") or ""),
            "creator": str(raw.get("creator") or selected.get("author") or ""),
            "sourcePageUrl": str(raw.get("sourcePageUrl") or selected.get("sourceUrl") or ""),
            "downloadUrl": str(raw.get("downloadUrl") or selected.get("downloadUrl") or ""),
            "localPath": str(local_path or ""),
            "localFileExists": bool(resolved_local and resolved_local.exists()),
            "contactSheetPath": str(contact_sheet_path or ""),
            "contactSheetExists": bool(resolved_contact_sheet and resolved_contact_sheet.exists()),
            "reframeSmokePath": str(reframe_smoke_path or ""),
            "reframeSmokeExists": bool(resolved_reframe_smoke and resolved_reframe_smoke.exists()),
            "reframeSmokeReviewPath": str(reframe_smoke_review_path or ""),
            "reframeSmokeReviewExists": bool(resolved_reframe_smoke_review and resolved_reframe_smoke_review.exists()),
            "reframeSmokeVerdict": str(raw.get("reframeSmokeVerdict") or ""),
            "previousLowerEmptyAreaConcernCorrected": raw.get("previousLowerEmptyAreaConcernCorrected") is True,
            "ffprobe": raw.get("ffprobe") if isinstance(raw.get("ffprobe"), dict) else {},
            "verdict": str(raw.get("verdict") or "needs-review"),
            "uploadReady": raw.get("uploadReady") is True,
            "requiresScriptRewrite": raw.get("requiresScriptRewrite") is True,
            "requiresPhoneFirstFrameReview": raw.get("requiresPhoneFirstFrameReview") is True,
            "requiresCropReframeTest": raw.get("requiresCropReframeTest") is True,
            "reason": str(raw.get("reason") or selected.get("reason") or ""),
        })

    conditional_count = sum(1 for item in candidates if item.get("verdict") == "conditional-fallback")
    failed_count = sum(1 for item in candidates if str(item.get("verdict") or "").startswith("fail"))
    upload_ready_count = sum(1 for item in candidates if item.get("uploadReady") is True)
    video_only_count = sum(1 for item in candidates if (item.get("ffprobe") or {}).get("hasAudio") is False)
    does_not_satisfy = review.get("doesNotSatisfy") if isinstance(review.get("doesNotSatisfy"), list) else [
        "fresh-source-proof",
        "final-mp4",
        "publish-packet",
        "phone-sized-review",
        "platform-analytics",
    ]
    status = str(review.get("status") or ("source-triage-only" if candidates else "research-without-structured-review"))
    return {
        "available": True,
        "projectId": project_id,
        "status": status,
        "reviewPath": str(review_path) if review_path else "",
        "downloadsPath": str(qa_dir / "selected-pexels-downloads.json") if (qa_dir / "selected-pexels-downloads.json").exists() else "",
        "directPexelsUrlOnly": review.get("directPexelsUrlOnly") is not False,
        "chromeDownloadUi": review.get("chromeDownloadUi") is True,
        "grokDownloadSaveExport": review.get("grokDownloadSaveExport") is True,
        "notFreshGrokProof": True,
        "notPublishPacket": True,
        "notUploadReadyEvidence": True,
        "uploadReady": upload_ready_count > 0 and upload_ready_count == len(candidates),
        "doesNotSatisfy": [str(item) for item in does_not_satisfy if item],
        "totalCandidates": len(candidates),
        "conditionalFallbackCandidates": conditional_count,
        "failedDirectUseCandidates": failed_count,
        "uploadReadyCandidates": upload_ready_count,
        "videoOnlyNoAudioCandidates": video_only_count,
        "scenes": sorted({str(item.get("sceneId") or "") for item in candidates if item.get("sceneId")}),
        "candidates": candidates,
        "operatorAction": str(review.get("operatorAction") or (
            "Treat free Pexels direct-URL candidates as source triage only. They need stock-fit review, script/layout rewrites, "
            "and phone-sized first-frame/crop checks before any accepted source decision."
        )),
    }


def _latest_pexels_expanded_search_summary(project_id: str) -> dict:
    project_id = str(project_id or "").strip()
    qa_root = _project_root / "storage" / "qa" / project_id
    if not project_id or not qa_root.exists():
        return {
            "available": False,
            "projectId": project_id,
            "status": "missing",
            "operatorAction": "No expanded Pexels scene search review is recorded for this fresh-source handoff.",
        }

    search_dirs = sorted(
        qa_root.glob("scene-*-pexels-expanded-search-*"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    if not search_dirs:
        return {
            "available": False,
            "projectId": project_id,
            "status": "missing",
            "operatorAction": "No expanded Pexels scene search review is recorded for this fresh-source handoff.",
        }

    review_dir = search_dirs[0]
    review_paths = sorted(
        review_dir.glob("expanded-search-review-*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    review_path = review_paths[0] if review_paths else None
    search_result_path = review_dir / "candidate-search-results.json"
    review = _read_json_artifact(review_path) if review_path else {}
    search_result = _read_json_artifact(search_result_path) if search_result_path.exists() else {}
    raw_candidates = review.get("candidates") if isinstance(review.get("candidates"), list) else []
    if not raw_candidates:
        raw_candidates = search_result.get("candidates") if isinstance(search_result.get("candidates"), list) else []

    candidates: list[dict] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        scene_id = str(raw.get("sceneId") or search_result.get("sceneId") or "").strip()
        if not scene_id:
            continue
        local_path = str(raw.get("localPath") or "")
        contact_sheet_path = str(raw.get("contactSheetPath") or "")
        resolved_local = _resolve_project_artifact_path(local_path)
        resolved_contact_sheet = _resolve_project_artifact_path(contact_sheet_path)
        verdict = str(raw.get("verdict") or "needs-review")
        candidates.append({
            "sceneId": scene_id,
            "provider": str(raw.get("provider") or "pexels-video"),
            "pexelsId": str(raw.get("pexelsId") or raw.get("id") or ""),
            "query": str(raw.get("query") or ""),
            "creator": str(raw.get("creator") or raw.get("author") or ""),
            "sourcePageUrl": str(raw.get("sourcePageUrl") or raw.get("sourceUrl") or ""),
            "downloadUrl": str(raw.get("downloadUrl") or raw.get("url") or ""),
            "thumbnailUrl": str(raw.get("thumbnailUrl") or ""),
            "durationSeconds": raw.get("durationSeconds") or raw.get("duration") or 0,
            "width": raw.get("width") or 0,
            "height": raw.get("height") or 0,
            "localPath": local_path,
            "localFileExists": bool(resolved_local and resolved_local.exists()),
            "contactSheetPath": contact_sheet_path,
            "contactSheetExists": bool(resolved_contact_sheet and resolved_contact_sheet.exists()),
            "verdict": verdict,
            "uploadReady": raw.get("uploadReady") is True,
            "requiresScriptRewrite": raw.get("requiresScriptRewrite") is True,
            "requiresPhoneFirstFrameReview": raw.get("requiresPhoneFirstFrameReview") is True,
            "recommendedUse": str(raw.get("recommendedUse") or ""),
            "reason": str(raw.get("reason") or ""),
        })

    rewrite_candidate_count = sum(1 for item in candidates if "rewrite" in str(item.get("verdict") or ""))
    rejected_count = sum(
        1
        for item in candidates
        if str(item.get("verdict") or "").startswith("reject")
        or str(item.get("verdict") or "").startswith("fail")
    )
    upload_ready_count = sum(1 for item in candidates if item.get("uploadReady") is True)
    status = str(review.get("status") or ("source-triage-only" if candidates else "search-without-review"))
    operator_action = str(review.get("operatorAction") or (
        "Use expanded Pexels candidates only as reviewed source triage. Rewrite the scene and rerun phone/source-fit review before render."
    ))
    return {
        "available": True,
        "projectId": project_id,
        "status": status,
        "reviewDir": str(review_dir),
        "reviewPath": str(review_path) if review_path else "",
        "searchResultPath": str(search_result_path) if search_result_path.exists() else "",
        "sceneIds": sorted({str(item.get("sceneId") or "") for item in candidates if item.get("sceneId")}),
        "candidateCount": len(candidates),
        "reviewedCandidateCount": int(review.get("reviewedCandidateCount") or len(candidates)),
        "rewriteCandidateCount": rewrite_candidate_count,
        "rejectedCandidateCount": rejected_count,
        "uploadReadyCandidates": upload_ready_count,
        "uploadReady": upload_ready_count > 0 and upload_ready_count == len(candidates),
        "doesNotSatisfy": [
            str(item)
            for item in (review.get("doesNotSatisfy") if isinstance(review.get("doesNotSatisfy"), list) else [
                "fresh-source-proof",
                "current-script-stock-fit-pass",
                "final-mp4",
                "publish-packet",
                "phone-sized-review",
            ])
            if item
        ],
        "candidates": candidates,
        "operatorAction": operator_action,
    }


def _latest_local_candidate_review_summary(project_id: str) -> dict:
    project_id = str(project_id or "").strip()
    review_dir = _project_root / "storage" / "qa" / project_id / "local-candidate-review"
    if not project_id or not review_dir.exists():
        return {
            "available": False,
            "projectId": project_id,
            "status": "missing",
            "operatorAction": "No local candidate review artifact is recorded for this fresh-source handoff.",
        }

    review_paths = sorted(
        review_dir.glob("source-recovery-review-*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    markdown_paths = sorted(
        review_dir.glob("visual-review-*.md"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    review_path = review_paths[0] if review_paths else None
    markdown_path = markdown_paths[0] if markdown_paths else None
    review = _read_json_artifact(review_path) if review_path else {}
    raw_scenes = review.get("scenes") if isinstance(review.get("scenes"), list) else []
    scenes: list[dict] = []
    for raw in raw_scenes:
        if not isinstance(raw, dict):
            continue
        scene_id = str(raw.get("sceneId") or "").strip()
        if not scene_id:
            continue
        contact_sheet_paths = raw.get("contactSheetPaths") if isinstance(raw.get("contactSheetPaths"), list) else []
        fail_categories = raw.get("failCategories") if isinstance(raw.get("failCategories"), list) else []
        verdict = str(raw.get("verdict") or raw.get("status") or "needs-review")
        scenes.append({
            "sceneId": scene_id,
            "status": str(raw.get("status") or verdict),
            "verdict": verdict,
            "uploadReady": raw.get("uploadReady") is True,
            "reviewedAllLocalCandidates": raw.get("reviewedAllLocalCandidates") is True,
            "reviewedCandidateCount": int(raw.get("reviewedCandidateCount") or 0),
            "selectedFileName": str(raw.get("selectedFileName") or ""),
            "contactSheetPaths": [str(path) for path in contact_sheet_paths if path],
            "failCategories": [str(category) for category in fail_categories if category],
            "operatorAction": str(raw.get("operatorAction") or ""),
            "notes": str(raw.get("notes") or raw.get("reason") or ""),
        })

    upload_ready_count = sum(1 for item in scenes if item.get("uploadReady") is True)
    failed_count = sum(
        1
        for item in scenes
        if item.get("uploadReady") is not True
        and (
            str(item.get("verdict") or "").startswith("fail")
            or str(item.get("verdict") or "") in {"needs-retry", "conditional-rewrite-only"}
        )
    )
    conditional_rewrite_count = sum(
        1
        for item in scenes
        if str(item.get("verdict") or "") in {"needs-retry", "conditional-rewrite-only"}
        or "rewrite" in str(item.get("operatorAction") or "").lower()
    )
    status = str(review.get("status") or ("review-recorded" if review_path else "markdown-only-review-recorded"))
    return {
        "available": bool(review_path or markdown_path),
        "projectId": project_id,
        "status": status,
        "structured": bool(review_path),
        "reviewPath": str(review_path) if review_path else str(markdown_path or ""),
        "markdownPath": str(markdown_path or ""),
        "reviewedAt": str(review.get("reviewedAt") or ""),
        "uploadReady": upload_ready_count > 0 and upload_ready_count == len(scenes),
        "reviewedScenes": len(scenes),
        "uploadReadyScenes": upload_ready_count,
        "failedScenes": failed_count,
        "conditionalRewriteScenes": conditional_rewrite_count,
        "doesNotSatisfy": [
            str(item)
            for item in (review.get("doesNotSatisfy") if isinstance(review.get("doesNotSatisfy"), list) else [])
            if item
        ],
        "policy": review.get("policy") if isinstance(review.get("policy"), dict) else {},
        "scenes": scenes,
        "operatorAction": str(review.get("operatorAction") or (
            "Use local candidate review as evidence only. Accept a scene only after the reviewed MP4 is upload-grade and the handoff review decision is updated."
        )),
    }


def _latest_selected_stock_rewrite_comparison() -> dict:
    render_root = _project_root / "storage" / "renders"
    if not render_root.exists():
        return {
            "available": False,
            "status": "missing",
            "operatorAction": "No selected-stock rewrite draft render-quality-report is available.",
        }

    report_paths = sorted(
        render_root.glob("*/render-quality-report.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    for report_path in report_paths:
        report = _read_json_artifact(report_path)
        if not isinstance(report, dict):
            continue
        project_id = str(report.get("projectId") or report_path.parent.name)
        title = str(report.get("title") or "")
        output_path = str(report.get("outputPath") or "")
        haystack = " ".join([project_id, title, output_path]).lower()
        if "rewrite" not in haystack or "selected-stock" not in haystack:
            continue

        production = report.get("productionReview") if isinstance(report.get("productionReview"), dict) else {}
        summary = production.get("summary") if isinstance(production.get("summary"), dict) else {}
        scenes_raw = production.get("scenes") if isinstance(production.get("scenes"), list) else []
        scenes_by_id = {
            str(scene.get("sceneId") or ""): scene
            for scene in scenes_raw
            if isinstance(scene, dict) and str(scene.get("sceneId") or "")
        }
        stock_scene_ids = [str(item) for item in (summary.get("stockVideoSceneIds") or []) if item]
        visual_scene_ids = {str(item) for item in (summary.get("visualVerdictScenes") or []) if item}
        failed_visual_ids = {str(item) for item in (summary.get("failedVisualVerdictScenes") or []) if item}
        caption_scene_ids = {str(item) for item in (summary.get("captionLayoutReviewScenes") or []) if item}
        missing_caption_ids = {str(item) for item in (summary.get("missingCaptionLayoutReviewScenes") or []) if item}
        top_tier = report.get("topTierReadiness") if isinstance(report.get("topTierReadiness"), dict) else {}
        top_summary = top_tier.get("summary") if isinstance(top_tier.get("summary"), dict) else {}
        channel = report.get("channelReadiness") if isinstance(report.get("channelReadiness"), dict) else {}
        upload = report.get("uploadReview") if isinstance(report.get("uploadReview"), dict) else {}
        publish = report.get("publishReadiness") if isinstance(report.get("publishReadiness"), dict) else {}
        original_clip_scenes = int(top_summary.get("originalClipScenes") or summary.get("grokHandoffScenes") or 0)
        min_original_scenes = int(top_summary.get("minOriginalScenes") or 3)
        stock_video_scenes = int(top_summary.get("stockVideoScenes") or len(stock_scene_ids))
        hero_original_ready = top_summary.get("originalHeroReady") is True or top_summary.get("grokOrLocalHeroReady") is True
        source_mix_ready = top_summary.get("originalSourceMixReady") is True
        upload_ready = (
            publish.get("status") == "ready"
            and channel.get("status") == "channel-ready"
            and upload.get("status") == "ready"
            and top_tier.get("status") == "top-tier-ready"
        )
        blockers: list[str] = []
        if not hero_original_ready:
            blockers.append("first hook is still selected-stock, not original/direct/Grok/local")
        if original_clip_scenes < min_original_scenes:
            blockers.append(f"original/direct/Grok/local source mix {original_clip_scenes}/{min_original_scenes}")
        if channel.get("status") != "channel-ready":
            blockers.append(f"channelReadiness={channel.get('status') or 'unknown'}")
        if upload.get("status") != "ready":
            blockers.append(f"uploadReview={upload.get('status') or 'unknown'}")
        if top_tier.get("status") != "top-tier-ready":
            blockers.append(f"topTierReadiness={top_tier.get('status') or 'unknown'}")

        scenes: list[dict] = []
        scenes_by_id_payload: dict[str, dict] = {}
        for scene_id in stock_scene_ids:
            scene = scenes_by_id.get(scene_id) or {}
            visual_pass = scene_id in visual_scene_ids and scene_id not in failed_visual_ids
            caption_reviewed = scene_id in caption_scene_ids and scene_id not in missing_caption_ids
            item = {
                "sceneId": scene_id,
                "projectId": project_id,
                "renderQualityReportPath": str(report_path),
                "outputPath": output_path,
                "visualVerdictPass": visual_pass,
                "captionLayoutReviewed": caption_reviewed,
                "sourceIntent": str(scene.get("visualSourceIntent") or "selected-stock"),
                "subtitleText": str(scene.get("subtitleText") or ""),
                "visualQualityVerdict": str(scene.get("visualQualityVerdict") or ""),
                "layoutVariantKey": str(scene.get("layoutVariantKey") or ""),
                "uploadReady": upload_ready,
                "sourceMixRegression": not source_mix_ready or original_clip_scenes < min_original_scenes,
                "heroOriginalReady": hero_original_ready,
                "originalClipScenes": original_clip_scenes,
                "minOriginalScenes": min_original_scenes,
                "stockVideoScenes": stock_video_scenes,
                "publishStatus": str(publish.get("status") or ""),
                "channelStatus": str(channel.get("status") or ""),
                "uploadStatus": str(upload.get("status") or ""),
                "topTierStatus": str(top_tier.get("status") or ""),
                "operatorAction": (
                    "Use this rewrite draft only as a comparison candidate: it may fix the scene visual/caption mismatch, "
                    "but it does not become upload-ready while source mix, first-hook originality, phone review, or top-tier gates fail."
                ),
            }
            scenes.append(item)
            scenes_by_id_payload[scene_id] = item

        return {
            "available": True,
            "status": "comparison-only-not-upload-ready" if not upload_ready else "upload-ready-review-required",
            "projectId": project_id,
            "renderQualityReportPath": str(report_path),
            "outputPath": output_path,
            "publishStatus": str(publish.get("status") or ""),
            "channelStatus": str(channel.get("status") or ""),
            "uploadStatus": str(upload.get("status") or ""),
            "topTierStatus": str(top_tier.get("status") or ""),
            "uploadReady": upload_ready,
            "originalClipScenes": original_clip_scenes,
            "minOriginalScenes": min_original_scenes,
            "stockVideoScenes": stock_video_scenes,
            "heroOriginalReady": hero_original_ready,
            "sourceMixReady": source_mix_ready,
            "blockers": blockers,
            "scenes": scenes,
            "scenesById": scenes_by_id_payload,
            "operatorAction": (
                "Compare this selected-stock rewrite against the current source-mix candidate. It can document scene rewrite progress, "
                "but it must not be promoted as upload-ready unless first-hook originality, source mix, phone review, fresh-source proof, "
                "and top-tier upload gates pass."
            ),
        }

    return {
        "available": False,
        "status": "missing",
        "operatorAction": "No selected-stock rewrite draft render-quality-report is available.",
    }


def _source_recovery_prompt_packet(project_id: str, scene_id: str, backlog_item: dict) -> dict:
    prompt_text = str(backlog_item.get("nextRetryPrompt") or "").strip()
    prompt_source = "replacement-backlog" if prompt_text else ""
    prompt_path = ""
    prompt_dir = _project_root / "storage" / "grok-handoffs" / project_id / "prompts"
    if not prompt_text and prompt_dir.exists():
        for candidate_name in (
            f"{scene_id}.retry.prompt.txt",
            f"{scene_id}.take-3.prompt.txt",
            f"{scene_id}.take-2.prompt.txt",
            f"{scene_id}.take-1.prompt.txt",
            f"{scene_id}.prompt.txt",
        ):
            candidate_path = prompt_dir / candidate_name
            if not candidate_path.exists():
                continue
            try:
                prompt_text = candidate_path.read_text(encoding="utf-8").strip()
            except OSError:
                prompt_text = ""
            if prompt_text:
                prompt_source = "handoff-prompt-file"
                prompt_path = str(candidate_path.relative_to(_project_root))
                break
    prompt_preview = prompt_text[:360] + ("..." if len(prompt_text) > 360 else "")
    return {
        "source": prompt_source or "missing",
        "promptPath": prompt_path,
        "promptText": prompt_text,
        "promptPreview": prompt_preview,
        "copyLabel": f"Copy {scene_id} recovery prompt",
    }


def _source_recovery_direct_import_runway(project_id: str, scene_id: str, scene_summary: dict, backlog_item: dict) -> dict:
    browser_generation = scene_summary.get("browserGeneration") if isinstance(scene_summary.get("browserGeneration"), dict) else {}
    observed_post_url = _sanitize_grok_observed_post_url(browser_generation.get("postUrl") or browser_generation.get("shareUrl"))
    expected_file_name = str(scene_summary.get("expectedFileName") or backlog_item.get("expectedFileName") or f"{scene_id}.grok.mp4").strip()
    upload_endpoint = f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{quote(project_id, safe='')}/upload-mp4"
    proof_monitor_url = (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/"
        f"{quote(project_id, safe='')}/direct-import-proof?sceneId={quote_plus(scene_id)}"
    )
    observed_post_download_script_url = (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/"
        f"{quote(project_id, safe='')}/observed-post-download.js?operatorApproved=true&sceneId={quote_plus(scene_id)}"
        if observed_post_url
        else ""
    )
    post_ready = bool(observed_post_url)
    return {
        "available": True,
        "status": "post-direct-import-ready" if post_ready else "needs-generation-before-direct-import",
        "sceneId": scene_id,
        "projectId": project_id,
        "expectedFileName": expected_file_name,
        "prompt": _source_recovery_prompt_packet(project_id, scene_id, backlog_item),
        "uploadEndpoint": upload_endpoint,
        "proofMonitorUrl": proof_monitor_url,
        "observedPostUrl": observed_post_url,
        "observedPostDownloadScriptUrl": observed_post_download_script_url,
        "requiresOperatorGeneration": not post_ready,
        "forbiddenActions": [
            "Grok Download",
            "Grok Save",
            "Grok Export",
            "Chrome native download prompt",
            "Downloads watcher fallback",
            "direct MP4 asset tab",
        ],
        "allowedRoutes": [
            "operator-owned manual download/import",
            "explicit manual MP4 upload",
            "operator-owned already-saved local MP4 import",
        ],
        "operatorAction": (
            f"Open the signed-in Grok post for {scene_id}, have the operator save/download the MP4, "
            f"and import {expected_file_name} locally before scene review."
            if post_ready
            else f"Generate {scene_id} from the recovery prompt, then use operator-owned local MP4 import; stop if Grok requires Codex to automate Download/Save/Export or a Chrome native download prompt."
        ),
    }


def _source_recovery_scene_blockers(
    backlog_item: dict,
    local_review: dict,
    expanded_summary: dict | None,
    selected_stock_rewrite_available: bool,
    recommended_lane: str,
) -> list[str]:
    blockers: list[str] = []

    def add(message: str) -> None:
        message = message.strip()
        if message and message not in blockers:
            blockers.append(message)

    add("rejected fresh-source scene has not been replaced and accepted")
    category_messages = {
        "weak-first-2s-hook": "first-two-second hook failed source review",
        "weak-thumbnail-or-first-frame": "thumbnail/first-frame failed source review",
        "ai-slop-or-stock-mismatch": "AI slop or stock/AI clip mismatch failed source review",
        "caption-safe-zone-risk": "caption safe-zone risk failed source review",
        "shot-continuity-mismatch": "shot continuity mismatch failed source review",
        "scene-assembly-risk": "scene assembly risk failed source review",
        "source-provenance-missing": "source provenance missing",
    }
    fail_categories = [
        str(category)
        for category in [
            *(backlog_item.get("failCategories") or []),
            *(local_review.get("failCategories") if isinstance(local_review.get("failCategories"), list) else []),
        ]
        if category
    ]
    for category in fail_categories:
        add(category_messages.get(category, f"{category} failed source review"))

    local_review_verdict = str(local_review.get("verdict") or local_review.get("status") or "").strip()
    if local_review and local_review.get("uploadReady") is not True:
        add("local replacement candidates are not upload-ready")
    if selected_stock_rewrite_available:
        add("selected-stock fallback requires script rewrite and phone-sized review before render")
    if expanded_summary and expanded_summary.get("uploadReady") is not True:
        add("expanded Pexels candidates are source triage only, not upload-ready")

    lane_blockers = {
        "review-local-candidates": "local replacement candidates still need operator source review",
        "accept-reviewed-local-candidate": "upload-grade local candidate is not accepted in the source review packet",
        "review-selected-stock-candidate": "selected-stock candidate still needs phone-sized source-fit and provenance review",
        "rewrite-selected-stock-fallback": "rewritten selected-stock fallback has not passed source-fit and phone-sized review",
        "regenerate-direct-import": "requires fresh direct-import regeneration before render",
    }
    add(lane_blockers.get(recommended_lane, "source recovery lane has not been completed"))
    if local_review_verdict.startswith("fail"):
        add("local review verdict still fails upload-grade source acceptance")
    return blockers


def _source_recovery_plan(
    latest_handoff: dict,
    pexels_research: dict,
    local_candidate_review: dict | None = None,
    pexels_expanded_search: dict | None = None,
) -> dict:
    latest_handoff = latest_handoff if isinstance(latest_handoff, dict) else {}
    pexels_research = pexels_research if isinstance(pexels_research, dict) else {}
    local_candidate_review = local_candidate_review if isinstance(local_candidate_review, dict) else {}
    pexels_expanded_search = pexels_expanded_search if isinstance(pexels_expanded_search, dict) else {}
    replacement_backlog = (
        latest_handoff.get("replacementBacklog")
        if isinstance(latest_handoff.get("replacementBacklog"), list)
        else []
    )
    pexels_candidates = {
        str(item.get("sceneId") or ""): item
        for item in (pexels_research.get("candidates") if isinstance(pexels_research.get("candidates"), list) else [])
        if isinstance(item, dict) and str(item.get("sceneId") or "").strip()
    }
    local_reviews = {
        str(item.get("sceneId") or ""): item
        for item in (local_candidate_review.get("scenes") if isinstance(local_candidate_review.get("scenes"), list) else [])
        if isinstance(item, dict) and str(item.get("sceneId") or "").strip()
    }
    expanded_pexels_candidates: dict[str, list[dict]] = {}
    for expanded_item in (pexels_expanded_search.get("candidates") if isinstance(pexels_expanded_search.get("candidates"), list) else []):
        if not isinstance(expanded_item, dict):
            continue
        expanded_scene_id = str(expanded_item.get("sceneId") or "").strip()
        if not expanded_scene_id:
            continue
        expanded_pexels_candidates.setdefault(expanded_scene_id, []).append(expanded_item)

    project_id = str(latest_handoff.get("projectId") or pexels_research.get("projectId") or pexels_expanded_search.get("projectId") or "")
    scene_summaries = {
        str(item.get("sceneId") or ""): item
        for item in (latest_handoff.get("scenes") if isinstance(latest_handoff.get("scenes"), list) else [])
        if isinstance(item, dict) and str(item.get("sceneId") or "").strip()
    }

    scenes: list[dict] = []
    for item in replacement_backlog:
        if not isinstance(item, dict):
            continue
        scene_id = str(item.get("sceneId") or "").strip()
        if not scene_id:
            continue
        pexels = pexels_candidates.get(scene_id) or {}
        local_review = local_reviews.get(scene_id) or {}
        unreviewed_local_count = int(item.get("unreviewedLocalCandidateCount") or 0)
        local_candidate_count = int(item.get("localCandidateCount") or 0)
        pexels_verdict = str(pexels.get("verdict") or "")
        reframe_smoke_verdict = str(pexels.get("reframeSmokeVerdict") or "")
        local_review_verdict = str(local_review.get("verdict") or local_review.get("status") or "")
        local_review_complete = bool(
            local_review
            and (
                local_review.get("reviewedAllLocalCandidates") is True
                or local_review_verdict.startswith("fail")
                or local_review_verdict in {"needs-retry", "conditional-rewrite-only"}
            )
        )
        local_review_upload_ready = bool(local_review and local_review.get("uploadReady") is True)
        selected_stock_rewrite_available = bool(
            pexels
            and (
                pexels_verdict == "conditional-fallback"
                or bool(reframe_smoke_verdict)
                or pexels.get("requiresScriptRewrite") is True
            )
        )
        pexels_direct_ready = bool(pexels and pexels.get("uploadReady") is True)
        if local_review_upload_ready:
            recommended_lane = "accept-reviewed-local-candidate"
            status = "local-candidate-ready-for-review-acceptance"
            operator_action = (
                f"Local review found an upload-grade candidate for {scene_id}; update the handoff review decision, "
                "then rerun source recovery and render gates before finalizing."
            )
        elif unreviewed_local_count > 0 and not local_review_complete:
            recommended_lane = "review-local-candidates"
            status = "local-review-needed"
            operator_action = (
                f"Review {unreviewed_local_count}/{local_candidate_count} local replacement candidate(s) for {scene_id} "
                "against first-2s hook, AI-slop/source-fit, caption safe zone, scene assembly, and source provenance. "
                "Accept only an upload-grade moving clip before render."
            )
        elif pexels_direct_ready:
            recommended_lane = "review-selected-stock-candidate"
            status = "selected-stock-review-needed"
            operator_action = (
                f"Phone-size review the selected-stock candidate for {scene_id}; keep source label/provenance and do not treat it as fresh Grok proof."
            )
        elif selected_stock_rewrite_available:
            recommended_lane = "rewrite-selected-stock-fallback"
            status = "script-rewrite-needed"
            operator_action = (
                f"Rewrite {scene_id} to fit the selected-stock fallback, then rerun phone-sized first-frame/caption/source-fit review. "
                "Do not accept the current rejected scene script unchanged."
            )
        else:
            recommended_lane = "regenerate-direct-import"
            status = "direct-import-regeneration-needed"
            operator_action = (
                f"Regenerate or acquire {scene_id} through operator-owned manual download/import "
                "or explicit already-saved local MP4 import. Native browser download prompts remain blocked."
            )

        scene_summary = scene_summaries.get(scene_id) or {}
        expanded_candidates = expanded_pexels_candidates.get(scene_id) or []
        expanded_summary = None
        if expanded_candidates:
            expanded_rewrite_count = sum(1 for candidate in expanded_candidates if "rewrite" in str(candidate.get("verdict") or ""))
            expanded_rejected_count = sum(
                1
                for candidate in expanded_candidates
                if str(candidate.get("verdict") or "").startswith("reject")
                or str(candidate.get("verdict") or "").startswith("fail")
            )
            expanded_upload_ready_count = sum(1 for candidate in expanded_candidates if candidate.get("uploadReady") is True)
            expanded_summary = {
                "available": True,
                "status": str(pexels_expanded_search.get("status") or "source-triage-only"),
                "reviewPath": str(pexels_expanded_search.get("reviewPath") or ""),
                "searchResultPath": str(pexels_expanded_search.get("searchResultPath") or ""),
                "candidateCount": len(expanded_candidates),
                "rewriteCandidateCount": expanded_rewrite_count,
                "rejectedCandidateCount": expanded_rejected_count,
                "uploadReadyCandidates": expanded_upload_ready_count,
                "uploadReady": expanded_upload_ready_count > 0 and expanded_upload_ready_count == len(expanded_candidates),
                "candidates": expanded_candidates[:6],
                "operatorAction": str(pexels_expanded_search.get("operatorAction") or (
                    f"Use expanded Pexels candidates for {scene_id} only as rewrite source triage; rerun source-fit and phone review before render."
                )),
            }
        render_blockers = _source_recovery_scene_blockers(
            item,
            local_review,
            expanded_summary,
            selected_stock_rewrite_available,
            recommended_lane,
        )
        scenes.append({
            "sceneId": scene_id,
            "status": status,
            "recommendedLane": recommended_lane,
            "directRenderAllowed": False,
            "uploadReady": False,
            "blocksRender": bool(render_blockers),
            "blocksFreshSourceProof": bool(render_blockers),
            "renderBlockers": render_blockers,
            "freshSourceProofBlockers": render_blockers,
            "renderBlockerCount": len(render_blockers),
            "freshSourceProofBlockerCount": len(render_blockers),
            "directImportRunway": _source_recovery_direct_import_runway(project_id, scene_id, scene_summary, item),
            "failCategories": [str(category) for category in (item.get("failCategories") or []) if category],
            "selectedFileName": str(item.get("selectedFileName") or ""),
            "localCandidateCount": local_candidate_count,
            "readyLocalCandidateCount": int(item.get("readyLocalCandidateCount") or 0),
            "unreviewedLocalCandidateCount": unreviewed_local_count,
            "unreviewedLocalCandidates": [str(name) for name in (item.get("unreviewedLocalCandidates") or []) if name],
            "selectedStockRewriteAvailable": selected_stock_rewrite_available,
            "pexelsCandidateFileName": str(pexels.get("candidateFileName") or ""),
            "pexelsVerdict": pexels_verdict,
            "pexelsRequiresScriptRewrite": pexels.get("requiresScriptRewrite") is True,
            "pexelsRequiresPhoneFirstFrameReview": pexels.get("requiresPhoneFirstFrameReview") is True,
            "pexelsReframeSmokeVerdict": reframe_smoke_verdict,
            "pexelsLowerFrameConcernCorrected": pexels.get("previousLowerEmptyAreaConcernCorrected") is True,
            "pexelsUploadReady": pexels_direct_ready,
            "expandedPexelsSearch": expanded_summary,
            "localReview": local_review if local_review else None,
            "operatorAction": operator_action,
        })

    local_review_count = sum(1 for item in scenes if item.get("recommendedLane") == "review-local-candidates")
    selected_stock_rewrite_count = sum(1 for item in scenes if item.get("selectedStockRewriteAvailable") is True)
    regenerate_count = sum(1 for item in scenes if item.get("recommendedLane") == "regenerate-direct-import")
    expanded_pexels_search_count = sum(1 for item in scenes if item.get("expandedPexelsSearch"))
    render_blocker_count = sum(int(item.get("renderBlockerCount") or 0) for item in scenes)
    scenes_blocking_render = [str(item.get("sceneId") or "") for item in scenes if item.get("blocksRender") is True]
    status = "needs-source-recovery" if scenes else (
        "no-rejected-scenes" if latest_handoff.get("status") == "accepted" else "waiting-for-source-review"
    )
    return {
        "available": bool(latest_handoff.get("available")),
        "projectId": project_id,
        "status": status,
        "uploadReady": False,
        "directRenderAllowed": False,
        "blockedByNativeDownloadPrompt": True,
        "totalScenes": len(scenes),
        "localReviewScenes": local_review_count,
        "selectedStockRewriteAvailableScenes": selected_stock_rewrite_count,
        "regenerateDirectImportScenes": regenerate_count,
        "expandedPexelsSearchScenes": expanded_pexels_search_count,
        "directImportRunwayScenes": len(scenes),
        "renderBlockerCount": render_blocker_count,
        "freshSourceProofBlockerCount": render_blocker_count,
        "scenesBlockingRender": scenes_blocking_render,
        "scenesBlockingFreshSourceProof": scenes_blocking_render,
        "latestLocalReview": local_candidate_review if local_candidate_review else {
            "available": False,
            "projectId": str(latest_handoff.get("projectId") or pexels_research.get("projectId") or ""),
            "status": "missing",
        },
        "latestExpandedPexelsSearch": pexels_expanded_search if pexels_expanded_search else {
            "available": False,
            "projectId": str(latest_handoff.get("projectId") or pexels_research.get("projectId") or ""),
            "status": "missing",
        },
        "reviewedLocalCandidateScenes": int(local_candidate_review.get("reviewedScenes") or 0),
        "failedLocalCandidateScenes": int(local_candidate_review.get("failedScenes") or 0),
        "conditionalRewriteLocalCandidateScenes": int(local_candidate_review.get("conditionalRewriteScenes") or 0),
        "scenes": scenes,
        "operatorAction": (
            "Resolve every source recovery scene before render: review local candidates first, use expanded Pexels candidates only as rewrite triage, "
            "rewrite only explicitly labeled selected-stock fallbacks, or regenerate through direct import. Do not use Chrome/Grok Download/Save/Export or native download prompts."
            if scenes
            else "No rejected source recovery scene is currently exposed; keep running fresh-source review before render."
        ),
    }


def _grok_direct_import_proof_monitor_url(context: dict | None = None) -> str:
    context = context or _latest_grok_handoff_context()
    project_id = str(context.get("projectId") or "grok-main-reset-routine-20260526-01")
    scene_id = str(context.get("sceneId") or "scene-01")
    return (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/"
        f"{quote(project_id, safe='')}/direct-import-proof?sceneId={quote_plus(scene_id)}"
    )


def _source_pipeline_status(report: dict) -> dict:
    local_adapters = {
        provider: probe_local_media_adapter(provider, project_root=_project_root).to_dict()
        for provider in sorted(_LOCAL_VIDEO_PROVIDERS)
    }
    pexels_key_ready = bool(os.environ.get("PEXELS_API_KEY", ""))
    channel = report.get("channelReadiness") or {}
    channel_summary = channel.get("summary") or {}
    production = report.get("productionReview") or {}
    production_summary = production.get("summary") or {}
    packet_summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    stock_curation = _stock_candidate_curation_summary(report)
    stock_curation_missing_scenes = stock_curation.get("missingScenes") or []
    latest_handoff_context = _latest_grok_handoff_context()
    latest_handoff_summary = _latest_grok_handoff_summary(latest_handoff_context)
    proof_monitor_url = _grok_direct_import_proof_monitor_url(latest_handoff_context)
    observed_post_url = str(latest_handoff_context.get("observedPostUrl") or "")
    handoff_project_id = str(latest_handoff_context.get("projectId") or "grok-main-reset-routine-20260526-01")
    handoff_scene_id = str(latest_handoff_context.get("sceneId") or "scene-01")
    pexels_replacement_research = _latest_pexels_replacement_research_summary(handoff_project_id)
    local_candidate_review = _latest_local_candidate_review_summary(handoff_project_id)
    pexels_expanded_search = _latest_pexels_expanded_search_summary(handoff_project_id)
    source_recovery_plan = _source_recovery_plan(
        latest_handoff_summary,
        pexels_replacement_research,
        local_candidate_review,
        pexels_expanded_search,
    )
    source_recovery_acceptance = _source_recovery_acceptance_status(handoff_project_id, source_recovery_plan)
    selected_stock_rewrite_comparison = _latest_selected_stock_rewrite_comparison()
    native_download_prompt_policy = {
        "status": "blocked-repeatability-fail",
        "allowedForCodexAutomation": False,
        "allowedForGoalCompletion": False,
        "blocksIfPromptAppears": True,
        "forbiddenActions": ["Grok Download", "Grok Save", "Grok Export", "Chrome native download prompt", "Downloads watcher fallback"],
        "allowedAlternatives": ["browser-control generation proof plus operator-owned local MP4 import", "explicit manual MP4 upload", "already-saved local MP4 import"],
        "reason": "Native browser download prompts wait for operator clicks and cannot be canceled repeatably by the production system.",
        "operatorAction": (
            "Do not use Chrome/Grok Download/Save/Export or any native download prompt from Codex automation. "
            "If the operator cannot save/download the MP4 and import it locally, mark the source flow blocked/not repeatable and close the prompt manually outside automation."
        ),
    }
    observed_post_download_script_url = (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/"
        f"{quote(handoff_project_id, safe='')}/observed-post-download.js?operatorApproved=true&sceneId={quote_plus(handoff_scene_id)}"
        if observed_post_url
        else ""
    )
    proof_monitor_hint = f" Proof monitor: {proof_monitor_url}"
    observed_post_hint = f" Observed Grok post: {observed_post_url}" if observed_post_url else ""
    grok_next_action = (
        "Use browser-control against the existing signed-in Chrome/Grok tab to fill and generate the Grok MP4. "
        "After generation proof exists, the operator downloads/saves the MP4 and imports it through local Downloads import or explicit batch upload. "
        "Do not let Codex click Chrome/Grok Download/Save/Export or treat a native prompt as repeatable automation."
    ) + proof_monitor_hint + observed_post_hint
    pexels_next_action = (
        "Complete Pexels candidate curation before claiming top-tier quality: record candidateCount>=2, source page/creator, and selectedCandidateSummary for "
        + (", ".join(stock_curation_missing_scenes) or "each selected stock scene")
        + "."
        if stock_curation.get("ready") is False
        else "Use Pexels candidates only after manual relevance review; keep Grok/local/direct MP4 for the first hook when claiming channel/top-tier quality."
    )
    return {
        "paidApiPolicy": {
            "paidAiApiAllowed": False,
            "disallowedByDefault": ["grok-api", "veo", "runway", "imagen", "elevenlabs", "openai-tts"],
            "allowedAutomation": "operator-approved Grok app/web browser handoff plus operator-owned local MP4 import only; no xAI API call or credential storage",
        },
        "grok": {
            "mode": "operator-approved-browser-handoff",
            "apiIntegration": False,
            "nextAction": grok_next_action,
            "nativeDownloadPromptPolicy": native_download_prompt_policy,
            "proofMonitorUrl": proof_monitor_url,
            "observedPostUrl": observed_post_url,
            "observedPostDownloadScriptUrl": observed_post_download_script_url,
            "handoffSelection": latest_handoff_context.get("handoffSelection") or {},
            "observedPostAction": (
                "Open this signed-in Grok post in the existing Chrome profile, then run the observed-post console direct-import snippet from the proof monitor. Do not click Download/Save/Export."
                if observed_post_url
                else ""
            ),
            "latestHandoff": latest_handoff_summary,
            "bookmarkletDirectImport": {
                "available": True,
                "operatorReady": True,
                "setupRequired": False,
                "uploadEndpointDriven": True,
                "avoidsChromeDownloadPrompt": True,
                "observedPostUrl": observed_post_url,
                "observedPostDownloadScriptUrl": observed_post_download_script_url,
                "sourceKinds": [
                    "bookmarklet-direct-video-fetch",
                    "bookmarklet-blob-direct-fetch",
                    "bookmarklet-post-direct-video-fetch",
                    "bookmarklet-post-blob-direct-fetch",
                ],
                "qualityNote": "legacy debug fallback only; no production success without operator-owned local MP4 import and review",
                "operatorAction": "Use only when browser-control is unavailable and the operator explicitly wants a debug recovery attempt. Production proof still requires operator-owned local MP4 import and Video Studio review.",
            },
            "dashboardControls": ["패킷 준비", "승인 자동 생성", "다음 씬 자동 생성", "승인 재개", "Grok 검수", "Grok 렌더"],
        },
        "localVideo": {
            "providers": local_adapters,
            "anyReady": any((status.get("ready") is True) for status in local_adapters.values()),
            "nextAction": "Configure a Wan/LTX/Hunyuan command adapter or paste a one-time JSON command override, then run 승인 로컬 생성 and review the returned MP4.",
        },
        "pexels": {
            "videoSearchReady": pexels_key_ready,
            "role": "free support footage; useful for context cuts, not enough alone for top-tier AI-assisted hero proof",
            "candidateCuration": stock_curation,
            "replacementResearch": pexels_replacement_research,
            "expandedSearch": pexels_expanded_search,
            "nextAction": pexels_next_action,
        },
        "sourceRecoveryPlan": source_recovery_plan,
        "sourceRecoveryAcceptance": source_recovery_acceptance,
        "selectedStockRewriteComparison": selected_stock_rewrite_comparison,
        "currentEvidence": {
            "heroAiOrLocalReady": channel_summary.get("heroAiOrLocalReady") is True or packet_summary.get("grokOrLocalHeroReady") is True,
            "heroOriginalClipReady": channel_summary.get("heroOriginalClipReady") is True or packet_summary.get("originalHeroReady") is True,
            "firstSceneHookReady": production_summary.get("firstSceneHookReady") is True or packet_summary.get("firstSceneHookReady") is True,
            "stockOnly": production_summary.get("stockOnly") is True,
            "missingRationaleScenes": production_summary.get("missingRationaleScenes") or [],
            "missingContinuityScenes": production_summary.get("missingContinuityScenes") or [],
            "missingNarrationScenes": production_summary.get("missingNarrationScenes") or [],
            "thinNarrationScenes": production_summary.get("thinNarrationScenes") or [],
            "missingCaptionLayoutReviewScenes": production_summary.get("missingCaptionLayoutReviewScenes") or [],
            "repeatedVisualAssetScenes": production_summary.get("repeatedVisualAssetScenes") or [],
            "missingFreeAssetProvenanceScenes": production_summary.get("missingFreeAssetProvenanceScenes") or [],
            "missingFreeAudioProvenanceAssets": production_summary.get("missingFreeAudioProvenanceAssets") or [],
            "stockCandidateCurationRecorded": stock_curation.get("recorded"),
            "stockCandidateCurationReady": stock_curation.get("ready"),
            "stockCandidateCurationStatus": stock_curation.get("status"),
            "stockCandidateCurationScenes": stock_curation.get("scenes") or [],
            "stockCandidateCurationReadyScenes": stock_curation.get("readyScenes") or [],
            "missingStockCandidateCurationScenes": stock_curation_missing_scenes,
            "stockCandidateCurationIssuesByScene": stock_curation.get("issuesByScene") or {},
        },
    }


def _existing_chrome_companion_readiness() -> dict:
    """Report local existing-Chrome readiness without starting browsers or reading secrets."""
    load_unpacked_path = _project_root / "tools" / "chrome-grok-companion"
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    profile_dir = Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Default" if local_app_data else None
    recognized: list[dict] = []

    def remember_extension(extension_id: str, name: str, title: str, path: str) -> None:
        lowered = " ".join([name, title, path]).lower()
        is_companion = "video studio grok companion" in lowered or "chrome-grok-companion" in lowered
        is_codex = name.lower() == "codex" or title.lower() == "codex"
        if not is_companion and not is_codex:
            return
        recognized.append({
            "id": extension_id,
            "name": name,
            "defaultTitle": title,
            "path": path,
            "isVideoStudioCompanion": is_companion,
            "isCodexExtension": is_codex,
        })

    if profile_dir and profile_dir.exists():
        extensions_dir = profile_dir / "Extensions"
        if extensions_dir.exists():
            for extension_dir in extensions_dir.iterdir():
                if not extension_dir.is_dir():
                    continue
                for manifest_path in extension_dir.glob("*/manifest.json"):
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    action = manifest.get("action") if isinstance(manifest.get("action"), dict) else {}
                    remember_extension(
                        extension_dir.name,
                        str(manifest.get("name") or ""),
                        str(action.get("default_title") or ""),
                        str(manifest_path.parent),
                    )
        preferences = _read_json_artifact(profile_dir / "Preferences") or {}
        extension_settings = ((preferences.get("extensions") or {}).get("settings") or {})
        if isinstance(extension_settings, dict):
            for extension_id, entry in extension_settings.items():
                if not isinstance(entry, dict):
                    continue
                manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
                action = manifest.get("action") if isinstance(manifest.get("action"), dict) else {}
                remember_extension(
                    str(extension_id),
                    str(manifest.get("name") or ""),
                    str(action.get("default_title") or ""),
                    str(entry.get("path") or ""),
                )

    companion_installed = any(item.get("isVideoStudioCompanion") for item in recognized)
    codex_extension_installed = any(item.get("isCodexExtension") for item in recognized)
    remote_debugging_port = 9222
    remote_debugging_listening = _is_local_tcp_port_listening("127.0.0.1", remote_debugging_port)
    return {
        "profileDir": str(profile_dir) if profile_dir else None,
        "profileDetected": bool(profile_dir and profile_dir.exists()),
        "loadUnpackedPath": str(load_unpacked_path),
        "companionInstalled": companion_installed,
        "codexExtensionInstalled": codex_extension_installed,
        "recognizedExtensions": recognized,
        "remoteDebuggingPort": remote_debugging_port,
        "remoteDebuggingListening": remote_debugging_listening,
        "operatorReady": companion_installed,
        "setupRequired": not companion_installed,
        "note": "Codex Chrome extension is not the Video Studio Grok Companion; load the project companion unpacked when setupRequired=true.",
    }


def _is_local_tcp_port_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _visual_fit_source_recovery_items(source_pipeline_status: dict | None, scene_ids: list[str]) -> list[dict]:
    if not isinstance(source_pipeline_status, dict):
        return []
    plan = source_pipeline_status.get("sourceRecoveryPlan")
    if not isinstance(plan, dict):
        return []
    rewrite_comparison = (
        source_pipeline_status.get("selectedStockRewriteComparison")
        if isinstance(source_pipeline_status.get("selectedStockRewriteComparison"), dict)
        else {}
    )
    rewrite_scenes = (
        rewrite_comparison.get("scenesById")
        if isinstance(rewrite_comparison.get("scenesById"), dict)
        else {}
    )
    raw_scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    target_ids = {str(scene_id).strip() for scene_id in scene_ids if str(scene_id).strip()}
    items: list[dict] = []
    for raw in raw_scenes:
        if not isinstance(raw, dict):
            continue
        scene_id = str(raw.get("sceneId") or "").strip()
        if not scene_id or (target_ids and scene_id not in target_ids):
            continue
        local_review = raw.get("localReview") if isinstance(raw.get("localReview"), dict) else {}
        item = {
            "sceneId": scene_id,
            "recommendedLane": str(raw.get("recommendedLane") or ""),
            "status": str(raw.get("status") or ""),
            "selectedFileName": str(raw.get("selectedFileName") or ""),
            "localReviewVerdict": str(local_review.get("verdict") or local_review.get("status") or ""),
            "localReviewUploadReady": local_review.get("uploadReady") is True,
            "pexelsCandidateFileName": str(raw.get("pexelsCandidateFileName") or ""),
            "pexelsVerdict": str(raw.get("pexelsVerdict") or ""),
            "pexelsRequiresScriptRewrite": raw.get("pexelsRequiresScriptRewrite") is True,
            "pexelsRequiresPhoneFirstFrameReview": raw.get("pexelsRequiresPhoneFirstFrameReview") is True,
            "directRenderAllowed": raw.get("directRenderAllowed") is True,
            "operatorAction": str(raw.get("operatorAction") or ""),
        }
        rewrite_scene = rewrite_scenes.get(scene_id)
        if isinstance(rewrite_scene, dict):
            item["selectedStockRewriteCandidate"] = rewrite_scene
        items.append(item)
    return items


def _visual_fit_source_recovery_detail(items: list[dict]) -> str:
    details: list[str] = []
    for item in items:
        scene_id = str(item.get("sceneId") or "").strip()
        if not scene_id:
            continue
        parts = [
            f"lane={item.get('recommendedLane') or 'unknown'}",
            f"localReview={item.get('localReviewVerdict') or 'not-recorded'}",
        ]
        if item.get("pexelsCandidateFileName"):
            parts.append(f"pexels={item.get('pexelsCandidateFileName')}")
        if item.get("pexelsVerdict"):
            parts.append(f"pexelsVerdict={item.get('pexelsVerdict')}")
        if item.get("pexelsRequiresScriptRewrite"):
            parts.append("scriptRewriteRequired=true")
        if item.get("directRenderAllowed") is False:
            parts.append("directRenderAllowed=false")
        rewrite = item.get("selectedStockRewriteCandidate")
        if isinstance(rewrite, dict):
            project_id = str(rewrite.get("projectId") or "").strip()
            rewrite_bits = [f"rewriteDraft={project_id or 'available'}"]
            if rewrite.get("visualVerdictPass") is True:
                rewrite_bits.append("visual=pass")
            if rewrite.get("captionLayoutReviewed") is True:
                rewrite_bits.append("caption=reviewed")
            if rewrite.get("sourceMixRegression") is True:
                rewrite_bits.append(
                    f"sourceMix={rewrite.get('originalClipScenes')}/{rewrite.get('minOriginalScenes')}"
                )
            if rewrite.get("heroOriginalReady") is False:
                rewrite_bits.append("heroOriginal=false")
            if rewrite.get("uploadReady") is False:
                rewrite_bits.append("uploadReady=false")
            parts.append(",".join(rewrite_bits))
        details.append(f"{scene_id}: " + ", ".join(parts))
    return "; ".join(details)


def _blocked_pipeline_next_actions(
    report: dict,
    error: str,
    require_channel_ready: bool,
    require_top_tier: bool = False,
    source_pipeline_status: dict | None = None,
) -> list[dict]:
    publish = report.get("publishReadiness") or {}
    channel = report.get("channelReadiness") or {}
    upload = report.get("uploadReview") or {}
    top_tier = report.get("topTierReadiness") or {}
    checks = report.get("checks") or {}
    production = report.get("productionReview") or {}
    production_summary = production.get("summary") or {}
    channel_summary = channel.get("summary") or {}
    first_scene_id = str(channel_summary.get("firstSceneId") or "scene-01")
    actions: list[dict] = []

    def _as_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _source_mix_criterion_failed() -> bool:
        for section in (top_tier, upload):
            for item in section.get("criteria") or []:
                if item.get("key") == "originalSourceMix" and item.get("status") == "fail":
                    return True
        return False

    moving = checks.get("movingClipPriority") if isinstance(checks.get("movingClipPriority"), dict) else {}
    source_motion = checks.get("sourceMotionEvidence") if isinstance(checks.get("sourceMotionEvidence"), dict) else {}
    if moving.get("status") == "fail" or source_motion.get("status") == "fail":
        actions.append({
            "key": "replace-low-motion-scenes",
            "priority": "required",
            "label": "Replace low-motion source clips",
            "detail": moving.get("detail") or source_motion.get("detail") or "Render uses MP4 containers but motion evidence is not strong enough.",
            "operatorAction": "Pick or generate short MP4s with visible first-two-second motion, then rerender before finalizing.",
        })

    if channel.get("status") != "channel-ready" or require_channel_ready or require_top_tier:
        if channel_summary.get("heroAiOrLocalReady") is not True:
            actions.append({
                "key": "add-grok-or-local-hero",
                "priority": "required" if require_channel_ready else "recommended",
                "label": "Add reviewed Grok/local AI hero MP4",
                "detail": f"{first_scene_id} does not yet prove Grok app/web or local Wan/LTX/Hunyuan hero footage.",
                "operatorAction": (
                    "Use the Grok app/web handoff path first: copy the scene prompt, generate the MP4 in the signed-in Grok UI, "
                    "then have the operator save/download and import it via Downloads import or explicit already-saved MP4 "
                    "batch upload before accepting the clip in Grok 검수. Do not press Grok Download/Save/Export or any "
                    "Chrome native download prompt from Codex automation. Use a local Wan/LTX/Hunyuan adapter only when "
                    "Grok output is unavailable."
                ),
            })

    top_tier_summary = top_tier.get("summary") or {}
    upload_summary = upload.get("summary") or {}
    source_mix_summary = top_tier_summary if top_tier_summary.get("originalSourceMixReady") is False else upload_summary
    source_mix_blocked = (
        top_tier.get("status") == "needs-original-source-mix"
        or top_tier_summary.get("originalSourceMixReady") is False
        or upload_summary.get("originalSourceMixReady") is False
        or _source_mix_criterion_failed()
    )
    if source_mix_blocked:
        original_scenes = _as_int(source_mix_summary.get("originalClipScenes"))
        min_scenes = _as_int(source_mix_summary.get("minOriginalScenes"))
        stock_scenes = _as_int(source_mix_summary.get("stockVideoScenes"))
        missing_count = max(1, min_scenes - original_scenes) if min_scenes else 1
        original_scene_ids = production_summary.get("originalClipSceneIds") or source_mix_summary.get("originalClipSceneIds") or []
        stock_scene_ids = production_summary.get("stockVideoSceneIds") or source_mix_summary.get("stockVideoSceneIds") or []
        actions.append({
            "key": "fix-original-source-mix",
            "priority": "required",
            "label": "Replace support stock with original/direct MP4",
            "detail": (
                f"original/direct/Grok/local scenes={original_scenes}/{min_scenes or 'required'}, "
                f"stockVideoScenes={stock_scenes}; "
                f"originalClipSceneIds={', '.join(original_scene_ids) or 'none'}; "
                f"stockVideoSceneIds={', '.join(stock_scene_ids) or 'not-recorded'}"
            ),
            "operatorAction": (
                f"Replace at least {missing_count} stock/support scene(s) with accepted Grok/local/direct/owned moving MP4 "
                "through operator-owned manual download/import or explicit already-saved MP4 batch import. Do not press "
                "Grok Download/Save/Export, open direct MP4 asset tabs, "
                "or rely on Chrome native download prompts or Downloads watcher fallback. Rerender and run "
                "finalize-render with requireTopTier=true."
            ),
        })

    failed_visual_scenes = production_summary.get("failedVisualVerdictScenes") or []
    missing_visual_scenes = production_summary.get("missingVisualVerdictScenes") or []
    ai_slop_check = checks.get("aiSlopVisualFit") if isinstance(checks.get("aiSlopVisualFit"), dict) else {}
    stock_fit_check = checks.get("stockAiClipFit") if isinstance(checks.get("stockAiClipFit"), dict) else {}
    if failed_visual_scenes or missing_visual_scenes or ai_slop_check.get("status") == "fail" or stock_fit_check.get("status") == "fail":
        detail_parts = []
        if failed_visual_scenes:
            detail_parts.append(f"failedVisualVerdictScenes={', '.join(failed_visual_scenes)}")
        if missing_visual_scenes:
            detail_parts.append(f"missingVisualVerdictScenes={', '.join(missing_visual_scenes)}")
        if stock_fit_check.get("status") == "fail":
            detail_parts.append(f"stockAiClipFit={stock_fit_check.get('detail') or 'fail'}")
        if ai_slop_check.get("status") == "fail":
            detail_parts.append(f"aiSlopVisualFit={ai_slop_check.get('detail') or 'fail'}")
        recovery_status = source_pipeline_status
        if not isinstance(recovery_status, dict):
            try:
                recovery_status = _source_pipeline_status(report)
            except Exception:
                recovery_status = {}
        visual_scene_ids = list(dict.fromkeys([
            str(scene_id)
            for scene_id in [*failed_visual_scenes, *missing_visual_scenes]
            if str(scene_id).strip()
        ]))
        recovery_items = _visual_fit_source_recovery_items(recovery_status, visual_scene_ids)
        recovery_detail = _visual_fit_source_recovery_detail(recovery_items)
        if recovery_detail:
            detail_parts.append(f"sourceRecovery={recovery_detail}")
        operator_action = (
            "Replace or rewrite the failed scene clips before upload. Use accepted Grok/local/direct/owned moving MP4s "
            "through operator-owned manual download/import or explicit already-saved MP4 batch import only. "
            "Keep Chrome/Grok Download/Save/Export, native download prompts, and Downloads watcher fallback blocked."
        )
        if recovery_items:
            lane_text = "; ".join(
                f"{item.get('sceneId')}: {item.get('recommendedLane') or 'source-recovery-needed'}"
                for item in recovery_items
                if item.get("sceneId")
            )
            operator_action += (
                f" Source recovery lanes: {lane_text}. Conditional selected-stock fallbacks still require a script rewrite, "
                "phone-sized first-frame/caption/source-fit review, and a rerender before any upload decision."
            )
            if any(isinstance(item.get("selectedStockRewriteCandidate"), dict) for item in recovery_items):
                operator_action += (
                    " Existing selected-stock rewrite drafts are comparison-only evidence: they can show a scene rewrite resolved "
                    "visual/caption issues, but they do not override source-mix, first-hook originality, phone review, fresh-source, "
                    "or top-tier upload gates."
                )
        action = {
            "key": "fix-visual-fit-failures",
            "priority": "required",
            "label": "Replace stock/AI visual-fit failures",
            "detail": "; ".join(detail_parts) or "Visual fit failed.",
            "operatorAction": operator_action,
        }
        if recovery_items:
            action["sourceRecovery"] = recovery_items
        actions.append(action)

    missing_caption_layout_scenes = production_summary.get("missingCaptionLayoutReviewScenes") or []
    if missing_caption_layout_scenes:
        actions.append({
            "key": "fix-caption-layout",
            "priority": "required",
            "label": "Fix caption layout review",
            "detail": f"Missing caption layout review scenes: {', '.join(missing_caption_layout_scenes)}",
            "operatorAction": "Move captions away from subject/right-bottom danger zones or disable captions per scene, then record the layout review.",
        })

    if require_top_tier and top_tier.get("status") != "top-tier-ready":
        actions.append({
            "key": "complete-top-tier-gate",
            "priority": "required",
            "label": "Complete top-tier readiness evidence",
            "detail": f"topTierReadiness={top_tier.get('status') or 'unknown'}",
            "operatorAction": "Create the first-hook MP4 through Grok app/web handoff or local Wan/LTX/Hunyuan, batch import and accept it, rerender, then pass the top-tier checklist before final-videos promotion.",
        })

    if channel_summary.get("heroOriginalClipReady") is not True:
        actions.append({
            "key": "add-original-hero-mp4",
            "priority": "required" if require_channel_ready or require_top_tier else "recommended",
            "label": "Make the first hook an original/direct/handoff MP4",
            "detail": f"{first_scene_id} must be a directly uploaded, Grok handoff, or local-model MP4 before channel-ready finalization.",
            "operatorAction": "Attach the MP4 to the first scene and keep source_rationale/originality_evidence/quality_review_note filled.",
        })

    if upload.get("status") != "ready":
        actions.append({
            "key": "complete-upload-review",
            "priority": "required",
            "label": "Complete final upload review",
            "detail": upload.get("status") or "Upload review is not ready.",
            "operatorAction": "Review thumbnail/first frame, audio mix, watermark/artifacts, safe zones, and platform benchmark notes before upload.",
        })

    audio_design_check = checks.get("ttsNarrationEvidence") if isinstance(checks.get("ttsNarrationEvidence"), dict) else {}
    voice_policy_check = checks.get("voicePolicyCompliance") if isinstance(checks.get("voicePolicyCompliance"), dict) else {}
    if (
        audio_design_check.get("status") != "pass"
        and (
            production_summary.get("missingNarrationScenes")
            or production_summary.get("thinNarrationScenes")
            or production_summary.get("voiceoverRequiredNoVoiceScenes")
        )
    ):
        actions.append({
            "key": "fix-viewer-audio-design",
            "priority": "required",
            "label": "Fix viewer-facing audio design",
            "detail": (
                f"missing={production_summary.get('missingNarrationScenes') or []}, "
                f"thin={production_summary.get('thinNarrationScenes') or []}, "
                f"voicePolicy={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}"
            ),
            "operatorAction": "For information/ranking/list output, add natural viewer-facing TTS/voiceover unless the operator explicitly approves a visual-led no-voice edit.",
        })
    if voice_policy_check.get("status") == "fail":
        actions.append({
            "key": "fix-template-voice-policy",
            "priority": "required",
            "label": "Fix template voice policy",
            "detail": voice_policy_check.get("detail") or "template voice policy failed",
            "operatorAction": "Add TTS/voiceover to information/ranking/list scenes or mark explicit human-approved visual-led no-voice evidence.",
        })

    bgm_sound_check = checks.get("bgmSoundQuality") if isinstance(checks.get("bgmSoundQuality"), dict) else {}
    if bgm_sound_check.get("status") == "fail":
        actions.append({
            "key": "replace-placeholder-bgm",
            "priority": "required",
            "label": "Replace beep/test-tone BGM",
            "detail": bgm_sound_check.get("detail") or "BGM sound quality failed",
            "operatorAction": "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed, then rerender.",
        })

    if production_summary.get("missingCaptionLayoutReviewScenes") and not any(
        item.get("key") == "fix-caption-layout" for item in actions
    ):
        actions.append({
            "key": "fix-caption-layout",
            "priority": "required",
            "label": "Fix caption layout review",
            "detail": f"Missing caption layout review scenes: {', '.join(production_summary.get('missingCaptionLayoutReviewScenes') or [])}",
            "operatorAction": "Move captions away from subject/right-bottom danger zones or disable captions per scene, then record the layout review.",
        })

    if production_summary.get("repeatedVisualAssetScenes"):
        actions.append({
            "key": "replace-reused-assets",
            "priority": "required",
            "label": "Replace repeated visual assets",
            "detail": f"Repeated visual asset scenes: {', '.join(production_summary.get('repeatedVisualAssetScenes') or [])}",
            "operatorAction": "Search/select different free clips or generate/direct-upload scene-specific MP4s before rerendering.",
        })

    missing_free_visual = production_summary.get("missingFreeAssetProvenanceScenes") or []
    missing_free_audio = production_summary.get("missingFreeAudioProvenanceAssets") or []
    if missing_free_visual or missing_free_audio:
        actions.append({
            "key": "record-free-asset-provenance",
            "priority": "required",
            "label": "Record free asset provenance",
            "detail": (
                f"Missing visual scenes: {', '.join(missing_free_visual) or 'none'}; "
                f"missing audio assets: {', '.join(missing_free_audio) or 'none'}"
            ),
            "operatorAction": "Keep source URL/ID/label for each free stock asset and source/license/attribution notes for BGM/SFX before finalization.",
        })

    if production_summary.get("missingRationaleScenes"):
        actions.append({
            "key": "fill-selection-rationale",
            "priority": "recommended",
            "label": "Fill manual selection rationale",
            "detail": f"Missing rationale scenes: {', '.join(production_summary.get('missingRationaleScenes') or [])}",
            "operatorAction": "Record why each stock/upload/Grok/local clip was selected for the scene intent.",
        })

    if not actions:
        actions.append({
            "key": "rerun-finalize",
            "priority": "next",
            "label": "Rerun finalization",
            "detail": error,
            "operatorAction": "Render and finalize again after the current blocked condition is cleared.",
        })

    return actions


def _write_blocked_quality_audit(
    output_path: Path,
    quality_path: Path,
    report: dict,
    error: str,
    require_channel_ready: bool,
    require_top_tier: bool = False,
    override_required_fixes: list[str] | None = None,
    override_recommended_fixes: list[str] | None = None,
) -> Path:
    publish = report.get("publishReadiness") or {}
    channel = report.get("channelReadiness") or {}
    upload = report.get("uploadReview") or {}
    top_tier = report.get("topTierReadiness") or {}
    checks = report.get("checks") or {}
    project_id = slugify(str(report.get("projectId") or output_path.parent.name or "blocked-render"))
    required_fixes = list(override_required_fixes or publish.get("requiredFixes") or [])
    recommended_fixes = list(override_recommended_fixes or publish.get("recommendedFixes") or [])
    if require_channel_ready:
        required_fixes = list(override_required_fixes or channel.get("requiredFixes") or required_fixes)
        recommended_fixes = list(override_recommended_fixes or channel.get("recommendedFixes") or recommended_fixes)
    if require_top_tier:
        required_fixes = list(override_required_fixes or top_tier.get("requiredFixes") or required_fixes)
        recommended_fixes = list(override_recommended_fixes or top_tier.get("recommendedFixes") or recommended_fixes)
    source_pipeline_status = _source_pipeline_status(report)
    next_actions = _blocked_pipeline_next_actions(
        report,
        error,
        require_channel_ready,
        require_top_tier,
        source_pipeline_status,
    )
    freshness = _quality_report_freshness(report)
    audit = {
        "projectId": project_id,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
        "error": error,
        "promotion": {
            "finalVideos": False,
            "reason": error,
            "requireChannelReady": require_channel_ready,
            "requireTopTier": require_top_tier,
        },
        "publishReadiness": publish,
        "channelReadiness": channel,
        "uploadReview": upload,
        "topTierReadiness": top_tier,
        "requiredFixes": required_fixes,
        "recommendedFixes": recommended_fixes,
        "qualityReportFreshness": freshness,
        "sourcePipelineStatus": source_pipeline_status,
        "nextActions": next_actions,
        "automatedEvidence": {
            "outputSpec": checks.get("outputSpec") or {},
            "noPlaceholders": checks.get("noPlaceholders") or {},
            "movingClipPriority": checks.get("movingClipPriority") or {},
            "sourceMotionEvidence": checks.get("sourceMotionEvidence") or {},
            "captionSafePresets": checks.get("captionSafePresets") or {},
            "aiSlopVisualFit": checks.get("aiSlopVisualFit") or {},
            "stockAiClipFit": checks.get("stockAiClipFit") or {},
            "ttsNarrationEvidence": checks.get("ttsNarrationEvidence") or {},
            "voicePolicyCompliance": checks.get("voicePolicyCompliance") or {},
            "captionLayoutReview": checks.get("captionLayoutReview") or {},
            "captionDensityAndSafeZone": checks.get("captionDensityAndSafeZone") or {},
            "assetReuseDiversity": checks.get("assetReuseDiversity") or {},
            "freeAssetProvenance": checks.get("freeAssetProvenance") or {},
            "stockCandidateCuration": checks.get("stockCandidateCuration") or {},
            "bgmAssetRotation": checks.get("bgmAssetRotation") or {},
            "bgmSoundQuality": checks.get("bgmSoundQuality") or {},
            "publishReadinessGate": checks.get("publishReadinessGate") or {},
            "channelReadinessGate": checks.get("channelReadinessGate") or {},
            "uploadReviewGate": checks.get("uploadReviewGate") or {},
            "topTierReadinessGate": checks.get("topTierReadinessGate") or {},
        },
        "summary": {
            "readyForUpload": False,
            "channelReady": False,
            "topTierReady": False,
            "publishStatus": publish.get("status") or "unknown",
            "channelStatus": channel.get("status") or "unknown",
            "uploadStatus": upload.get("status") or "unknown",
            "topTierStatus": top_tier.get("status") or "unknown",
            "checksNeeded": [
                key
                for key, value in checks.items()
                if isinstance(value, dict) and value.get("status") != "pass"
            ],
            "nextActionKeys": [item.get("key") for item in next_actions],
        },
    }
    _attach_quality_gate_fields(audit)
    audit_path = output_path.parent / "blocked-quality-audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit_path


@media_bp.route("/api/finalize-render", methods=["POST"])
def finalize_render_route():
    """Copy a publish-ready render into storage/final-videos with QA artifacts."""
    data = flask_request.get_json(silent=True) or {}
    output_path_raw = str(data.get("outputPath") or "").strip()
    if not output_path_raw:
        return jsonify({"ok": False, "error": "outputPath is required"}), 400

    output_path = _resolve_project_file(output_path_raw)
    if not output_path or not output_path.exists() or output_path.suffix.lower() != ".mp4":
        return jsonify({"ok": False, "error": "outputPath must be an existing MP4 under the project root"}), 400

    quality_path_raw = str(data.get("qualityReportPath") or "").strip()
    quality_path = _resolve_project_file(quality_path_raw) if quality_path_raw else output_path.parent / "render-quality-report.json"
    if not quality_path or not quality_path.exists():
        return jsonify({"ok": False, "error": "qualityReportPath is required or render-quality-report.json must exist beside the MP4"}), 400

    try:
        report = _read_quality_report(quality_path)
    except (OSError, json.JSONDecodeError) as exc:
        return jsonify({"ok": False, "error": f"quality report is unreadable: {exc}"}), 400

    readiness = report.get("publishReadiness") or {}
    channel_readiness = report.get("channelReadiness") or {}
    top_tier_readiness = report.get("topTierReadiness") or {}
    readiness_status = str(readiness.get("status") or "unknown")
    channel_status = str(channel_readiness.get("status") or "unknown")
    top_tier_status = str(top_tier_readiness.get("status") or "unknown")
    require_channel_ready = bool(data.get("requireChannelReady"))
    require_top_tier = bool(data.get("requireTopTier"))
    if require_top_tier:
        require_channel_ready = True
    freshness = _quality_report_freshness(report)
    if not freshness["ok"]:
        blocked_audit_path = _write_blocked_quality_audit(
            output_path,
            quality_path,
            report,
            "quality report is stale",
            require_channel_ready,
            require_top_tier,
            freshness["requiredFixes"],
            freshness["recommendedFixes"],
        )
        return jsonify({
            "ok": False,
            "error": "quality report is stale",
            "publishReadiness": readiness,
            "channelReadiness": channel_readiness,
            "topTierReadiness": top_tier_readiness,
            "qualityReportFreshness": freshness,
            "requiredFixes": freshness["requiredFixes"],
            "recommendedFixes": freshness["recommendedFixes"],
            "blockedQualityAuditPath": str(blocked_audit_path),
            "sourcePipelineStatus": _source_pipeline_status(report),
            "nextActions": _blocked_pipeline_next_actions(report, "quality report is stale", require_channel_ready, require_top_tier),
        }), 409
    if readiness_status != "ready":
        blocked_audit_path = _write_blocked_quality_audit(
            output_path,
            quality_path,
            report,
            "render is not publish-ready",
            require_channel_ready,
            require_top_tier,
        )
        return jsonify({
            "ok": False,
            "error": "render is not publish-ready",
            "publishReadiness": readiness,
            "channelReadiness": channel_readiness,
            "topTierReadiness": top_tier_readiness,
            "requiredFixes": readiness.get("requiredFixes") or [],
            "recommendedFixes": readiness.get("recommendedFixes") or [],
            "blockedQualityAuditPath": str(blocked_audit_path),
            "sourcePipelineStatus": _source_pipeline_status(report),
            "nextActions": _blocked_pipeline_next_actions(report, "render is not publish-ready", require_channel_ready, require_top_tier),
        }), 409
    if require_channel_ready and channel_status != "channel-ready":
        blocked_audit_path = _write_blocked_quality_audit(
            output_path,
            quality_path,
            report,
            "render is not channel-ready",
            require_channel_ready,
            require_top_tier,
        )
        return jsonify({
            "ok": False,
            "error": "render is not channel-ready",
            "publishReadiness": readiness,
            "channelReadiness": channel_readiness,
            "topTierReadiness": top_tier_readiness,
            "requiredFixes": channel_readiness.get("requiredFixes") or [],
            "recommendedFixes": channel_readiness.get("recommendedFixes") or [],
            "blockedQualityAuditPath": str(blocked_audit_path),
            "sourcePipelineStatus": _source_pipeline_status(report),
            "nextActions": _blocked_pipeline_next_actions(report, "render is not channel-ready", require_channel_ready, require_top_tier),
        }), 409
    if require_top_tier and top_tier_status != "top-tier-ready":
        blocked_audit_path = _write_blocked_quality_audit(
            output_path,
            quality_path,
            report,
            "render is not top-tier-ready",
            require_channel_ready,
            require_top_tier,
        )
        return jsonify({
            "ok": False,
            "error": "render is not top-tier-ready",
            "publishReadiness": readiness,
            "channelReadiness": channel_readiness,
            "topTierReadiness": top_tier_readiness,
            "requiredFixes": top_tier_readiness.get("requiredFixes") or [],
            "recommendedFixes": top_tier_readiness.get("recommendedFixes") or [],
            "blockedQualityAuditPath": str(blocked_audit_path),
            "sourcePipelineStatus": _source_pipeline_status(report),
            "nextActions": _blocked_pipeline_next_actions(report, "render is not top-tier-ready", require_channel_ready, require_top_tier),
        }), 409

    project_id = slugify(str(data.get("projectId") or report.get("projectId") or output_path.parent.name or "publish-render"))
    final_dir = _project_root / "storage" / "final-videos" / project_id
    final_dir.mkdir(parents=True, exist_ok=True)

    final_video = final_dir / output_path.name
    final_report = final_dir / "render-quality-report.json"
    checklist_path = final_dir / "publish-checklist.md"
    quality_checklist_path = final_dir / "quality-checklist.md"
    quality_audit_path = final_dir / "quality-audit.json"
    publish_packet_path = final_dir / "publish-packet.json"
    publish_packet_markdown_path = final_dir / "publish-packet.md"
    shutil.copy2(output_path, final_video)
    shutil.copy2(quality_path, final_report)

    manifest_artifact = None
    manifest_path_raw = str(report.get("manifestPath") or "").strip()
    manifest_path = _resolve_project_file(manifest_path_raw) if manifest_path_raw else None
    if manifest_path and manifest_path.exists():
        manifest_artifact = final_dir / "render-manifest.json"
        shutil.copy2(manifest_path, manifest_artifact)

    _write_publish_checklist(checklist_path, report, final_video, final_report)
    review_frames, contact_sheet = _extract_review_frames(final_video, final_dir, report)
    audio_level = _measure_audio_level(final_video)
    _write_final_quality_checklist(
        quality_checklist_path,
        report,
        final_video,
        review_frames,
        contact_sheet,
        audio_level,
    )
    quality_audit = _build_final_quality_audit(
        report,
        final_video,
        review_frames,
        contact_sheet,
        audio_level,
    )
    quality_audit_path.write_text(json.dumps(quality_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    publish_packet = _build_publish_packet(
        report,
        final_video,
        final_report,
        quality_audit,
        review_frames,
        contact_sheet,
        audio_level,
    )
    publish_packet_path.write_text(json.dumps(publish_packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_publish_packet_markdown(publish_packet_markdown_path, publish_packet)

    artifacts = {
        "finalVideoPath": str(final_video),
        "finalQualityReportPath": str(final_report),
        "publishChecklistPath": str(checklist_path),
        "qualityChecklistPath": str(quality_checklist_path),
        "qualityAuditPath": str(quality_audit_path),
        "publishPacketPath": str(publish_packet_path),
        "publishPacketMarkdownPath": str(publish_packet_markdown_path),
        "publishPacket": publish_packet,
        "qualityAudit": quality_audit,
        "reviewFramePaths": [str(path) for path in review_frames],
        "audioLevel": audio_level,
    }
    if contact_sheet:
        artifacts["contactSheetPath"] = str(contact_sheet)
    if manifest_artifact:
        artifacts["renderManifestPath"] = str(manifest_artifact)

    return jsonify({
        "ok": True,
        "projectId": project_id,
        "publishReadiness": readiness,
        "channelReadiness": channel_readiness,
        "topTierReadiness": top_tier_readiness,
        "uploadReview": report.get("uploadReview") or {},
        "channelReadyRequired": require_channel_ready,
        "topTierRequired": require_top_tier,
        **artifacts,
    })


# ---------------------------------------------------------------------------
# Translation / Dubbing
# ---------------------------------------------------------------------------

@media_bp.route("/api/dub", methods=["POST"])
def dub_route():
    """Transcribe + translate + generate TTS for a foreign-language audio file."""
    data = flask_request.get_json(silent=True) or {}
    source_path = data.get("source_path", "").strip()
    if not source_path:
        return jsonify({"ok": False, "error": "source_path is required"}), 400
    source = _safe_resolve(source_path, _project_root)
    if not source or not source.exists():
        return jsonify({"ok": False, "error": "File not found or path not allowed"}), 400

    target_lang = data.get("target_lang", "ko")
    tts_provider = data.get("tts_provider", "edge")
    voice_gender = data.get("voice_gender", "female")
    whisper_model = data.get("whisper_model", "base")
    style = data.get("style", "natural")

    try:
        from worker.translation.dubbing import dub_audio
        result = dub_audio(
            source_audio=source,
            target_lang=target_lang,
            tts_provider=tts_provider,
            voice_gender=voice_gender,
            whisper_model=whisper_model,
            translation_style=style,
        )
        return jsonify({"ok": True, **result})
    except Exception as e:
        # Flask route handler: broad catch required to convert any downstream
        # failure into a 500 response; log for observability.
        logger.warning("%s failed: %s", flask_request.path, e)
        return jsonify({"ok": False, "error": str(e)}), 500
