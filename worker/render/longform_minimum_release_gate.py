"""Minimum publishable release gate for longform candidates.

This is intentionally separate from shortform golden/reference gates. It only
answers whether a `longform_10m` final-readiness claim has enough objective
evidence to be called minimally publishable.
"""

from __future__ import annotations

from typing import Any


LONGFORM_MINIMUM_RELEASE_GATE_KEYS = (
    "longformReleaseFormatGate",
    "longformReleaseRightsGate",
    "longformReleaseDisclosureGate",
    "longformReleaseSourceContinuityGate",
    "longformReleaseScriptTtsCaptionGate",
    "longformReleaseEditorialGate",
    "longformReleaseAudioGate",
    "longformReleaseFullWatchGate",
    "longformReleaseScoreGate",
)

LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS = {
    "storyPackage": 12,
    "evidenceRightsProviderSafety": 13,
    "publishDisclosureSafety": 10,
    "sourceVisualContinuity": 18,
    "scriptTtsCaptionSync": 14,
    "editorialDirectionLayout": 13,
    "audioBgmSfxMix": 10,
    "fullWatchDefectControl": 10,
}

MINIMUM_RELEASE_SCORE = 72
LONGFORM_MIN_DURATION_SEC = 480
LONGFORM_MAX_DURATION_SEC = 900
LONGFORM_PUBLISH_PACKET_TEMPLATE_SCHEMA = "video-studio.longform-publish-packet-template.v1"

PASS_STATUSES = {"pass", "passed", "approved", "complete", "completed", "ready", "reviewed-pass"}
RIGHTS_OK_STATUSES = {
    "owned",
    "licensed",
    "public-domain",
    "cc0",
    "cc-by",
    "cc-by-sa",
    "editorial-approved",
    "operator-approved",
    "commercial-approved",
    "commercial-use-allowed",
}
RIGHTS_AMBIGUOUS_STATUSES = {
    "creative-commons",
    "cc",
}
RIGHTS_BLOCK_STATUSES = {
    "research-only",
    "non-commercial",
    "private-only",
    "personal-use-only",
    "unknown",
    "unverified",
    "unclear",
    "trial-only",
    "cc-by-nd",
    "cc-by-nc",
    "cc-by-nc-sa",
    "cc-by-nc-nd",
}
AI_USE_DECISIONS = {"yes", "no"}
CONTENT_CREDENTIALS_STATUSES = {
    "not-present",
    "none",
    "present",
    "preserved",
    "verified",
    "not-applicable",
    "unknown",
}
DISCLOSURE_REQUIRED_SIGNALS = {
    "realisticGenAiOrAltered",
    "photorealisticAi",
    "meaningfullyAltered",
    "aiGeneratedRealisticScene",
    "realPersonDepiction",
    "realEventOrPlaceAltered",
    "syntheticVoiceOrMusic",
}


def evaluate_longform_minimum_release_gate(packet: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a longform final candidate against minimum release evidence."""

    score_inputs = _score_inputs(packet)
    computed_score = sum(score_inputs.values())
    report: dict[str, Any] = {
        "schema": "video-studio.longform-minimum-release-gate.v1",
        "status": "pass",
        "releaseAllowed": False,
        "computedScore": computed_score,
        "minimumScore": MINIMUM_RELEASE_SCORE,
        "scoreInputs": score_inputs,
        "failedChecks": [],
        "checks": {},
    }

    _check_format(report, packet)
    _check_rights(report, packet)
    _check_disclosure(report, packet)
    _check_source_continuity(report, packet)
    _check_script_tts_caption(report, packet)
    _check_editorial(report, packet)
    _check_audio(report, packet)
    _check_full_watch(report, packet)
    _check_score(report, packet, computed_score)

    if report["failedChecks"]:
        report["status"] = "fail"
        report["releaseAllowed"] = False
    else:
        report["releaseAllowed"] = True
    return report


def build_longform_publish_packet_template(
    material: dict[str, Any] | None = None,
    release_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an operator-fillable longform publish packet scaffold."""

    material = material if isinstance(material, dict) else {}
    release_packet = release_packet if isinstance(release_packet, dict) else {}
    title = _text(material.get("title") or release_packet.get("title"))
    central_question = _text(material.get("centralQuestion") or release_packet.get("centralQuestion"))
    search_seed = _text(material.get("searchSeed") or release_packet.get("searchSeed"))
    return {
        "schema": LONGFORM_PUBLISH_PACKET_TEMPLATE_SCHEMA,
        "materialId": material.get("materialId") or release_packet.get("materialId"),
        "title": title,
        "centralQuestion": central_question,
        "searchSeed": search_seed,
        "targetPlatform": "youtube",
        "targetFormat": "longform_10m",
        "releasePacketInput": {
            "required": True,
            "minimumReleaseGate": "worker/render/longform_minimum_release_gate.py:evaluate_longform_minimum_release_gate",
            "requiredObjects": [
                "chapters",
                "sourceReviewImport",
                "scriptTtsCaptionReview",
                "editorialReleaseReview",
                "audioReleaseReview",
                "fullWatchReview",
                "publishDisclosureReview",
            ],
        },
        "publishDisclosureReview": {
            "schema": "video-studio.publish-disclosure-review.v1",
            "platform": "youtube",
            "aiUseDecision": "",
            "realisticGenAiOrAltered": True,
            "aiUseDisclosureRequired": True,
            "youtubeAiUseSelected": False,
            "disclosureStatement": "",
            "contentCredentialsStatus": "not-present",
            "contentCredentialsSource": "",
            "viewerMisleadRiskReviewed": False,
            "inaccurateAuthenticityClaim": False,
            "capturedWithCameraClaim": False,
            "inauthenticRiskReview": {
                "massProducedTemplate": False,
                "originalInsightAdded": False,
                "substantiveVariation": False,
                "metadataTruthful": False,
                "reusedContentTransformative": False,
            },
        },
        "uploadChecklist": {
            "titleThumbnailTruthful": False,
            "descriptionCreditsReady": False,
            "rightsAndLicenseNotesReady": False,
            "thumbnailFirstFrameReviewed": False,
            "humanUploadDecision": "",
        },
        "requiredBeforePublish": [
            "passing longform minimum release gate",
            "publishDisclosureReview.aiUseDecision",
            "publishDisclosureReview.youtubeAiUseSelected when realisticGenAiOrAltered=true",
            "publishDisclosureReview.contentCredentialsStatus",
            "publishDisclosureReview.inauthenticRiskReview",
            "uploadChecklist human decision",
        ],
        "reference": "docs/reference/youtube-ai-disclosure-publish-gate.md",
    }


def _check_format(report: dict[str, Any], packet: dict[str, Any]) -> None:
    profile = _text(packet.get("formatProfile") or packet.get("format_profile") or packet.get("productionMode"))
    duration = _duration_sec(packet)
    chapters = _chapters(packet)
    segment_count = sum(len(_segments(chapter)) for chapter in chapters)
    problems: list[str] = []
    if profile != "longform_10m":
        problems.append("formatProfile must be longform_10m")
    if duration is None or duration < LONGFORM_MIN_DURATION_SEC or duration > LONGFORM_MAX_DURATION_SEC:
        problems.append("durationSec must stay in the longform_10m 480-900 second range")
    if len(chapters) < 6:
        problems.append("minimum release needs at least 6 chapters")
    if segment_count < 18:
        problems.append("minimum release needs at least 18 planned segments")
    if problems:
        _fail(report, "longformReleaseFormatGate", "; ".join(problems))
        return
    _set_check(report, "longformReleaseFormatGate", "pass", f"{len(chapters)} chapters, {segment_count} segments, durationSec={duration:g}.")


def _check_rights(report: dict[str, Any], packet: dict[str, Any]) -> None:
    source_items = _source_right_items(packet)
    problems: list[str] = []
    if not source_items:
        problems.append("minimum release needs source/evidence rights items")
    for item in source_items:
        provider = _text(item.get("provider") or item.get("sourceProvider") or item.get("model")).lower()
        rights = _text(item.get("rightsStatus") or item.get("rights") or item.get("license")).lower()
        explicit_commercial = item.get("commercialUseAllowed") is True
        commercial_allowed = explicit_commercial or rights in RIGHTS_OK_STATUSES
        if any(token in provider for token in ("dreamina", "seedance")) and not explicit_commercial:
            problems.append(f"{_item_label(item)} uses {provider or 'provider'} without explicit commercialUseAllowed=true")
        if not rights:
            problems.append(f"{_item_label(item)} missing rightsStatus")
        elif rights in RIGHTS_BLOCK_STATUSES:
            problems.append(f"{_item_label(item)} rightsStatus={rights} is blocked for release")
        elif rights in RIGHTS_AMBIGUOUS_STATUSES and not explicit_commercial:
            problems.append(f"{_item_label(item)} rightsStatus={rights} requires explicit commercialUseAllowed=true")
        elif not commercial_allowed:
            problems.append(f"{_item_label(item)} rightsStatus={rights} is not a release-approved status")
    if problems:
        _fail(report, "longformReleaseRightsGate", "; ".join(problems[:6]))
        return
    _set_check(report, "longformReleaseRightsGate", "pass", f"{len(source_items)} source/evidence rights items are release-approved.")


def _check_disclosure(report: dict[str, Any], packet: dict[str, Any]) -> None:
    disclosure = _disclosure_review(packet)
    risk = _inauthentic_risk_review(disclosure, packet)
    decision = _text(
        disclosure.get("aiUseDecision")
        or disclosure.get("youtubeAiUseDecision")
        or disclosure.get("aiUse")
    ).lower()
    c2pa_status = _text(
        disclosure.get("contentCredentialsStatus")
        or disclosure.get("c2paStatus")
        or disclosure.get("contentCredentials")
    ).lower()
    realistic_required = _disclosure_required(disclosure)
    problems: list[str] = []
    if decision not in AI_USE_DECISIONS:
        problems.append("aiUseDecision must be yes or no")
    if realistic_required and decision != "yes":
        problems.append("realistic or meaningfully altered AI content must select aiUseDecision=yes")
    if realistic_required and disclosure.get("youtubeAiUseSelected") is not True:
        problems.append("YouTube Studio AI use must be selected for realistic altered/synthetic content")
    if not _text(disclosure.get("disclosureStatement") or disclosure.get("operatorDisclosureNote")):
        problems.append("disclosureStatement is required")
    if not c2pa_status or c2pa_status not in CONTENT_CREDENTIALS_STATUSES:
        problems.append("contentCredentialsStatus must be explicit")
    if c2pa_status in {"present", "preserved", "verified"} and not _text(
        disclosure.get("contentCredentialsSource") or disclosure.get("c2paSigningAuthority")
    ):
        problems.append("C2PA/content credentials source is required when metadata is present")
    if disclosure.get("viewerMisleadRiskReviewed") is not True:
        problems.append("viewerMisleadRiskReviewed=true is required")
    if disclosure.get("inaccurateAuthenticityClaim") is True or disclosure.get("capturedWithCameraClaim") is True:
        problems.append("publish packet cannot make an inaccurate captured-with-camera/authenticity claim")
    if risk.get("massProducedTemplate") is True:
        problems.append("mass-produced template risk must be false")
    if risk.get("metadataTruthful") is not True:
        problems.append("upload metadata must be truthful about AI/source/editorial work")
    if risk.get("originalInsightAdded") is not True and risk.get("substantiveOriginalCommentary") is not True:
        problems.append("original insight or substantive commentary is required")
    if risk.get("substantiveVariation") is not True and risk.get("reusedContentTransformative") is not True:
        problems.append("substantive variation or transformative reuse evidence is required")
    if problems:
        _fail(report, "longformReleaseDisclosureGate", "; ".join(problems[:8]))
        return
    _set_check(
        report,
        "longformReleaseDisclosureGate",
        "pass",
        f"AI disclosure decision={decision}, contentCredentialsStatus={c2pa_status}, inauthentic risk reviewed.",
    )


def _check_source_continuity(report: dict[str, Any], packet: dict[str, Any]) -> None:
    source = _source_review(packet)
    ratio = _number(source.get("chapterContinuityPassRatio") or source.get("adjacentContinuityPassRatio"))
    unresolved = _count(source.get("unresolvedSourceDefects") or source.get("unresolvedDefects"))
    accepted_chapter_count = _number(source.get("acceptedChapterCount") or source.get("chaptersWithAcceptedSources"))
    chapters = len(_chapters(packet))
    problems: list[str] = []
    if ratio is None or ratio < 0.85:
        problems.append("source continuity pass ratio must be >= 0.85")
    if source.get("primarySubjectIdentityDrift") is True:
        problems.append("primary subject identity drift is unresolved")
    if source.get("primarySubjectScaleJump") is True:
        problems.append("primary subject scale jump is unresolved")
    if source.get("unexplainedCameraWorldJump") is True:
        problems.append("unexplained camera/world jump is unresolved")
    if unresolved > 0:
        problems.append("unresolved source defects must be 0")
    if accepted_chapter_count is None or accepted_chapter_count < chapters:
        problems.append("accepted source coverage must cover every chapter")
    if problems:
        _fail(report, "longformReleaseSourceContinuityGate", "; ".join(problems))
        return
    _set_check(report, "longformReleaseSourceContinuityGate", "pass", "source continuity covers every chapter without unresolved drift.")


def _check_script_tts_caption(report: dict[str, Any], packet: dict[str, Any]) -> None:
    plan = _script_tts_caption_plan(packet)
    voice = _voice_plan(packet, plan)
    pace = _number(voice.get("targetWpm") or voice.get("paceWpm") or plan.get("targetWpm"))
    drift = _number(plan.get("maxCaptionTtsDriftSec") or _nested(plan, "captionTtsSync", "maxDriftSec"))
    problems: list[str] = []
    if not _status_pass(plan.get("languageReviewStatus") or plan.get("copyQualityStatus") or plan.get("status")):
        problems.append("Korean script/copy review must be pass")
    if not _text(voice.get("provider")) or not _text(voice.get("voiceId") or voice.get("voice")):
        problems.append("voice provider and voice id are required")
    if pace is None or pace < 115 or pace > 170:
        problems.append("longform TTS pace must stay between 115 and 170 WPM")
    if drift is None or drift > 0.30:
        problems.append("caption/TTS drift must be <= 0.30 seconds")
    if plan.get("noDuplicateCaptionTts") is not True:
        problems.append("captions must not duplicate TTS")
    if plan.get("captionExplainsMissingVisual") is True:
        problems.append("captions cannot explain visuals that sources do not show")
    if plan.get("safeZoneReviewed") is not True:
        problems.append("caption safe zone review is required")
    if problems:
        _fail(report, "longformReleaseScriptTtsCaptionGate", "; ".join(problems))
        return
    _set_check(report, "longformReleaseScriptTtsCaptionGate", "pass", "Korean copy, TTS, captions, and timing are release-ready.")


def _check_editorial(report: dict[str, Any], packet: dict[str, Any]) -> None:
    edit = _editorial_review(packet)
    cut_ratio = _number(edit.get("motivatedCutPassRatio") or edit.get("cutIntentPassRatio"))
    problems: list[str] = []
    if edit.get("directedEdit") is not True and edit.get("shotIntentReviewed") is not True:
        problems.append("directed edit or shot-intent review is required")
    if cut_ratio is None or cut_ratio < 0.85:
        problems.append("motivated cut pass ratio must be >= 0.85")
    if edit.get("layoutSafeZoneReviewed") is not True:
        problems.append("layout/HUD safe-zone review is required")
    if edit.get("noUnboundEffectCues") is not True:
        problems.append("effect/SFX cues must be source-bound")
    if edit.get("noHudComparisonReviewed") is not True:
        problems.append("no-HUD or baseline comparison review is required")
    if edit.get("unresolvedEditorialIssues"):
        problems.append("unresolved editorial issues must be empty")
    if problems:
        _fail(report, "longformReleaseEditorialGate", "; ".join(problems))
        return
    _set_check(report, "longformReleaseEditorialGate", "pass", "edit direction, cuts, layout, and source-bound cues are release-ready.")


def _check_audio(report: dict[str, Any], packet: dict[str, Any]) -> None:
    audio = _audio_review(packet)
    peak = _number(audio.get("maxPeakDb") or audio.get("peakDb"))
    mean = _number(audio.get("meanDb") or audio.get("integratedLufs"))
    problems: list[str] = []
    if audio.get("audioStreamExists") is not True:
        problems.append("final candidate needs an audio stream")
    if audio.get("narrationDuckingEnabled") is not True and audio.get("duckingEnabled") is not True:
        problems.append("narration ducking must be enabled")
    if audio.get("chapterAudioBedsCovered") is not True:
        problems.append("chapter audio beds must cover every chapter")
    if audio.get("everyCueBoundToVisibleEvent") is not True:
        problems.append("audio cues must be bound to visible events")
    if peak is None or peak > -1.0:
        problems.append("audio peak must be measured and stay <= -1.0 dB")
    if mean is None or mean < -32.0 or mean > -12.0:
        problems.append("audio mean/integrated loudness must be measured in a usable range")
    if problems:
        _fail(report, "longformReleaseAudioGate", "; ".join(problems))
        return
    _set_check(report, "longformReleaseAudioGate", "pass", "audio stream, BGM ducking, beds, cues, and loudness are release-ready.")


def _check_full_watch(report: dict[str, Any], packet: dict[str, Any]) -> None:
    review = _full_watch_review(packet)
    duration = _number(review.get("durationSec") or review.get("watchedDurationSec"))
    chapter_ids = {_chapter_id(chapter, index) for index, chapter in enumerate(_chapters(packet))}
    reviewed_ids = _reviewed_chapter_ids(review)
    critical = _count(review.get("unresolvedCriticalIssues"))
    major = _count(review.get("unresolvedMajorIssues"))
    density = _number(review.get("defectDensityPerMinute"))
    problems: list[str] = []
    if review.get("completed") is not True:
        problems.append("full-watch review completed=true is required")
    if duration is None or duration < LONGFORM_MIN_DURATION_SEC:
        problems.append("full-watch duration must cover the longform timeline")
    if not _text(review.get("reviewerRole") or review.get("reviewer") or review.get("humanReviewNote")):
        problems.append("full-watch review needs reviewerRole or humanReviewNote")
    if critical > 0 or major > 0:
        problems.append("unresolved critical/major full-watch issues must be 0")
    if density is None or density > 0.70:
        problems.append("full-watch defect density must be <= 0.70 per minute")
    if chapter_ids and not chapter_ids.issubset(reviewed_ids):
        problems.append("full-watch chapter issue log must cover every chapter")
    if review.get("retentionDipMitigationsReviewed") is not True:
        problems.append("retention dip mitigations must be reviewed")
    if problems:
        _fail(report, "longformReleaseFullWatchGate", "; ".join(problems))
        return
    _set_check(report, "longformReleaseFullWatchGate", "pass", "full-watch review covers the timeline with no unresolved critical/major issues.")


def _check_score(report: dict[str, Any], packet: dict[str, Any], computed_score: int) -> None:
    declared = _declared_score(packet)
    if declared is not None and abs(declared - computed_score) > 0.01:
        _fail(report, "longformReleaseScoreGate", f"declared score {declared:g} does not match computed score {computed_score:g}")
        return
    if computed_score < MINIMUM_RELEASE_SCORE:
        _fail(report, "longformReleaseScoreGate", f"computedScore={computed_score:g} is below minimum {MINIMUM_RELEASE_SCORE}")
        return
    _set_check(report, "longformReleaseScoreGate", "pass", f"computedScore={computed_score:g} meets minimum {MINIMUM_RELEASE_SCORE}.")


def _score_inputs(packet: dict[str, Any]) -> dict[str, int]:
    chapters = _chapters(packet)
    story = _story_package(packet)
    rights_items = _source_right_items(packet)
    source = _source_review(packet)
    script = _script_tts_caption_plan(packet)
    voice = _voice_plan(packet, script)
    edit = _editorial_review(packet)
    audio = _audio_review(packet)
    full_watch = _full_watch_review(packet)
    disclosure = _disclosure_review(packet)
    risk = _inauthentic_risk_review(disclosure, packet)
    return {
        "storyPackage": _score_story_package(packet, story, chapters),
        "evidenceRightsProviderSafety": _score_rights(rights_items),
        "publishDisclosureSafety": _score_disclosure(disclosure, risk),
        "sourceVisualContinuity": _score_source_continuity(source, len(chapters)),
        "scriptTtsCaptionSync": _score_script_tts_caption(script, voice),
        "editorialDirectionLayout": _score_editorial(edit),
        "audioBgmSfxMix": _score_audio(audio),
        "fullWatchDefectControl": _score_full_watch(full_watch, chapters),
    }


def _score_story_package(packet: dict[str, Any], story: dict[str, Any], chapters: list[dict[str, Any]]) -> int:
    score = 0
    segment_count = sum(len(_segments(chapter)) for chapter in chapters)
    if _duration_sec(packet) is not None and LONGFORM_MIN_DURATION_SEC <= _duration_sec(packet) <= LONGFORM_MAX_DURATION_SEC:
        score += 3
    if len(chapters) >= 6 and segment_count >= 18:
        score += 3
    if story.get("firstTenSecondExpectationMet") is True:
        score += 3
    if story.get("titleThumbnailExpectationMet") is True:
        score += 3
    if story.get("payoffPromiseResolved") is True:
        score += 3
    return min(score, LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["storyPackage"])


def _score_rights(items: list[dict[str, Any]]) -> int:
    if not items:
        return 0
    blocked = 0
    dreamina_unapproved = 0
    for item in items:
        provider = _text(item.get("provider") or item.get("sourceProvider") or item.get("model")).lower()
        rights = _text(item.get("rightsStatus") or item.get("rights") or item.get("license")).lower()
        explicit_commercial = item.get("commercialUseAllowed") is True
        if rights in RIGHTS_BLOCK_STATUSES:
            blocked += 1
        elif rights in RIGHTS_AMBIGUOUS_STATUSES and not explicit_commercial:
            blocked += 1
        elif rights not in RIGHTS_OK_STATUSES and not explicit_commercial:
            blocked += 1
        if any(token in provider for token in ("dreamina", "seedance")) and not explicit_commercial:
            dreamina_unapproved += 1
    if blocked or dreamina_unapproved:
        return 5
    return LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["evidenceRightsProviderSafety"]


def _score_disclosure(disclosure: dict[str, Any], risk: dict[str, Any]) -> int:
    score = 0
    decision = _text(
        disclosure.get("aiUseDecision")
        or disclosure.get("youtubeAiUseDecision")
        or disclosure.get("aiUse")
    ).lower()
    c2pa_status = _text(
        disclosure.get("contentCredentialsStatus")
        or disclosure.get("c2paStatus")
        or disclosure.get("contentCredentials")
    ).lower()
    if decision in AI_USE_DECISIONS:
        score += 2
    if not _disclosure_required(disclosure) or disclosure.get("youtubeAiUseSelected") is True:
        score += 2
    if _text(disclosure.get("disclosureStatement") or disclosure.get("operatorDisclosureNote")):
        score += 1
    if c2pa_status in CONTENT_CREDENTIALS_STATUSES:
        score += 1
    if disclosure.get("viewerMisleadRiskReviewed") is True and disclosure.get("inaccurateAuthenticityClaim") is not True:
        score += 1
    if risk.get("massProducedTemplate") is not True and risk.get("metadataTruthful") is True:
        score += 1
    if risk.get("originalInsightAdded") is True or risk.get("substantiveOriginalCommentary") is True:
        score += 1
    if risk.get("substantiveVariation") is True or risk.get("reusedContentTransformative") is True:
        score += 1
    return min(score, LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["publishDisclosureSafety"])


def _score_source_continuity(source: dict[str, Any], chapter_count: int) -> int:
    score = 0
    ratio = _number(source.get("chapterContinuityPassRatio") or source.get("adjacentContinuityPassRatio"))
    if ratio is not None:
        score += min(6, max(0, round(ratio * 6)))
    if source.get("primarySubjectIdentityDrift") is not True:
        score += 4
    if source.get("primarySubjectScaleJump") is not True:
        score += 4
    if _count(source.get("unresolvedSourceDefects") or source.get("unresolvedDefects")) == 0:
        score += 3
    accepted = _number(source.get("acceptedChapterCount") or source.get("chaptersWithAcceptedSources"))
    if chapter_count and accepted is not None:
        score += min(3, max(0, round((accepted / chapter_count) * 3)))
    return min(score, LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["sourceVisualContinuity"])


def _score_script_tts_caption(script: dict[str, Any], voice: dict[str, Any]) -> int:
    score = 0
    if _status_pass(script.get("languageReviewStatus") or script.get("copyQualityStatus") or script.get("status")):
        score += 4
    if _text(voice.get("provider")) and _text(voice.get("voiceId") or voice.get("voice")):
        score += 2
    pace = _number(voice.get("targetWpm") or voice.get("paceWpm") or script.get("targetWpm"))
    if pace is not None and 115 <= pace <= 170:
        score += 1
    drift = _number(script.get("maxCaptionTtsDriftSec") or _nested(script, "captionTtsSync", "maxDriftSec"))
    if drift is not None and drift <= 0.30:
        score += 3
    if script.get("noDuplicateCaptionTts") is True:
        score += 3
    if script.get("safeZoneReviewed") is True and script.get("captionExplainsMissingVisual") is not True:
        score += 2
    return min(score, LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["scriptTtsCaptionSync"])


def _score_editorial(edit: dict[str, Any]) -> int:
    score = 0
    if edit.get("directedEdit") is True or edit.get("shotIntentReviewed") is True:
        score += 3
    ratio = _number(edit.get("motivatedCutPassRatio") or edit.get("cutIntentPassRatio"))
    if ratio is not None:
        score += min(4, max(0, round(ratio * 4)))
    if edit.get("layoutSafeZoneReviewed") is True:
        score += 2
    if edit.get("noUnboundEffectCues") is True:
        score += 3
    if edit.get("noHudComparisonReviewed") is True:
        score += 3
    return min(score, LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["editorialDirectionLayout"])


def _score_audio(audio: dict[str, Any]) -> int:
    score = 0
    if audio.get("audioStreamExists") is True:
        score += 2
    if audio.get("narrationDuckingEnabled") is True or audio.get("duckingEnabled") is True:
        score += 2
    if audio.get("chapterAudioBedsCovered") is True:
        score += 2
    if audio.get("everyCueBoundToVisibleEvent") is True:
        score += 2
    peak = _number(audio.get("maxPeakDb") or audio.get("peakDb"))
    mean = _number(audio.get("meanDb") or audio.get("integratedLufs"))
    if peak is not None and peak <= -1.0 and mean is not None and -32.0 <= mean <= -12.0:
        score += 2
    return min(score, LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["audioBgmSfxMix"])


def _score_full_watch(review: dict[str, Any], chapters: list[dict[str, Any]]) -> int:
    score = 0
    if review.get("completed") is True:
        score += 2
    duration = _number(review.get("durationSec") or review.get("watchedDurationSec"))
    if duration is not None and duration >= LONGFORM_MIN_DURATION_SEC:
        score += 2
    if _count(review.get("unresolvedCriticalIssues")) == 0 and _count(review.get("unresolvedMajorIssues")) == 0:
        score += 3
    chapter_ids = {_chapter_id(chapter, index) for index, chapter in enumerate(chapters)}
    if chapter_ids and chapter_ids.issubset(_reviewed_chapter_ids(review)):
        score += 1
    density = _number(review.get("defectDensityPerMinute"))
    if density is not None and density <= 0.70:
        score += 1
    if _text(review.get("reviewerRole") or review.get("reviewer") or review.get("humanReviewNote")):
        score += 1
    return min(score, LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS["fullWatchDefectControl"])


def _chapters(packet: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        packet.get("chapters"),
        _nested(packet, "outline", "chapters"),
        _nested(packet, "longformOutline", "chapters"),
        _nested(packet, "productionModePacket", "chapters"),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _segments(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("segments", "beats", "sections"):
        value = chapter.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _duration_sec(packet: dict[str, Any]) -> float | None:
    for key in ("durationSec", "duration_sec", "totalDurationSec", "targetDurationSec"):
        value = _number(packet.get(key))
        if value is not None:
            return value
    return None


def _story_package(packet: dict[str, Any]) -> dict[str, Any]:
    for key in ("storyPackageReview", "packagingReview", "releasePackagingReview"):
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    plan = _nested(packet, "powerUserProductionPlan", "packagingPlan")
    return plan if isinstance(plan, dict) else {}


def _source_review(packet: dict[str, Any]) -> dict[str, Any]:
    for key in ("sourceContinuityReview", "sourceReviewImport", "sourceReview", "sourceQuality"):
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _script_tts_caption_plan(packet: dict[str, Any]) -> dict[str, Any]:
    for key in ("scriptTtsCaptionReview", "scriptTtsPlan", "copyTtsCaptionReview", "ttsCaptionReview"):
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _voice_plan(packet: dict[str, Any], script_plan: dict[str, Any]) -> dict[str, Any]:
    candidates = (
        script_plan.get("voicePlan"),
        packet.get("voicePlan"),
        _nested(packet, "productionModePacket", "voicePlan"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {
        "provider": script_plan.get("voiceProvider"),
        "voiceId": script_plan.get("voiceId"),
        "targetWpm": script_plan.get("targetWpm"),
    }


def _editorial_review(packet: dict[str, Any]) -> dict[str, Any]:
    for key in ("editorialReleaseReview", "editorialReview", "postEditReview", "roughCutReview"):
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _audio_review(packet: dict[str, Any]) -> dict[str, Any]:
    for key in ("audioReleaseReview", "audioReview", "mixReview", "audioPlanReview"):
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _full_watch_review(packet: dict[str, Any]) -> dict[str, Any]:
    for key in ("fullWatchReview", "finalFullWatchReview", "releaseFullWatchReview"):
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _disclosure_review(packet: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "publishDisclosureReview",
        "aiDisclosureReview",
        "platformDisclosureReview",
        "youtubeDisclosureReview",
        "uploadDisclosureReview",
    ):
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _inauthentic_risk_review(disclosure: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    candidates = (
        disclosure.get("inauthenticRiskReview"),
        packet.get("inauthenticRiskReview"),
        packet.get("monetizationOriginalityReview"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _disclosure_required(disclosure: dict[str, Any]) -> bool:
    for key in DISCLOSURE_REQUIRED_SIGNALS:
        if disclosure.get(key) is True:
            return True
    if disclosure.get("aiUseDisclosureRequired") is True:
        return True
    if disclosure.get("disclosureRequired") is True:
        return True
    return False


def _source_right_items(packet: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("sources", "sourceAssets", "acceptedSources", "evidence", "evidenceItems"):
        value = packet.get(key)
        if isinstance(value, list):
            items.extend([item for item in value if isinstance(item, dict)])
    for key in ("sourceReviewImport", "sourceReview", "sourceQuality"):
        value = packet.get(key)
        if isinstance(value, dict):
            for nested_key in ("acceptedSources", "sources", "sourceAssets"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    items.extend([item for item in nested if isinstance(item, dict)])
    for chapter in _chapters(packet):
        for key in ("evidence", "evidenceItems", "sources"):
            value = chapter.get(key)
            if isinstance(value, list):
                items.extend([item for item in value if isinstance(item, dict)])
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        marker = _item_label(item) + "|" + _text(item.get("rightsStatus") or item.get("rights") or item.get("license"))
        if marker not in seen:
            seen.add(marker)
            deduped.append(item)
    return deduped


def _reviewed_chapter_ids(review: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("reviewedChapterIds", "chaptersReviewed"):
        raw = review.get(key)
        if isinstance(raw, list):
            values.update(_text(item) for item in raw if _text(item))
    log = review.get("chapterIssueLog")
    if isinstance(log, list):
        for item in log:
            if isinstance(item, dict):
                chapter_id = _text(item.get("chapterId") or item.get("id"))
                if chapter_id:
                    values.add(chapter_id)
    return values


def _chapter_id(chapter: dict[str, Any], index: int) -> str:
    return _text(chapter.get("chapterId") or chapter.get("id") or f"chapter-{index + 1:02d}")


def _declared_score(packet: dict[str, Any]) -> float | None:
    candidates = (
        packet.get("computedScore"),
        packet.get("declaredScore"),
        _nested(packet, "releaseScoreEvidence", "computedScore"),
        _nested(packet, "minimumReleaseScore", "computedScore"),
    )
    for candidate in candidates:
        value = _number(candidate)
        if value is not None:
            return value
    return None


def _item_label(item: dict[str, Any]) -> str:
    return _text(
        item.get("sourceId")
        or item.get("assetId")
        or item.get("evidenceId")
        or item.get("id")
        or item.get("url")
        or item.get("sourceUrl")
        or "source-item"
    )


def _status_pass(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in PASS_STATUSES


def _count(value: Any) -> int:
    if value is None or value is False:
        return 0
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return 0 if not value.strip() else 1
    return 1


def _nested(packet: dict[str, Any], key: str, nested_key: str) -> Any:
    value = packet.get(key)
    if isinstance(value, dict):
        return value.get(nested_key)
    return None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _set_check(report: dict[str, Any], key: str, status: str, detail: str) -> None:
    report["checks"][key] = {"status": status, "detail": detail}


def _fail(report: dict[str, Any], key: str, detail: str) -> None:
    if key not in report["failedChecks"]:
        report["failedChecks"].append(key)
    _set_check(report, key, "fail", detail)
