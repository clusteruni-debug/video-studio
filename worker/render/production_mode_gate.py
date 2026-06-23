"""Production-mode gate for shortform and longform planning contracts.

The gate is intentionally independent from FFmpeg. It validates whether a
production packet or source-prompt bible is shaped for the intended format
before source generation or render work starts.
"""

from __future__ import annotations

from typing import Any


FORMAT_PROFILE_GATE_KEYS = ("formatProfileGate",)

PROVIDER_ROLE_MATRIX_GATE_KEYS = (
    "providerRoleMatrixGate",
    "grokPrimaryMotionGate",
    "geminiReferenceGate",
    "geminiFallbackMotionGate",
)

LONGFORM_PRODUCTION_GATE_KEYS = (
    "longformOutlineGate",
    "chapterContinuityGate",
    "evidenceDensityGate",
    "sourceRightsCitationGate",
    "longformVoiceConsistencyGate",
    "longformEditRhythmGate",
    "chapterAudioBedGate",
    "fullWatchReviewGate",
)

LONGFORM_STORYBOARD_GATE_KEYS = (
    "longformStoryboardGate",
    "chapterMarkerGate",
    "retentionPlanGate",
    "storyboardBeatCoverageGate",
    "evidenceVisualBindingGate",
    "visualContinuityBibleGate",
    "webReferenceLedgerGate",
)

LONGFORM_POWER_USER_GATE_KEYS = (
    "packagingPremiseGate",
    "productionFeasibilityGate",
    "roughCutRetentionMapGate",
    "creatorFeedbackLoopGate",
    "derivativeClipPlanGate",
    "powerUserCaseLedgerGate",
)

FORMAT_PROFILES: dict[str, dict[str, Any]] = {
    "shortform_vertical": {
        "label": "Shortform vertical",
        "durationRangeSec": [10, 90],
        "primaryUnit": "scene",
        "captionMode": "shortform-safe",
        "aspectRatio": "9:16",
    },
    "longform_10m": {
        "label": "Longform 10 minute",
        "durationRangeSec": [480, 900],
        "primaryUnit": "chapter",
        "captionMode": "chapter-lower-third",
        "aspectRatio": "16:9-or-9:16-derived",
        "minChapters": 6,
        "minSegments": 18,
    },
}

LONGFORM_TEMPLATE_TYPES = {
    "longform_deep_dive",
    "interview_documentary",
    "live_recap",
    "news_explainer",
    "documentary_explainer",
}

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

SHORTS_CAPTION_MODES = {
    "shorts-center",
    "shorts-karaoke",
    "giant-center-caption",
    "tiktok-style-center",
}


def evaluate_production_mode_gate(packet: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a production packet or prompt bible against its format profile."""

    report: dict[str, Any] = {
        "schema": "video-studio.production-mode-gate.v1",
        "status": "pass",
        "renderAllowed": True,
        "formatProfile": _format_profile(packet),
        "failedChecks": [],
        "checks": {},
    }

    profile = report["formatProfile"]
    if profile not in FORMAT_PROFILES:
        _fail(
            report,
            "formatProfileGate",
            "formatProfile must be one of: " + ", ".join(sorted(FORMAT_PROFILES)),
        )
    else:
        _set_check(
            report,
            "formatProfileGate",
            "pass",
            f"formatProfile={profile} uses {FORMAT_PROFILES[profile]['primaryUnit']} units.",
        )

    _merge_provider_role_report(report, evaluate_provider_role_matrix(_provider_matrix(packet)))

    if profile == "longform_10m":
        _evaluate_longform_10m(packet, report)
        _evaluate_longform_storyboard(packet, report)
        _evaluate_longform_power_user(packet, report)
    else:
        for key in LONGFORM_PRODUCTION_GATE_KEYS:
            _set_check(report, key, "skip", "longform_10m gate is not required for this formatProfile.")
        for key in LONGFORM_STORYBOARD_GATE_KEYS:
            _set_check(report, key, "skip", "longform storyboard gate is not required for this formatProfile.")
        for key in LONGFORM_POWER_USER_GATE_KEYS:
            _set_check(report, key, "skip", "longform power-user gate is not required for this formatProfile.")

    if report["failedChecks"]:
        report["status"] = "fail"
        report["renderAllowed"] = False

    return report


def evaluate_provider_role_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    """Validate Grok/Gemini provider role separation before generation."""

    report: dict[str, Any] = {
        "schema": "video-studio.provider-role-matrix-gate.v1",
        "status": "pass",
        "failedChecks": [],
        "checks": {},
    }

    roles = _normalize_roles(matrix)
    if not roles:
        _fail(report, "providerRoleMatrixGate", "providerRoleMatrix is required.")
    else:
        required_roles = {"primaryMotion", "referenceStill", "fallbackMotion"}
        missing = sorted(required_roles - set(roles))
        if missing:
            _fail(report, "providerRoleMatrixGate", "providerRoleMatrix missing roles: " + ", ".join(missing))
        else:
            _set_check(report, "providerRoleMatrixGate", "pass", "provider roles are explicit.")

    _check_grok_primary_motion(report, roles)
    _check_gemini_reference(report, roles)
    _check_gemini_fallback_motion(report, roles)

    if report["failedChecks"]:
        report["status"] = "fail"
    return report


def _evaluate_longform_10m(packet: dict[str, Any], report: dict[str, Any]) -> None:
    chapters = _chapters(packet)
    chapter_count = len(chapters)
    segment_count = sum(len(_segments(chapter)) for chapter in chapters)

    if chapter_count < FORMAT_PROFILES["longform_10m"]["minChapters"] or segment_count < FORMAT_PROFILES["longform_10m"]["minSegments"]:
        _fail(
            report,
            "longformOutlineGate",
            "longform_10m needs at least 6 chapters and 18 segments.",
        )
    elif any(not _text(chapter.get("title")) or not _text(chapter.get("claim")) for chapter in chapters):
        _fail(report, "longformOutlineGate", "each longform chapter needs title and claim.")
    else:
        _set_check(report, "longformOutlineGate", "pass", f"{chapter_count} chapters and {segment_count} segments.")

    _check_chapter_continuity(report, packet, chapters)
    _check_evidence_density(report, chapters)
    _check_source_rights_citations(report, chapters)
    _check_voice_consistency(report, packet)
    _check_edit_rhythm(report, packet, segment_count)
    _check_chapter_audio_bed(report, packet, chapters)
    _check_full_watch_review(report, packet)


def _evaluate_longform_storyboard(packet: dict[str, Any], report: dict[str, Any]) -> None:
    storyboard = _storyboard(packet)
    beats = _storyboard_beats(packet)
    chapters = _chapters(packet)

    _check_longform_storyboard(report, storyboard, beats)
    _check_chapter_markers(report, packet, chapters)
    _check_retention_plan(report, storyboard)
    _check_storyboard_beat_coverage(report, beats, chapters)
    _check_evidence_visual_binding(report, beats, chapters)
    _check_visual_continuity_bible(report, storyboard)
    _check_web_reference_ledger(report, packet)


def _evaluate_longform_power_user(packet: dict[str, Any], report: dict[str, Any]) -> None:
    plan = _power_user_production_plan(packet)
    beats = _storyboard_beats(packet)

    _check_packaging_premise(report, plan)
    _check_production_feasibility(report, plan)
    _check_rough_cut_retention_map(report, plan, beats)
    _check_creator_feedback_loop(report, plan)
    _check_derivative_clip_plan(report, plan, beats)
    _check_power_user_case_ledger(report, packet)


def _check_chapter_continuity(report: dict[str, Any], packet: dict[str, Any], chapters: list[dict[str, Any]]) -> None:
    chapter_ids = [_chapter_id(chapter, index) for index, chapter in enumerate(chapters)]
    if len(chapter_ids) != len(set(chapter_ids)):
        _fail(report, "chapterContinuityGate", "chapter ids must be unique.")
        return

    continuity = packet.get("chapterContinuityPlan") if isinstance(packet.get("chapterContinuityPlan"), dict) else {}
    bridges = continuity.get("bridges") if isinstance(continuity.get("bridges"), list) else []
    per_chapter_bridges = [
        chapter
        for index, chapter in enumerate(chapters)
        if index > 0 and _text(chapter.get("bridgeFromPrevious"))
    ]
    if len(chapters) > 1 and len(bridges) < len(chapters) - 1 and len(per_chapter_bridges) < len(chapters) - 1:
        _fail(report, "chapterContinuityGate", "longform chapters need bridge continuity between chapters.")
        return

    _set_check(report, "chapterContinuityGate", "pass", "chapter ids and bridge continuity are present.")


def _check_evidence_density(report: dict[str, Any], chapters: list[dict[str, Any]]) -> None:
    evidence_counts = [len(_evidence_items(chapter)) for chapter in chapters]
    if not evidence_counts or any(count < 1 for count in evidence_counts):
        _fail(report, "evidenceDensityGate", "each longform chapter needs at least one evidence item.")
        return
    _set_check(report, "evidenceDensityGate", "pass", f"{sum(evidence_counts)} evidence items across chapters.")


def _check_source_rights_citations(report: dict[str, Any], chapters: list[dict[str, Any]]) -> None:
    problems: list[str] = []
    for chapter in chapters:
        for item in _evidence_items(chapter):
            citation = _text(item.get("citation") or item.get("sourceUrl") or item.get("url"))
            rights = _text(item.get("rightsStatus") or item.get("rights") or item.get("license")).lower()
            explicit_commercial = item.get("commercialUseAllowed") is True
            if not citation:
                problems.append(f"{_chapter_id(chapter, 0)} missing citation")
            if not rights:
                problems.append(f"{_chapter_id(chapter, 0)} rights=missing")
            elif rights in RIGHTS_BLOCK_STATUSES:
                problems.append(f"{_chapter_id(chapter, 0)} rights={rights} is blocked for release")
            elif rights in RIGHTS_AMBIGUOUS_STATUSES and not explicit_commercial:
                problems.append(f"{_chapter_id(chapter, 0)} rights={rights} requires explicit commercialUseAllowed=true")
            elif rights not in RIGHTS_OK_STATUSES and not explicit_commercial:
                problems.append(f"{_chapter_id(chapter, 0)} rights={rights or 'missing'}")
    if problems:
        _fail(report, "sourceRightsCitationGate", "; ".join(problems[:4]))
        return
    _set_check(report, "sourceRightsCitationGate", "pass", "all evidence items have citation and approved rights status.")


def _check_voice_consistency(report: dict[str, Any], packet: dict[str, Any]) -> None:
    voice_plan = packet.get("voicePlan") if isinstance(packet.get("voicePlan"), dict) else {}
    provider = _text(voice_plan.get("provider"))
    voice_id = _text(voice_plan.get("voiceId") or voice_plan.get("voice"))
    pace = _number(voice_plan.get("targetWpm") or voice_plan.get("paceWpm"))
    if not provider or not voice_id:
        _fail(report, "longformVoiceConsistencyGate", "voicePlan.provider and voicePlan.voiceId are required.")
        return
    if pace is not None and not 115 <= pace <= 170:
        _fail(report, "longformVoiceConsistencyGate", "longform narration targetWpm must stay between 115 and 170.")
        return

    chapter_voice_plans = packet.get("chapterVoicePlans")
    if isinstance(chapter_voice_plans, list):
        mismatches = [
            item
            for item in chapter_voice_plans
            if isinstance(item, dict)
            and (
                _text(item.get("provider")) not in {"", provider}
                or _text(item.get("voiceId") or item.get("voice")) not in {"", voice_id}
            )
        ]
        if mismatches:
            _fail(report, "longformVoiceConsistencyGate", "chapter voice plans must keep one provider and voice.")
            return

    _set_check(report, "longformVoiceConsistencyGate", "pass", f"voice={provider}/{voice_id}.")


def _check_edit_rhythm(report: dict[str, Any], packet: dict[str, Any], segment_count: int) -> None:
    edit_plan = packet.get("editPlan") if isinstance(packet.get("editPlan"), dict) else {}
    caption_mode = _text(edit_plan.get("captionMode") or packet.get("captionMode")).lower()
    if caption_mode in SHORTS_CAPTION_MODES:
        _fail(report, "longformEditRhythmGate", "longform_10m must not use Shorts-style center caption mode.")
        return
    max_static_hold = _number(edit_plan.get("maxStaticHoldSec"))
    if max_static_hold is None or max_static_hold > 14:
        _fail(report, "longformEditRhythmGate", "editPlan.maxStaticHoldSec must be <= 14 for longform.")
        return
    average_cut = _number(edit_plan.get("averageCutSec"))
    if average_cut is not None and not 5 <= average_cut <= 18:
        _fail(report, "longformEditRhythmGate", "editPlan.averageCutSec must stay between 5 and 18.")
        return
    if segment_count < FORMAT_PROFILES["longform_10m"]["minSegments"]:
        _fail(report, "longformEditRhythmGate", "longform edit rhythm needs at least 18 planned segments.")
        return
    _set_check(report, "longformEditRhythmGate", "pass", "longform edit rhythm avoids shortform caption pacing.")


def _check_chapter_audio_bed(report: dict[str, Any], packet: dict[str, Any], chapters: list[dict[str, Any]]) -> None:
    audio_plan = packet.get("audioPlan") if isinstance(packet.get("audioPlan"), dict) else {}
    chapter_beds = audio_plan.get("chapterBeds") if isinstance(audio_plan.get("chapterBeds"), list) else []
    ducking_enabled = audio_plan.get("duckingEnabled") is True or audio_plan.get("narrationDucking") is True
    if not ducking_enabled:
        _fail(report, "chapterAudioBedGate", "audioPlan must enable narration ducking.")
        return
    if len(chapter_beds) < len(chapters):
        _fail(report, "chapterAudioBedGate", "audioPlan.chapterBeds must cover every chapter.")
        return
    if any(not _text(item.get("bedId") or item.get("trackId")) for item in chapter_beds if isinstance(item, dict)):
        _fail(report, "chapterAudioBedGate", "each chapter bed needs bedId or trackId.")
        return
    _set_check(report, "chapterAudioBedGate", "pass", "chapter audio beds cover the outline.")


def _check_full_watch_review(report: dict[str, Any], packet: dict[str, Any]) -> None:
    if not _claims_final_ready(packet):
        _set_check(report, "fullWatchReviewGate", "skip", "full-watch review is required only for final readiness claims.")
        return

    review = packet.get("fullWatchReview") if isinstance(packet.get("fullWatchReview"), dict) else {}
    duration = _number(review.get("durationSec") or packet.get("durationSec"))
    if review.get("completed") is not True:
        _fail(report, "fullWatchReviewGate", "final longform readiness requires fullWatchReview.completed=true.")
        return
    if duration is None or duration < FORMAT_PROFILES["longform_10m"]["durationRangeSec"][0]:
        _fail(report, "fullWatchReviewGate", "fullWatchReview.durationSec must cover the longform timeline.")
        return
    if not _text(review.get("reviewer") or review.get("humanReviewNote")):
        _fail(report, "fullWatchReviewGate", "fullWatchReview needs reviewer or humanReviewNote.")
        return
    _set_check(report, "fullWatchReviewGate", "pass", "full longform watch review is present.")


def _check_longform_storyboard(report: dict[str, Any], storyboard: dict[str, Any], beats: list[dict[str, Any]]) -> None:
    if not storyboard:
        _fail(report, "longformStoryboardGate", "longform storyboard object is required before source generation.")
        return
    if not _text(storyboard.get("thesis") or storyboard.get("centralQuestion")):
        _fail(report, "longformStoryboardGate", "storyboard needs thesis or centralQuestion.")
        return
    if not _text(storyboard.get("viewerPromise")):
        _fail(report, "longformStoryboardGate", "storyboard.viewerPromise is required.")
        return
    if len(beats) < FORMAT_PROFILES["longform_10m"]["minSegments"]:
        _fail(report, "longformStoryboardGate", "storyboard needs at least 18 timed beats.")
        return
    _set_check(report, "longformStoryboardGate", "pass", f"{len(beats)} storyboard beats before generation.")


def _check_chapter_markers(
    report: dict[str, Any],
    packet: dict[str, Any],
    chapters: list[dict[str, Any]],
) -> None:
    markers = _chapter_markers(packet)
    if len(markers) < 3:
        _fail(report, "chapterMarkerGate", "longform storyboard needs at least three chapter markers.")
        return

    starts = [
        _number(marker["startSec"] if "startSec" in marker else marker.get("timestampSec"))
        for marker in markers
    ]
    if starts[0] != 0:
        _fail(report, "chapterMarkerGate", "first chapter marker must start at 0 seconds.")
        return
    if any(start is None for start in starts):
        _fail(report, "chapterMarkerGate", "every chapter marker needs startSec.")
        return
    if starts != sorted(starts):
        _fail(report, "chapterMarkerGate", "chapter markers must be in ascending order.")
        return
    if any(next_start - start < 10 for start, next_start in zip(starts, starts[1:])):
        _fail(report, "chapterMarkerGate", "chapter markers must be at least 10 seconds apart.")
        return

    chapter_ids = {_chapter_id(chapter, index) for index, chapter in enumerate(chapters)}
    missing_titles = [marker for marker in markers if not _text(marker.get("title"))]
    unknown_ids = [
        marker
        for marker in markers
        if _text(marker.get("chapterId")) and _text(marker.get("chapterId")) not in chapter_ids
    ]
    if missing_titles or unknown_ids:
        _fail(report, "chapterMarkerGate", "chapter markers need titles and known chapter ids when ids are provided.")
        return
    _set_check(report, "chapterMarkerGate", "pass", f"{len(markers)} valid chapter markers.")


def _check_retention_plan(report: dict[str, Any], storyboard: dict[str, Any]) -> None:
    retention = storyboard.get("retentionPlan") if isinstance(storyboard.get("retentionPlan"), dict) else {}
    required_fields = ("first30SecPromise", "titleThumbnailExpectation", "topMomentPreview")
    missing = [field for field in required_fields if not _text(retention.get(field))]
    dip_risks = retention.get("dipRiskMitigations")
    dip_risk_count = len(dip_risks) if isinstance(dip_risks, list) else 0
    if missing or dip_risk_count < 1:
        detail = "retentionPlan needs first30SecPromise, titleThumbnailExpectation, topMomentPreview, and dipRiskMitigations."
        _fail(report, "retentionPlanGate", detail)
        return
    _set_check(report, "retentionPlanGate", "pass", "first-30s, top moment, and dip-risk plan are present.")


def _check_storyboard_beat_coverage(
    report: dict[str, Any],
    beats: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
) -> None:
    required_fields = ("beatId", "chapterId", "startSec", "durationSec", "visualIntent", "providerRole")
    broken = []
    for beat in beats:
        missing = [field for field in required_fields if field not in beat or not _text(beat.get(field))]
        if not _text(beat.get("audioIntent") or beat.get("narrationIntent")):
            missing.append("audioIntent/narrationIntent")
        if missing:
            broken.append(f"{_text(beat.get('beatId')) or 'unnamed'} missing {', '.join(missing)}")
    chapter_ids = {_chapter_id(chapter, index) for index, chapter in enumerate(chapters)}
    covered_chapter_ids = {_text(beat.get("chapterId")) for beat in beats if _text(beat.get("chapterId"))}
    missing_chapters = sorted(chapter_ids - covered_chapter_ids)
    if broken or missing_chapters:
        details = broken[:2]
        if missing_chapters:
            details.append("missing chapter beats: " + ", ".join(missing_chapters[:4]))
        _fail(report, "storyboardBeatCoverageGate", "; ".join(details))
        return
    _set_check(report, "storyboardBeatCoverageGate", "pass", "storyboard beats cover all chapters with timing and intent.")


def _check_evidence_visual_binding(
    report: dict[str, Any],
    beats: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
) -> None:
    evidence_by_chapter: dict[str, set[str]] = {}
    for index, chapter in enumerate(chapters):
        chapter_id = _chapter_id(chapter, index)
        evidence_by_chapter[chapter_id] = {
            evidence_id
            for evidence_id in (_evidence_id(item) for item in _evidence_items(chapter))
            if evidence_id
        }

    if not evidence_by_chapter or any(not ids for ids in evidence_by_chapter.values()):
        _fail(report, "evidenceVisualBindingGate", "each chapter needs evidence ids before visual binding.")
        return

    bound_by_chapter: dict[str, set[str]] = {chapter_id: set() for chapter_id in evidence_by_chapter}
    unknown_refs: list[str] = []
    for beat in beats:
        chapter_id = _text(beat.get("chapterId"))
        ref = _text(beat.get("evidenceRef") or beat.get("evidenceId") or beat.get("sourceEvidenceId"))
        if not chapter_id or not ref:
            continue
        if chapter_id not in evidence_by_chapter or ref not in evidence_by_chapter[chapter_id]:
            unknown_refs.append(f"{_text(beat.get('beatId')) or chapter_id}->{ref}")
        else:
            bound_by_chapter[chapter_id].add(ref)

    missing = sorted(chapter_id for chapter_id, refs in bound_by_chapter.items() if not refs)
    if unknown_refs or missing:
        details = []
        if unknown_refs:
            details.append("unknown evidence refs: " + ", ".join(unknown_refs[:3]))
        if missing:
            details.append("chapters without evidence-bound beats: " + ", ".join(missing[:4]))
        _fail(report, "evidenceVisualBindingGate", "; ".join(details))
        return
    _set_check(report, "evidenceVisualBindingGate", "pass", "every chapter has evidence-bound visual beats.")


def _check_visual_continuity_bible(report: dict[str, Any], storyboard: dict[str, Any]) -> None:
    bible = storyboard.get("visualContinuityBible")
    if not isinstance(bible, dict):
        _fail(report, "visualContinuityBibleGate", "visualContinuityBible object is required for longform.")
        return
    required_fields = ("shotLanguage", "colorTreatment", "layoutRules")
    missing = [field for field in required_fields if not _text(bible.get(field))]
    style_rules = bible.get("styleRules")
    recurring_assets = bible.get("recurringAssets")
    if missing or not isinstance(style_rules, list) or not style_rules or not isinstance(recurring_assets, list) or not recurring_assets:
        detail = "visualContinuityBible needs shotLanguage, colorTreatment, layoutRules, styleRules, and recurringAssets."
        _fail(report, "visualContinuityBibleGate", detail)
        return
    _set_check(report, "visualContinuityBibleGate", "pass", "visual continuity bible is present.")


def _check_web_reference_ledger(report: dict[str, Any], packet: dict[str, Any]) -> None:
    ledger = _web_reference_ledger(packet)
    references = ledger.get("references") if isinstance(ledger.get("references"), list) else []
    if len(references) < 4:
        _fail(report, "webReferenceLedgerGate", "webReferenceLedger needs at least four durable references.")
        return

    missing_fields = []
    applied_gates: set[str] = set()
    source_types: set[str] = set()
    for index, item in enumerate(references, start=1):
        if not isinstance(item, dict):
            missing_fields.append(f"reference-{index} must be an object")
            continue
        required = ("title", "url", "sourceType", "takeaways", "appliedGateKeys")
        missing = [field for field in required if field not in item or not item.get(field)]
        if not _text(item.get("retrievedAt") or item.get("checkedAt") or item.get("lastVerified")):
            missing.append("retrievedAt/checkedAt")
        if missing:
            missing_fields.append(f"reference-{index} missing {', '.join(missing)}")
        source_types.add(_text(item.get("sourceType")))
        gates = item.get("appliedGateKeys") if isinstance(item.get("appliedGateKeys"), list) else []
        applied_gates.update(_text(gate) for gate in gates if _text(gate))

    required_gates = set(LONGFORM_STORYBOARD_GATE_KEYS) - {"webReferenceLedgerGate"}
    missing_gate_refs = sorted(required_gates - applied_gates)
    if (
        missing_fields
        or "official-platform" not in source_types
        or "research-paper" not in source_types
        or missing_gate_refs
    ):
        details = missing_fields[:2]
        if "official-platform" not in source_types:
            details.append("missing official-platform source")
        if "research-paper" not in source_types:
            details.append("missing research-paper source")
        if missing_gate_refs:
            details.append("missing gate reference basis: " + ", ".join(missing_gate_refs[:4]))
        _fail(report, "webReferenceLedgerGate", "; ".join(details))
        return
    _set_check(report, "webReferenceLedgerGate", "pass", f"{len(references)} references cover storyboard gates.")


def _check_packaging_premise(report: dict[str, Any], plan: dict[str, Any]) -> None:
    packaging = plan.get("packagingPlan") if isinstance(plan.get("packagingPlan"), dict) else {}
    title_options = _text_list(packaging.get("titleOptions"))
    thumbnail_briefs = _dict_list(packaging.get("thumbnailBriefs"))
    missing = [
        field
        for field in ("premise", "targetViewer", "firstTenSecondExpectation", "payoffPromise")
        if not _text(packaging.get(field))
    ]
    if missing or len(set(title_options)) < 3 or len(thumbnail_briefs) < 2:
        _fail(
            report,
            "packagingPremiseGate",
            "packagingPlan needs premise, targetViewer, firstTenSecondExpectation, payoffPromise, 3 title options, and 2 thumbnail briefs.",
        )
        return
    incomplete_thumbnails = [
        item
        for item in thumbnail_briefs
        if not _text(item.get("visualHook")) or not _text(item.get("contrastPoint") or item.get("subject"))
    ]
    if incomplete_thumbnails:
        _fail(report, "packagingPremiseGate", "thumbnail briefs need visualHook and contrastPoint or subject.")
        return
    _set_check(report, "packagingPremiseGate", "pass", "packaging premise, title options, and thumbnail briefs are present.")


def _check_production_feasibility(report: dict[str, Any], plan: dict[str, Any]) -> None:
    feasibility = plan.get("feasibilityPlan") if isinstance(plan.get("feasibilityPlan"), dict) else {}
    risks = _dict_list(feasibility.get("risks"))
    kill_criteria = _text_list(feasibility.get("killCriteria"))
    resource_plan = feasibility.get("resourcePlan") if isinstance(feasibility.get("resourcePlan"), dict) else {}
    missing_resource = [
        field
        for field in ("owner", "sourceBudget", "fallbackPath")
        if not _text(resource_plan.get(field))
    ]
    incomplete_risks = [
        item
        for item in risks
        if not _text(item.get("risk")) or not _text(item.get("mitigation")) or not _text(item.get("owner"))
    ]
    if len(risks) < 3 or len(kill_criteria) < 2 or missing_resource or incomplete_risks:
        _fail(
            report,
            "productionFeasibilityGate",
            "feasibilityPlan needs 3 owned risks, 2 killCriteria, and resourcePlan owner/sourceBudget/fallbackPath.",
        )
        return
    _set_check(report, "productionFeasibilityGate", "pass", "production feasibility has risks, kill criteria, and fallback resources.")


def _check_rough_cut_retention_map(
    report: dict[str, Any],
    plan: dict[str, Any],
    beats: list[dict[str, Any]],
) -> None:
    retention_map = _dict_list(plan.get("roughCutRetentionMap"))
    if len(retention_map) < 6:
        _fail(report, "roughCutRetentionMapGate", "roughCutRetentionMap needs at least six minute-level retention beats.")
        return

    starts = [_number(item.get("startSec") if "startSec" in item else item.get("minuteMarkSec")) for item in retention_map]
    if any(start is None for start in starts) or starts != sorted(starts) or starts[0] != 0:
        _fail(report, "roughCutRetentionMapGate", "roughCutRetentionMap startSec values must start at 0 and ascend.")
        return

    beat_ids = {_text(beat.get("beatId")) for beat in beats if _text(beat.get("beatId"))}
    broken = []
    for item in retention_map:
        if not _text(item.get("viewerQuestion")) or not _text(item.get("payoff") or item.get("reveal")):
            broken.append(_text(item.get("label")) or str(item.get("startSec")))
        beat_ref = _text(item.get("sourceBeatId") or item.get("beatId"))
        if beat_ids and beat_ref and beat_ref not in beat_ids:
            broken.append(f"unknown beat {beat_ref}")
    if broken:
        _fail(report, "roughCutRetentionMapGate", "retention map entries need viewerQuestion/payoff and valid beat refs: " + ", ".join(broken[:4]))
        return
    _set_check(report, "roughCutRetentionMapGate", "pass", f"{len(retention_map)} retention beats mapped to the rough cut.")


def _check_creator_feedback_loop(report: dict[str, Any], plan: dict[str, Any]) -> None:
    feedback = plan.get("feedbackLoop") if isinstance(plan.get("feedbackLoop"), dict) else {}
    passes = _dict_list(feedback.get("reviewPasses"))
    stages = {_text(item.get("stage")) for item in passes}
    required_stages = {"script", "roughCut", "final"}
    incomplete = [
        item
        for item in passes
        if not _text(item.get("reviewerRole")) or not _text(item.get("decisionRule"))
    ]
    if not required_stages.issubset(stages) or incomplete or not _text(feedback.get("iterationPolicy")):
        _fail(
            report,
            "creatorFeedbackLoopGate",
            "feedbackLoop needs script/roughCut/final reviewPasses with reviewerRole, decisionRule, and iterationPolicy.",
        )
        return
    _set_check(report, "creatorFeedbackLoopGate", "pass", "creator feedback loop covers script, rough cut, and final review.")


def _check_derivative_clip_plan(
    report: dict[str, Any],
    plan: dict[str, Any],
    beats: list[dict[str, Any]],
) -> None:
    clip_plan = plan.get("derivativeClipPlan") if isinstance(plan.get("derivativeClipPlan"), dict) else {}
    clips = _dict_list(clip_plan.get("clips"))
    if len(clips) < 3 or not _text(clip_plan.get("cadence")) or not _text(clip_plan.get("qualityControl")):
        _fail(report, "derivativeClipPlanGate", "derivativeClipPlan needs cadence, qualityControl, and at least three clips.")
        return

    beat_ids = {_text(beat.get("beatId")) for beat in beats if _text(beat.get("beatId"))}
    broken = []
    for clip in clips:
        missing = [
            field
            for field in ("clipId", "platform", "hook", "viewerPromise")
            if not _text(clip.get(field))
        ]
        source_ref = _text(clip.get("sourceBeatId") or clip.get("sourceChapterId"))
        if not source_ref:
            missing.append("sourceBeatId/sourceChapterId")
        if clip.get("contextPreserved") is not True and clip.get("noMisleadingContext") is not True:
            missing.append("contextPreserved/noMisleadingContext")
        if beat_ids and _text(clip.get("sourceBeatId")) and _text(clip.get("sourceBeatId")) not in beat_ids:
            missing.append("known sourceBeatId")
        if missing:
            broken.append(f"{_text(clip.get('clipId')) or 'unnamed'} missing {', '.join(missing)}")
    if broken:
        _fail(report, "derivativeClipPlanGate", "; ".join(broken[:3]))
        return
    _set_check(report, "derivativeClipPlanGate", "pass", f"{len(clips)} derivative clips preserve longform context.")


def _check_power_user_case_ledger(report: dict[str, Any], packet: dict[str, Any]) -> None:
    ledger = _power_user_case_ledger(packet)
    references = ledger.get("references") if isinstance(ledger.get("references"), list) else []
    if len(references) < 5:
        _fail(report, "powerUserCaseLedgerGate", "powerUserCaseLedger needs at least five creator/power-user references.")
        return

    missing_fields = []
    applied_gates: set[str] = set()
    source_types: set[str] = set()
    for index, item in enumerate(references, start=1):
        if not isinstance(item, dict):
            missing_fields.append(f"reference-{index} must be an object")
            continue
        required = ("title", "url", "sourceType", "takeaways", "appliedGateKeys")
        missing = [field for field in required if field not in item or not item.get(field)]
        if not _text(item.get("retrievedAt") or item.get("checkedAt") or item.get("lastVerified")):
            missing.append("retrievedAt/checkedAt")
        if missing:
            missing_fields.append(f"reference-{index} missing {', '.join(missing)}")
        source_types.add(_text(item.get("sourceType")))
        gates = item.get("appliedGateKeys") if isinstance(item.get("appliedGateKeys"), list) else []
        applied_gates.update(_text(gate) for gate in gates if _text(gate))

    case_sources = {"creator-case", "creator-interview", "industry-case", "industry-analysis"}
    required_gates = set(LONGFORM_POWER_USER_GATE_KEYS) - {"powerUserCaseLedgerGate"}
    missing_gate_refs = sorted(required_gates - applied_gates)
    if (
        missing_fields
        or not (source_types & case_sources)
        or "research-paper" not in source_types
        or missing_gate_refs
    ):
        details = missing_fields[:2]
        if not (source_types & case_sources):
            details.append("missing creator or industry case source")
        if "research-paper" not in source_types:
            details.append("missing research-paper source")
        if missing_gate_refs:
            details.append("missing gate reference basis: " + ", ".join(missing_gate_refs[:4]))
        _fail(report, "powerUserCaseLedgerGate", "; ".join(details))
        return
    _set_check(report, "powerUserCaseLedgerGate", "pass", f"{len(references)} creator/power-user references cover production gates.")


def _check_grok_primary_motion(report: dict[str, Any], roles: dict[str, list[dict[str, Any]]]) -> None:
    grok_roles = [
        role
        for role, entries in roles.items()
        for entry in entries
        if entry["provider"] == "grok-web-video"
    ]
    if any(role not in {"primaryMotion", "firstHookMotion", "motionTake"} for role in grok_roles):
        _fail(report, "grokPrimaryMotionGate", "grok-web-video may only serve motion roles.")
        return
    if not roles.get("primaryMotion"):
        _fail(report, "grokPrimaryMotionGate", "primaryMotion provider is required.")
        return
    _set_check(report, "grokPrimaryMotionGate", "pass", "Grok is constrained to motion-source roles.")


def _check_gemini_reference(report: dict[str, Any], roles: dict[str, list[dict[str, Any]]]) -> None:
    image_bad_roles = [
        role
        for role, entries in roles.items()
        for entry in entries
        if entry["provider"] == "gemini-web-image"
        and role not in {"referenceStill", "visualBible", "diagramStill"}
    ]
    if image_bad_roles:
        _fail(report, "geminiReferenceGate", "gemini-web-image must stay reference/diagram/still only.")
        return
    if not any(entry["provider"] == "gemini-web-image" for entry in roles.get("referenceStill", [])):
        _fail(report, "geminiReferenceGate", "referenceStill should explicitly name gemini-web-image or another still provider.")
        return
    _set_check(report, "geminiReferenceGate", "pass", "Gemini image is constrained to reference/still roles.")


def _check_gemini_fallback_motion(report: dict[str, Any], roles: dict[str, list[dict[str, Any]]]) -> None:
    video_entries = [
        (role, entry)
        for role, entries in roles.items()
        for entry in entries
        if entry["provider"] == "gemini-web-video"
    ]
    invalid_roles = [role for role, _ in video_entries if role not in {"fallbackMotion", "primaryMotion"}]
    if invalid_roles:
        _fail(report, "geminiFallbackMotionGate", "gemini-web-video may only serve fallbackMotion or explicit primaryMotion.")
        return
    fallback_entries = [entry for role, entry in video_entries if role == "fallbackMotion"]
    if fallback_entries and any(not _text(entry.get("reason") or entry.get("when")) for entry in fallback_entries):
        _fail(report, "geminiFallbackMotionGate", "gemini-web-video fallbackMotion needs reason or when.")
        return
    primary_entries = [entry for role, entry in video_entries if role == "primaryMotion"]
    if primary_entries and any(not _text(entry.get("overrideReason") or entry.get("reason")) for entry in primary_entries):
        _fail(report, "geminiFallbackMotionGate", "gemini-web-video primaryMotion needs overrideReason.")
        return
    _set_check(report, "geminiFallbackMotionGate", "pass", "Gemini video is fallback or explicitly justified primary motion.")


def _merge_provider_role_report(report: dict[str, Any], provider_report: dict[str, Any]) -> None:
    for key, check in provider_report["checks"].items():
        report["checks"][key] = check
    for key in provider_report["failedChecks"]:
        if key not in report["failedChecks"]:
            report["failedChecks"].append(key)


def _format_profile(packet: dict[str, Any]) -> str:
    return _text(packet.get("formatProfile") or packet.get("format_profile") or packet.get("productionMode"))


def _provider_matrix(packet: dict[str, Any]) -> dict[str, Any]:
    matrix = packet.get("providerRoleMatrix") or packet.get("providerRoles")
    return matrix if isinstance(matrix, dict) else {}


def _chapters(packet: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        packet.get("chapters"),
        _nested(packet, "outline", "chapters"),
        _nested(packet, "longformOutline", "chapters"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _storyboard(packet: dict[str, Any]) -> dict[str, Any]:
    value = packet.get("storyboard") or packet.get("longformStoryboard")
    return value if isinstance(value, dict) else {}


def _storyboard_beats(packet: dict[str, Any]) -> list[dict[str, Any]]:
    storyboard = _storyboard(packet)
    candidates = [
        storyboard.get("beats"),
        storyboard.get("storyboardBeats"),
        packet.get("storyboardBeats"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _chapter_markers(packet: dict[str, Any]) -> list[dict[str, Any]]:
    storyboard = _storyboard(packet)
    candidates = [
        packet.get("chapterMarkers"),
        storyboard.get("chapterMarkers"),
        storyboard.get("youtubeChapterMarkers"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _web_reference_ledger(packet: dict[str, Any]) -> dict[str, Any]:
    storyboard = _storyboard(packet)
    value = packet.get("webReferenceLedger") or storyboard.get("webReferenceLedger")
    return value if isinstance(value, dict) else {}


def _power_user_production_plan(packet: dict[str, Any]) -> dict[str, Any]:
    value = packet.get("powerUserProductionPlan") or packet.get("creatorProductionPlan")
    return value if isinstance(value, dict) else {}


def _power_user_case_ledger(packet: dict[str, Any]) -> dict[str, Any]:
    plan = _power_user_production_plan(packet)
    value = packet.get("powerUserCaseLedger") or plan.get("powerUserCaseLedger")
    return value if isinstance(value, dict) else {}


def _segments(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("segments", "beats", "scenes"):
        value = chapter.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _evidence_items(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("evidence", "evidenceItems", "sources"):
        value = chapter.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _evidence_id(item: dict[str, Any]) -> str:
    return _text(item.get("evidenceId") or item.get("id") or item.get("sourceUrl") or item.get("url"))


def _chapter_id(chapter: dict[str, Any], index: int) -> str:
    return _text(chapter.get("chapterId") or chapter.get("id") or f"chapter-{index + 1:02d}")


def _normalize_roles(matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    roles: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(matrix, dict):
        return roles

    scene_entries = matrix.get("scenes") if isinstance(matrix.get("scenes"), list) else []
    for role, value in matrix.items():
        if role == "scenes":
            continue
        _append_role_values(roles, role, value)
    for scene in scene_entries:
        if isinstance(scene, dict):
            for role, value in scene.items():
                if role.endswith("Id") or role in {"sceneId", "chapterId"}:
                    continue
                _append_role_values(roles, role, value)
    return roles


def _append_role_values(roles: dict[str, list[dict[str, Any]]], role: str, value: Any) -> None:
    for item in _role_entries(value):
        roles.setdefault(role, []).append(item)


def _role_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        provider = _text(value)
        return [{"provider": provider}] if provider else []
    if isinstance(value, dict):
        provider = _text(value.get("provider") or value.get("providerKey"))
        return [{**value, "provider": provider}] if provider else []
    if isinstance(value, list):
        entries: list[dict[str, Any]] = []
        for item in value:
            entries.extend(_role_entries(item))
        return entries
    return []


def _claims_final_ready(packet: dict[str, Any]) -> bool:
    if (
        packet.get("claimFinalReady") is True
        or packet.get("finalReadinessClaim") is True
        or packet.get("releaseReadinessClaim") is True
        or packet.get("claimsFinalReady") is True
        or packet.get("publishReadyClaim") is True
    ):
        return True
    if _text(packet.get("candidateEvaluationStatus")).lower() == "approved":
        return True
    for key, ready_statuses in (
        ("publishReadiness", {"ready"}),
        ("channelReadiness", {"ready", "channel-ready"}),
        ("topTierReadiness", {"ready", "top-tier-ready"}),
    ):
        value = packet.get(key)
        if isinstance(value, dict) and _text(value.get("status")).lower() in ready_statuses:
            return True
    return False


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _set_check(report: dict[str, Any], key: str, status: str, detail: str) -> None:
    report["checks"][key] = {"status": status, "detail": detail}


def _fail(report: dict[str, Any], key: str, detail: str) -> None:
    _set_check(report, key, "fail", detail)
    if key not in report["failedChecks"]:
        report["failedChecks"].append(key)
