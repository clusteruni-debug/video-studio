from __future__ import annotations

import json

from worker.render.compose import compose_smoke_render
from worker.render.golden_reference_gate import evaluate_golden_reference_compliance


def _touch(path, data: bytes = b"artifact-evidence-bytes"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _image(path):
    _touch(path, b"\xff\xd8" + b"review-evidence" * 4 + b"\xff\xd9")


def _write_json(path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scene(
    scene_id: str,
    *,
    idx: int,
    role: str,
    layout: str,
    subtitle: str,
    caption_zone: str,
    source_path: str,
) -> dict:
    prompt = (
        "Vertical handheld close-up camera shot showing the primary subject "
        "being checked by a real actor in a practical environment, no text overlay, "
        "no charts, no diagrams, clear action state and visible surroundings."
    )
    return {
        "sceneId": scene_id,
        "title": f"Scene {idx}",
        "durationSec": 2.6 if idx else 1.35,
        "visualKind": "video",
        "sourceType": "video",
        "sourcePath": source_path,
        "subtitleText": subtitle,
        "narrationText": (
            "이 변화는 그냥 넘어가도 될까요?"
            if idx == 0
            else "변화를 먼저 보고 판단은 그다음에 하세요."
            if role != "answer"
            else "확실하지 않다면 다시 확인하고 넘어가세요."
        ),
        "captionPreset": "top-hook" if idx == 0 else "lower-info",
        "layoutVariantKey": layout,
        "referenceEditRole": role,
        "sourceContract": {
            "requiredObject": "primary subject with readable object state",
            "mustShow": ["primary subject", "actor or manipulator", "real environment"],
            "forbidden": ["abstract diagram", "text overlay", "vertical heat bar"],
        },
        "sourceQualityRubric": {
            "required": True,
            "minDimension": 60,
            "dimensions": {
                "promptIntentFit": 76,
                "primarySubjectIntegrity": 74,
                "actorOrManipulatorIntegrity": 71,
                "actionReadability": 77,
                "physicalPlausibility": 73,
                "cameraGrammar": 75,
                "lightingColorNaturalness": 72,
                "temporalStability": 70,
                "aiArtifactControl": 68,
                "editability": 76,
            },
            "topicSpecificCriteriaInGlobalGate": False,
        },
        "promptContract": {
            "camera": "vertical handheld close-up camera",
            "action": "show the actor checking the primary subject state",
            "mustShow": ["primary subject", "actor or manipulator", "real environment"],
            "mustNotShow": ["caption text", "text overlay", "chart", "diagram"],
            "prompt": prompt,
        },
        "captionContract": {
            "role": role,
            "maxLines": 2,
            "tone": "spoken Korean curiosity",
        },
        "layoutContract": {
            "captionZone": caption_zone,
            "fontSize": 60 if idx == 0 else 58,
            "maxWidthPx": 760,
            "enterTimingSec": 0.2 if idx == 0 else 0.35,
            "displayDurationSec": 1.2 if idx == 0 else 1.55,
            "mustNotCover": ["primary subject", "actor/manipulator", "main action"],
            "decorativeOverlayAllowed": False,
        },
        "ttsScriptContract": {
            "role": role,
            "tone": "natural Korean spoken context, not hosty",
            "maxKoreanCharsPerSec": 12.0 if idx == 0 else 8.0,
            "avoidOverFriendlyTone": True,
        },
    }


def _editorial_direction_contract() -> dict:
    return {
        "required": True,
        "referenceBasis": [
            "YouTube Shorts timeline editing: text timing, audio, voiceover, and Shorts pacing",
            "CapCut caption and sound tools: editable captions plus sound effects matched to motion and scene changes",
            "Sound design research: SFX and foley must be synchronized to visible source events",
            "Short-form accessibility research: avoid dense on-screen text, rapid changes, and unrelated music or meme audio",
            "Continuity editing: match action, new information, diegetic sound, and viewer orientation across cuts",
        ],
        "evidence": {
            "directingPlanPath": "storage/qa/editorial-direction-plan.json",
            "phoneReviewPath": "storage/qa/editorial-phone-review.jpg",
            "referenceComparisonPath": "storage/qa/editorial-reference-comparison.json",
            "noHudComparisonPath": "storage/qa/editorial-no-hud-ab.jpg",
        },
        "shotIntentMap": [
            {
                "sceneId": "scene-001",
                "role": "hook-question",
                "viewerQuestionOrAnswer": "what visible state changed first",
                "visibleEvent": "primary subject is inspected in the first beat",
                "focusTarget": "primary subject state and actor hand",
                "sourceEventReadable": True,
                "subjectProtected": True,
                "captionExplainsMissingVisual": False,
            },
            {
                "sceneId": "scene-002",
                "role": "mechanism",
                "viewerQuestionOrAnswer": "what action explains the change",
                "visibleEvent": "actor continues checking the primary subject",
                "focusTarget": "state change in the same subject",
                "sourceEventReadable": True,
                "subjectProtected": True,
                "captionExplainsMissingVisual": False,
            },
            {
                "sceneId": "scene-003",
                "role": "answer",
                "viewerQuestionOrAnswer": "what action should the viewer take",
                "visibleEvent": "final subject state resolves the inspection",
                "focusTarget": "final subject and action resolution",
                "sourceEventReadable": True,
                "subjectProtected": True,
                "captionExplainsMissingVisual": False,
            },
        ],
        "motivatedCutPlan": [
            {
                "fromSceneId": "scene-001",
                "toSceneId": "scene-002",
                "cutAtSec": 1.35,
                "cutReason": "match-action",
                "visibleContinuityBridge": True,
                "newInformationRevealed": False,
                "actionContinuesAcrossCut": True,
                "unmotivatedHoldSec": 0,
            },
            {
                "fromSceneId": "scene-002",
                "toSceneId": "scene-003",
                "cutAtSec": 3.95,
                "cutReason": "payoff",
                "visibleContinuityBridge": False,
                "newInformationRevealed": True,
                "actionContinuesAcrossCut": False,
                "unmotivatedHoldSec": 0,
            },
        ],
        "audioVisualBinding": {
            "everyCueBoundToVisibleEvent": True,
            "unrelatedAudioCues": False,
            "maxSyncOffsetSec": 0.18,
            "minimumSfxCueCount": 0,
            "maxSfxCueCount": 4,
            "cues": [
                {
                    "type": "bgm",
                    "bindingMode": "bgm-bed",
                    "sourceEvent": "global restrained curiosity bed",
                    "syncOffsetSec": 0,
                    "decorativeOnly": False,
                },
            ],
        },
        "captionPerformance": {
            "notTtsDuplicate": True,
            "timelineReviewed": True,
            "safeZoneReviewed": True,
            "subjectOcclusion": False,
            "captionExplainsMissingVisual": False,
            "maxLines": 2,
            "maxCharsPerCaption": 22,
            "timelineCues": [
                {
                    "sceneId": "scene-001",
                    "startSec": 0.45,
                    "endSec": 1.15,
                    "text": "그냥 넘어가도 될까?",
                },
                {
                    "sceneId": "scene-002",
                    "startSec": 1.70,
                    "endSec": 2.70,
                    "text": "변화부터 보세요",
                },
                {
                    "sceneId": "scene-003",
                    "startSec": 4.15,
                    "endSec": 5.05,
                    "text": "다시 확인하세요",
                },
            ],
            "ttsSegments": [
                {
                    "sceneId": "scene-001",
                    "startSec": 0.48,
                    "endSec": 1.18,
                    "text": "먼저 보이는 변화를 확인하고 판단하세요.",
                },
                {
                    "sceneId": "scene-002",
                    "startSec": 1.72,
                    "endSec": 2.68,
                    "text": "움직임이 이어지는지 눈으로 따라가 보세요.",
                },
                {
                    "sceneId": "scene-003",
                    "startSec": 4.12,
                    "endSec": 5.02,
                    "text": "확실하지 않다면 잠깐 멈추고 다시 보세요.",
                },
            ],
        },
        "continuityMap": {
            "continuitySlots": [
                "primarySubject",
                "actorOrManipulator",
                "environment",
                "primaryAction",
                "camera",
                "lighting",
                "audio",
            ],
            "adjacentContinuityPassRatio": 0.86,
            "primarySubjectIdentityDrift": False,
            "primarySubjectScaleJump": False,
            "unexplainedCameraWorldJump": False,
        },
        "restraintMode": {
            "effectsAreOptional": True,
            "effectCountIsNotQuality": True,
            "symbolCuesDefault": False,
            "noGeneratedStickerPresetSpray": True,
        },
        "referenceComparison": {
            "comparedAgainstExternalReferences": 3,
            "noHudAbReviewed": True,
            "editImprovesComprehensionOverNoHud": True,
        },
        "topicSpecificCriteriaInGlobalGate": False,
    }


def _clean_external_edit_contract() -> dict:
    return {
        "required": False,
        "cleanEditorialMode": True,
        "generatedVisualLayersAllowed": False,
        "generatedSfxAllowed": False,
        "manualExceptionOnly": True,
        "visualElementCount": 0,
        "audioCueCount": 0,
        "reasonNoGeneratedExternalElements": "The default edit relies on source-visible events, cuts, captions, BGM, and clean CapCut motion instead of symbolic overlays.",
        "rejectionBasis": [
            "Generated X/OK/check stickers read as crude decoration when the screen event is already visible.",
            "Generated SFX hits are rejected unless they bind to a source event within the sync window.",
            "Effect counts are not a quality signal; restraint is allowed when it improves comprehension.",
        ],
        "perScenePlan": [
            {"sceneId": "scene-001", "elements": [], "reasonNoExternalElement": "hook source event remains readable without a symbol"},
            {"sceneId": "scene-002", "elements": [], "reasonNoExternalElement": "mechanism beat uses cut timing and caption staging"},
            {"sceneId": "scene-003", "elements": [], "reasonNoExternalElement": "answer beat uses subject hold and BGM tail"},
        ],
        "topicSpecificCriteriaInGlobalGate": False,
    }


def _editorial_plan_payload() -> dict:
    contract = _editorial_direction_contract()
    return {
        "schema": "video-studio.editorial-pass.v1",
        "status": "pass",
        "shotIntentMap": contract["shotIntentMap"],
        "motivatedCutPlan": contract["motivatedCutPlan"],
        "captionPlan": contract["captionPerformance"]["timelineCues"],
        "ttsSegments": contract["captionPerformance"]["ttsSegments"],
        "audioCueSheet": contract["audioVisualBinding"]["cues"],
    }


def _write_editorial_plan_from_manifest(root, manifest: dict):
    contract = manifest["postEditGoldenReference"]["editorialDirection"]
    _write_json(
        root / "storage/qa/editorial-direction-plan.json",
        {
            "schema": "video-studio.editorial-pass.v1",
            "status": "pass",
            "shotIntentMap": contract["shotIntentMap"],
            "motivatedCutPlan": contract["motivatedCutPlan"],
            "captionPlan": contract["captionPerformance"]["timelineCues"],
            "ttsSegments": contract["captionPerformance"]["ttsSegments"],
            "audioCueSheet": contract["audioVisualBinding"]["cues"],
        },
    )


def _reference_comparison_payload() -> dict:
    return {
        "schema": "video-studio.reference-comparison.v1",
        "status": "pass",
        "externalReferences": [
            {"source": "YouTube Shorts timeline editing reference", "usedFor": "timed text and music sync"},
            {"source": "Continuity editing reference", "usedFor": "cut motivation and action bridge"},
        ],
        "noHudAbReviewed": True,
        "editImprovesComprehensionOverNoHud": True,
    }


def _post_edit_score_payload() -> dict:
    dimensions = {
        "sourceTakeQuality": 73.2,
        "sourceSequenceContinuity": 73.0,
        "hookClarity": 76,
        "storyPayoff": 76,
        "copyTtsQuality": 78,
        "captionAccessibility": 73,
        "editRhythm": 72,
        "audioMix": 78,
        "colorTechnicalQuality": 70,
        "platformReferenceFit": 74,
    }
    return {
        "schema": "video-studio.post-edit-score.v1",
        "status": "pass",
        "computedScore": {
            "overall": 74.3,
            "dimensions": dimensions,
        },
        "scoreInputs": {
            "shotIntentMap": True,
            "motivatedCutPlan": True,
            "captionPlan": True,
            "audioCueSheet": True,
            "capcutDraftAudit": True,
        },
    }


def _capcut_draft_content_payload() -> dict:
    def keyframed_segment():
        return {
            "common_keyframes": [
                {"keyframe_list": [{}, {}, {}]},
                {"keyframe_list": [{}, {}, {}]},
                {"keyframe_list": [{}, {}, {}]},
            ]
        }

    return {
        "tracks": [
            {"type": "video", "segments": [keyframed_segment(), keyframed_segment()]},
            {"type": "audio", "segments": [{}, {}, {}]},
            {"type": "text", "segments": [{}, {}, {}]},
        ]
    }


def _capcut_draft_audit_payload() -> dict:
    return {
        "schema": "video-studio.capcut-draft-audit.v1",
        "trackCounts": {"video": 2, "audio": 3, "text": 3, "effect": 0},
        "actualVideoKeyframes": 18,
        "totalMotionKeyframes": 18,
        "sfxTracks": 0,
        "effectTracks": 0,
        "editElementVisualLayers": 0,
        "operations": [
            {"id": "source-motion-001", "kind": "sourceMotionProfile", "sceneId": "scene-001", "ok": True},
            {"id": "source-motion-002", "kind": "sourceMotionProfile", "sceneId": "scene-002", "ok": True},
            {"id": "caption-001", "kind": "caption", "sceneId": "scene-001", "ok": True},
            {"id": "caption-002", "kind": "caption", "sceneId": "scene-002", "ok": True},
            {"id": "caption-003", "kind": "caption", "sceneId": "scene-003", "ok": True},
            {"id": "tts-001", "kind": "tts", "sceneId": "scene-001", "ok": True},
            {"id": "tts-002", "kind": "tts", "sceneId": "scene-002", "ok": True},
            {"id": "tts-003", "kind": "tts", "sceneId": "scene-003", "ok": True},
            {"id": "bgm-001", "kind": "bgm", "ok": True},
        ],
    }


def _active_external_edit_contract() -> dict:
    return {
        "required": True,
        "referenceBasis": [
            "YouTube Shorts timeline editor for video, text, stickers, music, and voiceover",
            "YouTube Shorts visual guides and sticker placement for safe platform overlays",
            "TikTok Creative Center Top Ads high-performing vertical examples",
            "Microsoft motion continuity and connected animation context",
            "WCAG 2.2 reduced motion and flash safety",
        ],
        "layerPurpose": {
            "editorialFunctionDeclared": True,
            "supportsNarrativeBeats": True,
            "decorativeOnly": False,
            "sourceReplacementClaim": False,
        },
        "elementTypes": ["keyword-emphasis", "match-cut-assist"],
        "visualElementCount": 2,
        "audioCueCount": 0,
        "safety": {
            "platformSafeZoneReviewed": True,
            "subjectOcclusion": False,
            "debugOrEditorLabels": False,
            "maxScreenAreaRatio": 0.08,
            "maxOpacity": 0.58,
            "maxFlashPerSecond": 2.0,
            "rapidFlashes": False,
            "reducedMotionSafe": True,
            "templateLook": False,
        },
        "perceptualSalience": {
            "recognizableSymbolRequired": False,
            "semanticCueMatchesNarration": True,
            "viewerCanNameCueAfterOneWatch": True,
            "sourceEventBindingRequired": True,
            "everyCueBoundToVisibleSourceEvent": True,
            "effectCountIsNotQuality": True,
            "symbolCuesDefault": False,
            "containsWarningOrNegativeAction": True,
            "warningBeatSourceEventBound": True,
            "containsPositiveResolution": True,
            "positiveResolutionSourceEventBound": True,
            "minVisualCueScreenAreaRatio": 0.018,
            "minCueOpacity": 0.58,
        },
        "evidence": {
            "editElementPlanPath": "storage/qa/external-edit-plan.json",
            "phonePreviewPath": "storage/qa/external-edit-preview.jpg",
        },
        "perScenePlan": [
            {
                "sceneId": "scene-001",
                "elements": [
                    {
                        "type": "keyword-emphasis",
                        "semanticRole": "warning-no",
                        "semanticCueMatchesNarration": True,
                        "sourceEvent": "the first visible source action raises the warning",
                        "bindingMode": "visible-action",
                        "purpose": "briefly guide attention to the source event without adding a symbol",
                        "startSec": 0.72,
                        "endSec": 1.24,
                        "screenAreaRatio": 0.05,
                        "opacity": 0.60,
                        "subjectOcclusion": False,
                        "decorativeOnly": False,
                    }
                ],
            },
            {
                "sceneId": "scene-002",
                "elements": [
                    {
                        "type": "match-cut-assist",
                        "semanticRole": "safe-resolution",
                        "semanticCueMatchesNarration": True,
                        "sourceEvent": "the second scene resolves the source action",
                        "bindingMode": "cut-bridge",
                        "purpose": "bridge the cut through the visible action change",
                        "startSec": 0.40,
                        "endSec": 0.92,
                        "screenAreaRatio": 0.04,
                        "opacity": 0.60,
                        "subjectOcclusion": False,
                        "decorativeOnly": False,
                    }
                ],
            },
            {
                "sceneId": "scene-003",
                "elements": [],
                "reasonNoExternalElement": "final answer stays cleaner with subject hold and audio tail",
            },
        ],
        "topicSpecificCriteriaInGlobalGate": False,
    }


def _passing_manifest(root) -> dict:
    source_paths = [
        "storage/source/scene-001.mp4",
        "storage/source/scene-002.mp4",
        "storage/source/scene-003.mp4",
    ]
    for source_path in source_paths:
        _touch(root / source_path)
    _image(root / "storage/qa/source-contact-sheet.jpg")
    _image(root / "storage/qa/first-2s-review.jpg")
    _image(root / "storage/qa/first-3s-review.jpg")
    _image(root / "storage/qa/caption-safe-zone-review.jpg")
    _write_json(root / "storage/qa/color-match-evidence.json", {"status": "pass"})
    _write_json(root / "storage/qa/post-edit-score-review.json", _post_edit_score_payload())
    _image(root / "storage/qa/final-2s-review.jpg")
    _write_json(root / "storage/qa/audio-mix-evidence.json", {"status": "pass"})
    _write_json(root / "storage/qa/tts-candidate-comparison.json", {"status": "pass"})
    _write_json(root / "storage/qa/external-edit-plan.json", {"status": "pass"})
    _image(root / "storage/qa/external-edit-preview.jpg")
    _write_json(root / "storage/qa/editorial-direction-plan.json", _editorial_plan_payload())
    _image(root / "storage/qa/editorial-phone-review.jpg")
    _write_json(root / "storage/qa/editorial-reference-comparison.json", _reference_comparison_payload())
    _image(root / "storage/qa/editorial-no-hud-ab.jpg")
    _write_json(root / "storage/qa/capcut-draft/draft_content.json", _capcut_draft_content_payload())
    _write_json(root / "storage/qa/capcut-draft-audit.json", _capcut_draft_audit_payload())
    return {
        "projectId": "golden-reference-pass",
        "referenceStylePreset": "kr_curiosity_explainer",
        "goldenReferenceComplianceRequired": True,
        "sourceContactSheetPath": "storage/qa/source-contact-sheet.jpg",
        "visualUnityTreatment": {
            "required": True,
            "appliesToAllScenes": True,
            "subjectSafe": True,
            "treatmentTypes": [
                "thin common phone-video frame",
                "single restrained warm color grade",
                "consistent caption-safe matte",
            ],
            "reviewChecklist": [
                "all scenes read as one edited video package",
                "treatment does not cover primary subject, actor/manipulator, or action",
                "no visible production guide marks or unexplained divider artifacts",
            ],
        },
        "sourceSequenceContinuity": {
            "required": True,
            "continuitySlots": [
                "primarySubject",
                "actorOrManipulator",
                "environment",
                "primaryAction",
                "camera",
                "lighting",
                "style",
            ],
            "minDimension": 60,
            "dimensions": {
                "entityContinuity": 72,
                "environmentContinuity": 70,
                "actionContinuity": 75,
                "cameraContinuity": 73,
                "lightingContinuity": 71,
                "styleContinuity": 74,
                "repairability": 76,
            },
            "topicSpecificCriteriaInGlobalGate": False,
        },
        "openingAudioContinuity": {
            "coldOpen": {
                "firstFrameHasPrimaryVisual": True,
                "firstFrameIsBlack": False,
                "captionOnlyOpening": False,
                "firstFrameHasOnlySubtitleOrText": False,
                "blackScreenStartSec": 0.0,
                "firstVisibleActionSec": 0.35,
                "firstTwoSecReviewPath": "storage/qa/first-2s-review.jpg",
            },
            "audioBed": {
                "bgmPresent": True,
                "bgmAudibleUnderVoice": True,
                "introBgmAudible": True,
                "outroBgmTailAudible": True,
                "bgmNonPlaceholder": True,
                "bgmSourcePath": "assets/bgm/calm/warm-curiosity-bed.wav",
                "bgmSourceType": "local-bgm",
                "bgmMeanVolumeDb": -24.0,
                "audioMixEvidencePath": "storage/qa/audio-mix-evidence.json",
            },
            "audioBridges": [
                {"fromSceneId": "scene-001", "toSceneId": "scene-002", "mode": "j-cut", "durationSec": 0.28},
                {"fromSceneId": "scene-002", "toSceneId": "scene-003", "mode": "crossfade", "durationSec": 0.30},
            ],
            "ttsAlignment": {
                "required": True,
                "timelineReviewed": True,
                "voiceQuality": {
                    "required": True,
                    "provider": "edge-tts",
                    "voiceName": "ko-KR-SunHiNeural",
                    "voiceClass": "neural",
                    "ratePercent": -6,
                    "voiceNaturalnessReviewed": True,
                    "speechRateReviewed": True,
                    "fallbackUsed": False,
                    "perceivedRoboticOrSapi": False,
                    "candidateComparisonPath": "storage/qa/tts-candidate-comparison.json",
                },
                "timelineDurationSec": 9.0,
                "narrationDurationSec": 7.1,
                "narrationStartSec": 0.45,
                "narrationEndSec": 7.55,
                "voiceEndsBeforeVideoEndSec": 1.45,
                "maxCaptionVoiceDesyncSec": 0.42,
                "maxSceneVoiceOverflowSec": 0.12,
                "allVoiceLinesComplete": True,
                "finalSpokenLineComplete": True,
                "finalCaptionCoversFinalVoiceLine": True,
                "captionsDoNotAdvanceBeforeVoice": True,
                "sceneTimings": [
                    {
                        "sceneId": "scene-001",
                        "sceneEndSec": 2.35,
                        "voiceEndSec": 2.20,
                        "captionEndSec": 2.30,
                    },
                    {
                        "sceneId": "scene-002",
                        "sceneEndSec": 5.40,
                        "voiceEndSec": 5.30,
                        "captionEndSec": 5.35,
                    },
                    {
                        "sceneId": "scene-003",
                        "sceneEndSec": 9.00,
                        "voiceEndSec": 7.55,
                        "captionEndSec": 7.70,
                    },
                ],
            },
            "payoffTail": {
                "finalBeatHasVisualResolution": True,
                "endingIsBlank": False,
                "blankOutroSec": 0.0,
                "finalVisualHoldSec": 0.85,
                "finalBgmTailSec": 0.75,
                "finalAudioFadeSec": 0.65,
                "finalTwoSecReviewPath": "storage/qa/final-2s-review.jpg",
            },
        },
        "postEditGoldenReference": {
            "required": True,
            "referenceBasis": [
                "YouTube Shorts editing tools: sound, text timeline, captions, and voiceover",
                "YouTube Shorts mobile filming: shot list, soft light, clean sound, and start/end beat",
                "TikTok Creative Center Top Ads: compare against high-performing vertical examples",
                "Hook-period research: first three seconds blend visual, audio, and text",
                "Short-form accessibility: avoid rapid visual changes, dense on-screen text, and muddy overlays",
            ],
            "score": {
                "overall": 74.3,
                "minOverall": 72,
                "minDimension": 60,
                "dimensions": {
                    "sourceTakeQuality": 73.2,
                    "sourceSequenceContinuity": 73.0,
                    "hookClarity": 76,
                    "storyPayoff": 76,
                    "copyTtsQuality": 78,
                    "captionAccessibility": 73,
                    "editRhythm": 72,
                    "audioMix": 78,
                    "colorTechnicalQuality": 70,
                    "platformReferenceFit": 74,
                },
            },
            "firstThreeSecReviewPath": "storage/qa/first-3s-review.jpg",
            "captionSafeZoneEvidencePath": "storage/qa/caption-safe-zone-review.jpg",
            "audioMixEvidencePath": "storage/qa/audio-mix-evidence.json",
            "colorMatchEvidencePath": "storage/qa/color-match-evidence.json",
            "finalTwoSecReviewPath": "storage/qa/final-2s-review.jpg",
            "scoringReviewPath": "storage/qa/post-edit-score-review.json",
            "editorialDirection": _editorial_direction_contract(),
            "hook": {
                "firstThreeSecHasPrimaryVisual": True,
                "firstThreeSecHasMotionOrAction": True,
                "firstThreeSecHasAudioBed": True,
                "viewerQuestionClear": True,
                "firstCaptionStartSec": 0.72,
            },
            "captions": {
                "maxLines": 2,
                "maxCharsPerCaption": 24,
                "stableSafeZone": True,
                "mainSubjectOcclusion": False,
                "timelineReviewed": True,
                "maxScreenAreaRatio": 0.12,
            },
            "layoutHud": {
                "referenceBasis": [
                    "YouTube Shorts text timeline, captions, filters, sound, and voiceover",
                    "TikTok Creative Center Top Ads high-performing vertical examples",
                    "WCAG 2.2 contrast and captions accessibility",
                    "Netflix timed text line count, line length, and reading speed guidance",
                ],
                "safeZone": {
                    "platformUiReviewed": True,
                    "subjectOcclusion": False,
                    "topReservedPx": 112,
                    "bottomReservedPx": 260,
                    "rightReservedPx": 116,
                },
                "typography": {
                    "hookFontSizePx": 60,
                    "bodyFontSizePx": 48,
                    "lineCountMax": 2,
                    "lineLengthMaxKorean": 16,
                    "textContrastRatio": 7.8,
                    "boxOpacity": 0.46,
                },
                "hud": {
                    "mode": "minimal-frame",
                    "opacity": 0.07,
                    "screenAreaRatio": 0.018,
                    "textLabels": False,
                    "debugMarks": False,
                },
                "transitions": {
                    "purposeDeclaredPerCut": True,
                    "beatAligned": True,
                    "decorativeOnlyTransitions": False,
                    "maxTransitionDurationSec": 0.28,
                },
            },
            "externalEditElements": _clean_external_edit_contract(),
            "capcutHandoff": {
                "required": True,
                "draftRequired": True,
                "pipelineMode": "capcut-draft-first",
                "referenceBasis": [
                    "CapCut keyframe animation: keyframe motion, speed curves, and easing",
                    "CapCut auto caption generator: caption timeline, sync, and style remain editable",
                    "YouTube Shorts timeline: video, text, stickers, music, voiceover, and TTS",
                    "TikTok Creative Center Top Ads: compare against high-performing vertical examples",
                    "CapCut effects/templates: native effect, transition, light leak, glitch, HUD, and filter layers",
                    "VectCutAPI CapCut draft automation creates draft_content.json tracks",
                ],
                "capcutIsPrimaryEditSurface": True,
                "ffmpegPreviewOnly": True,
                "ffmpegOnlyAllowed": False,
                "manualExportRequired": True,
                "humanReviewBeforeUpload": True,
                "editableTextAndTiming": True,
                "motionDesignedEditElements": True,
                "automationSurface": {
                    "tool": "VectCutAPI",
                    "targetEditor": "CapCut desktop",
                    "draftFormat": "draft_content.json",
                    "localDraftRootExists": True,
                    "capcutInstallVerified": True,
                    "finalExportByOperator": True,
                    "ffmpegPreviewOnly": True,
                },
                "editModel": {
                    "multitrackTimeline": True,
                    "editableTextAndTiming": True,
                    "editableCaptions": True,
                    "editableAudioLevels": True,
                    "editableMotionElements": True,
                    "extraTextCalloutsAllowed": False,
                    "editElementsUseNonTextVisuals": False,
                    "nativeCapCutEffectsRequired": False,
                    "generatedEffectLayersAllowed": False,
                    "cleanEditorialMode": True,
                },
                "effectPass": {
                    "required": True,
                    "mode": "clean-editorial-no-canned-effects",
                    "usesNativeCapCutEffects": False,
                    "nativeEffectsDisabled": True,
                    "generatedVisualEffectsDisabled": True,
                    "forbidPngOnlyClaim": True,
                    "manualPresetReviewRequired": True,
                    "visualBindingRequired": True,
                    "forbidUnanchoredEffects": True,
                    "forbidPresetSpray": True,
                    "cannedEffectsRejected": True,
                    "effectTrackCount": 0,
                    "minEffectTracks": 0,
                    "maxEffectTracks": 0,
                    "anchoredCueRoles": [],
                    "requiredFamilies": [],
                    "disallowedUnanchoredFamilies": [
                        "atmosphere-light",
                        "distortion",
                        "scan-context",
                        "impact-pulse",
                    ],
                    "candidateEffects": [],
                },
                "motionDesign": {
                    "usesKeyframes": True,
                    "usesEasing": True,
                    "usesSpeedCurvesOrEasing": True,
                    "minKeyframedElements": 2,
                    "editorialMotionPass": {
                        "required": True,
                        "mode": "capcut-scene-directed-motion",
                        "sceneDirectedMotion": True,
                        "capcutKeyframesNotPreviewOnly": True,
                        "captionAnimationDesigned": True,
                        "sceneMotionProfileCount": 2,
                        "captionAnimationProfileCount": 2,
                        "transitionCount": 1,
                        "totalKeyframeCount": 18,
                        "minKeyframesPerScene": 9,
                        "minVisibleScaleDelta": 0.07,
                        "maxUnmotivatedMotionSec": 0,
                        "motionProfiles": [
                            {
                                "sceneId": "scene-001",
                                "role": "hook-question",
                                "profile": "hook-push-in",
                                "motionIntent": "open with a curiosity push",
                                "keyframeCount": 9,
                                "scaleDelta": 0.08,
                                "positionDelta": 0.03,
                            },
                            {
                                "sceneId": "scene-002",
                                "role": "answer",
                                "profile": "resolution-pullback",
                                "motionIntent": "release tension",
                                "keyframeCount": 9,
                                "scaleDelta": 0.07,
                                "positionDelta": 0.03,
                            },
                        ],
                    },
                    "noRawDrawboxDrawtextFinal": True,
                    "motionDurationMsMin": 83,
                    "motionDurationMsMax": 400,
                },
                "roundTripStatus": "draft-created",
                "draftPath": "storage/qa/capcut-draft",
                "draftContentPath": "storage/qa/capcut-draft/draft_content.json",
                "draftAuditPath": "storage/qa/capcut-draft-audit.json",
                "mediaLinked": {
                    "sourceVideoTracks": True,
                    "ttsTracks": True,
                    "bgmTrack": True,
                    "sfxTracks": False,
                    "captionTracks": True,
                    "editElementTracks": False,
                    "effectTracks": False,
                },
            },
            "rhythm": {
                "transitionCount": 2,
                "actionBeatsAlignedToCuts": True,
                "noHardJumpWithoutBridge": True,
                "minShotHoldSec": 1.25,
                "maxDeadAirSec": 0.45,
            },
            "audio": {
                "duckingApplied": True,
                "bgmContinuous": True,
                "sourceAmbienceOrFoleyPresent": True,
                "speechBgmSeparationReviewed": True,
                "fullMixMeanDb": -18.2,
            },
            "color": {
                "colorGradeAppliedToAllScenes": True,
                "noUnmotivatedFlashes": True,
                "maxLumaDelta": 0.22,
                "maxSaturationDelta": 0.18,
            },
            "payoff": {
                "finalAnswerResolved": True,
                "noNewInfoInLastSecond": True,
                "finalVisualHoldSec": 1.2,
                "finalAudioTailSec": 0.9,
            },
        },
        "scenes": [
            _scene(
                "scene-001",
                idx=0,
                role="hook-question",
                layout="headline-evidence",
                subtitle="이 변화\\N그냥 넘어가도 될까?",
                caption_zone="top-left",
                source_path=source_paths[0],
            ),
            _scene(
                "scene-002",
                idx=1,
                role="mechanism",
                layout="chapter-evidence",
                subtitle="무엇이 바뀌었는지\\N먼저 보세요",
                caption_zone="lower-mid",
                source_path=source_paths[1],
            ),
            _scene(
                "scene-003",
                idx=2,
                role="answer",
                layout="hands-proof",
                subtitle="확실하지 않다면\\N다시 확인하세요",
                caption_zone="lower-mid",
                source_path=source_paths[2],
            ),
        ],
    }


def test_golden_reference_gate_rejects_manifest_self_assertions_without_contracts(tmp_path):
    manifest = {
        "projectId": "self-claimed-pass",
        "referenceStylePreset": "kr_curiosity_explainer",
        "visualFrameReview": {"contactSheetPath": "storage/renders/self-claimed/contact-sheet.jpg"},
        "scenes": [
            {
                "sceneId": "scene-001",
                "title": "Bad",
                "durationSec": 3.5,
                "visualKind": "video",
                "subtitleText": "레퍼런스 반영\\N완료",
                "captionPreset": "top-hook",
                "layoutVariantKey": "headline-evidence",
                "referenceEditRole": "hook-question",
                "sourceFirstProof": True,
                "captionLayoutReview": {"status": "pass"},
            }
        ],
    }

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert report["renderAllowed"] is False
    assert "sourceContactSheet" in report["failedChecks"]
    assert "scene-001.sourceContract" in report["failedChecks"]
    assert "scene-001.sourceQualityRubric" in report["failedChecks"]
    assert "scene-001.promptContract" in report["failedChecks"]
    assert "scene-001.captionContract" in report["failedChecks"]
    assert "scene-001.layoutContract" in report["failedChecks"]
    assert "scene-001.copyTone" in report["failedChecks"]
    assert "scene-001.captionDirection" in report["failedChecks"]
    assert "scene-001.ttsScriptQuality" in report["failedChecks"]
    assert "visualUnityTreatment" in report["failedChecks"]
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "postEditGoldenReference" in report["failedChecks"]


def test_golden_reference_gate_passes_contract_and_artifact_parity(tmp_path):
    report = evaluate_golden_reference_compliance(_passing_manifest(tmp_path), project_root=tmp_path)

    assert report["status"] == "pass"
    assert report["renderAllowed"] is True
    assert report["failedChecks"] == []
    assert [scene["status"] for scene in report["scenes"]] == ["pass", "pass", "pass"]


def test_golden_reference_gate_allows_clean_editorial_without_generated_external_elements(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = {
        "required": False,
        "cleanEditorialMode": True,
        "generatedVisualLayersAllowed": False,
        "generatedSfxAllowed": False,
        "manualExceptionOnly": True,
        "visualElementCount": 0,
        "audioCueCount": 0,
        "reasonNoGeneratedExternalElements": (
            "Generated stickers, overlays, and sound hits were rejected because they looked unrelated to the source."
        ),
        "rejectionBasis": [
            "Generated external elements are disabled when they cannot be bound to a visible source action.",
            "CapCut remains available for manual operator-selected elements after review.",
            "Clean editorial mode prefers source footage, timing, captions, and audio mix over canned effects.",
        ],
        "perScenePlan": [
            {
                "sceneId": scene["sceneId"],
                "elements": [],
                "reasonNoExternalElement": "No generated external element is allowed for this clean editorial pass.",
            }
            for scene in manifest["scenes"]
        ],
        "topicSpecificCriteriaInGlobalGate": False,
    }

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "pass"
    assert report["renderAllowed"] is True


def test_golden_reference_gate_rejects_ai_slop_caption_and_tts(tmp_path):
    manifest = _passing_manifest(tmp_path)
    scene = manifest["scenes"][0]
    scene["subtitleText"] = "여러분 충격적인\\N사실 알아볼게요"
    scene["narrationText"] = "여러분 지금부터 놀라운 사실을 함께 알아볼게요."

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "scene-001.copyTone" in report["failedChecks"]
    assert "scene-001.ttsScriptQuality" in report["failedChecks"]
    assert "AI-slop" in report["scenes"][0]["checks"]["copyTone"]["detail"]


def test_golden_reference_gate_rejects_awkward_korean_label_copy_and_tts(tmp_path):
    manifest = _passing_manifest(tmp_path)
    scene = manifest["scenes"][0]
    scene["subtitleText"] = "정답은 조건\\N그냥 피하기"
    scene["narrationText"] = "정답은 조건, 그냥 피하기."

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "scene-001.copyTone" in report["failedChecks"]
    assert "scene-001.ttsScriptQuality" in report["failedChecks"]
    assert "awkward Korean" in report["scenes"][0]["checks"]["copyTone"]["detail"]
    assert "awkward Korean" in report["scenes"][0]["checks"]["ttsScriptQuality"]["detail"]


def test_golden_reference_gate_rejects_korean_caption_noun_label_line(tmp_path):
    manifest = _passing_manifest(tmp_path)
    scene = manifest["scenes"][1]
    scene["subtitleText"] = "상태 변화\\N확인 조건"

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "scene-002.copyTone" in report["failedChecks"]
    assert "noun label" in report["scenes"][1]["checks"]["copyTone"]["detail"]


def test_golden_reference_gate_rejects_missing_caption_direction_numbers(tmp_path):
    manifest = _passing_manifest(tmp_path)
    layout_contract = manifest["scenes"][1]["layoutContract"]
    layout_contract.pop("fontSize")
    layout_contract.pop("displayDurationSec")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "scene-002.captionDirection" in report["failedChecks"]
    assert "fontSize" in report["scenes"][1]["checks"]["captionDirection"]["detail"]


def test_golden_reference_gate_requires_shared_visual_unity_treatment(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest.pop("visualUnityTreatment")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "visualUnityTreatment" in report["failedChecks"]


def test_golden_reference_gate_requires_generic_source_sequence_continuity(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest.pop("sourceSequenceContinuity")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "sourceSequenceContinuity" in report["failedChecks"]
    assert "multi-source reference renders" in report["checks"]["sourceSequenceContinuity"]["detail"]


def test_golden_reference_gate_rejects_topic_specific_source_sequence_gate(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["sourceSequenceContinuity"]["topicSpecificCriteriaInGlobalGate"] = True

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "sourceSequenceContinuity" in report["failedChecks"]
    assert "topic-specific criteria" in report["checks"]["sourceSequenceContinuity"]["detail"]


def test_golden_reference_gate_requires_generic_source_take_quality(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["scenes"][0].pop("sourceQualityRubric")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "scene-001.sourceQualityRubric" in report["failedChecks"]
    assert "every source take" in report["scenes"][0]["checks"]["sourceQualityRubric"]["detail"]


def test_golden_reference_gate_rejects_low_source_take_dimension(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["scenes"][0]["sourceQualityRubric"]["dimensions"]["physicalPlausibility"] = 55

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "scene-001.sourceQualityRubric" in report["failedChecks"]
    assert "physicalPlausibility" in report["scenes"][0]["checks"]["sourceQualityRubric"]["detail"]


def test_golden_reference_gate_requires_global_post_edit_reference_contract(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest.pop("postEditGoldenReference")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "every golden/reference render" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_low_post_edit_score(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["score"]["overall"] = 68

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "below minimum" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_score_not_backed_by_computed_evidence(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["score"]["overall"] = 88

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "must match computed scoring evidence" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_fabricated_matching_post_edit_score(tmp_path):
    manifest = _passing_manifest(tmp_path)
    inflated_dimensions = {
        key: 95
        for key in manifest["postEditGoldenReference"]["score"]["dimensions"]
    }
    manifest["postEditGoldenReference"]["score"]["overall"] = 95
    manifest["postEditGoldenReference"]["score"]["dimensions"] = inflated_dimensions
    _write_json(
        tmp_path / "storage/qa/post-edit-score-review.json",
        {
            "schema": "video-studio.post-edit-score.v1",
            "status": "pass",
            "computedScore": {
                "overall": 95,
                "dimensions": inflated_dimensions,
            },
            "scoreInputs": {
                "shotIntentMap": True,
                "motivatedCutPlan": True,
                "captionPlan": True,
                "audioCueSheet": True,
                "capcutDraftAudit": True,
            },
        },
    )

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "gate-derived scoring result" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_legacy_post_edit_dimension_names(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["score"]["dimensions"] = {
        "sourceContinuity": 74,
        "hook": 76,
        "editRhythm": 72,
        "captionDesign": 73,
        "audioPolish": 78,
        "colorUnity": 70,
        "payoffResolution": 76,
    }

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "generic dimensions" in report["checks"]["postEditGoldenReference"]["detail"]
    assert "sourceTakeQuality" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_weak_post_edit_caption_and_audio_polish(tmp_path):
    manifest = _passing_manifest(tmp_path)
    post_edit = manifest["postEditGoldenReference"]
    post_edit["captions"]["mainSubjectOcclusion"] = True
    post_edit["audio"]["sourceAmbienceOrFoleyPresent"] = False

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "main subject" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_requires_layout_hud_contract(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"].pop("layoutHud")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "layoutHud object" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_unsafe_platform_zone(tmp_path):
    manifest = _passing_manifest(tmp_path)
    layout_hud = manifest["postEditGoldenReference"]["layoutHud"]
    layout_hud["safeZone"]["bottomReservedPx"] = 120

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "bottomReservedPx" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_oversized_caption_type(tmp_path):
    manifest = _passing_manifest(tmp_path)
    layout_hud = manifest["postEditGoldenReference"]["layoutHud"]
    layout_hud["typography"]["hookFontSizePx"] = 86

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "hookFontSizePx" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_hud_text_or_debug_marks(tmp_path):
    manifest = _passing_manifest(tmp_path)
    hud = manifest["postEditGoldenReference"]["layoutHud"]["hud"]
    hud["textLabels"] = True
    hud["opacity"] = 0.22

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "HUD text labels" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_requires_editorial_direction_contract(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"].pop("editorialDirection")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "editorialDirection object" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_fake_editorial_evidence_json(tmp_path):
    manifest = _passing_manifest(tmp_path)
    _write_json(tmp_path / "storage/qa/editorial-direction-plan.json", {"status": "pass"})

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "schema video-studio.editorial-pass.v1" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_stale_editorial_plan_fields(tmp_path):
    manifest = _passing_manifest(tmp_path)
    plan = _editorial_plan_payload()
    plan["motivatedCutPlan"][0]["cutReason"] = "payoff"
    _write_json(tmp_path / "storage/qa/editorial-direction-plan.json", plan)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "directing plan motivatedCutPlan must match manifest fields" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_editorial_scene_id_order_mismatch(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["editorialDirection"]["shotIntentMap"][1]["sceneId"] = "scene-999"

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "sceneId/order" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_editorial_cut_timing_mismatch(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["editorialDirection"]["motivatedCutPlan"][0]["cutAtSec"] = 9.0

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "cutAtSec" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_caption_tts_duplicate_in_editorial_plan(tmp_path):
    manifest = _passing_manifest(tmp_path)
    captions = manifest["postEditGoldenReference"]["editorialDirection"]["captionPerformance"]
    captions["timelineCues"][0]["text"] = captions["ttsSegments"][0]["text"]
    _write_editorial_plan_from_manifest(tmp_path, manifest)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "duplicate TTS" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_caption_tts_timeline_drift(tmp_path):
    manifest = _passing_manifest(tmp_path)
    captions = manifest["postEditGoldenReference"]["editorialDirection"]["captionPerformance"]
    captions["timelineCues"][1]["endSec"] = captions["ttsSegments"][1]["endSec"] + 0.55
    _write_editorial_plan_from_manifest(tmp_path, manifest)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "within 0.30s" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_unmotivated_editorial_cut(tmp_path):
    manifest = _passing_manifest(tmp_path)
    cut = manifest["postEditGoldenReference"]["editorialDirection"]["motivatedCutPlan"][0]
    cut["cutReason"] = "duration-ended"
    cut["visibleContinuityBridge"] = False
    cut["actionContinuesAcrossCut"] = False
    cut["unmotivatedHoldSec"] = 0.4

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "cutReason" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_unbound_editorial_sfx(tmp_path):
    manifest = _passing_manifest(tmp_path)
    cues = manifest["postEditGoldenReference"]["editorialDirection"]["audioVisualBinding"]["cues"]
    cues.append(
        {
            "type": "sfx",
            "sceneId": "scene-001",
            "startSec": 0.9,
            "bindingMode": "visible-action",
            "sourceEvent": "",
            "syncOffsetSec": 0.04,
            "assetPath": "assets/sfx/source-empty.wav",
            "decorativeOnly": False,
        }
    )
    _touch(tmp_path / "assets/sfx/source-empty.wav")
    _write_editorial_plan_from_manifest(tmp_path, manifest)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "visible source event" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_sfx_cue_without_audit_realization(tmp_path):
    manifest = _passing_manifest(tmp_path)
    cues = manifest["postEditGoldenReference"]["editorialDirection"]["audioVisualBinding"]["cues"]
    cues.append(
        {
            "type": "sfx",
            "sceneId": "scene-001",
            "startSec": 0.9,
            "bindingMode": "visible-action",
            "sourceEvent": "visible hand stops the source action",
            "syncOffsetSec": 0.04,
            "assetPath": "assets/sfx/missing-from-audit.wav",
            "decorativeOnly": False,
        }
    )
    _touch(tmp_path / "assets/sfx/missing-from-audit.wav")
    _write_editorial_plan_from_manifest(tmp_path, manifest)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "auditOperationId" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_requires_external_edit_elements_contract(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"].pop("externalEditElements")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "externalEditElements object" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_decorative_external_edit_elements(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()
    external = manifest["postEditGoldenReference"]["externalEditElements"]
    external["layerPurpose"]["decorativeOnly"] = True

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "decorative-only" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_unsafe_external_edit_overlay(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()
    external = manifest["postEditGoldenReference"]["externalEditElements"]
    external["safety"]["subjectOcclusion"] = True

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "subject occlusion" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_external_edit_missing_scene_coverage(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()
    external = manifest["postEditGoldenReference"]["externalEditElements"]
    external["perScenePlan"] = external["perScenePlan"][:1]

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "cover every scene" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_external_edit_scene_id_order_mismatch(tmp_path):
    manifest = _passing_manifest(tmp_path)
    external = manifest["postEditGoldenReference"]["externalEditElements"]
    external["perScenePlan"][1]["sceneId"] = "scene-999"

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "perScenePlan sceneId/order" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_requires_external_edit_perceptual_salience(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()
    external = manifest["postEditGoldenReference"]["externalEditElements"]
    external.pop("perceptualSalience")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "perceptualSalience object" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_external_warning_without_source_event_binding(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()
    salience = manifest["postEditGoldenReference"]["externalEditElements"]["perceptualSalience"]
    salience["warningBeatSourceEventBound"] = False

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "visible source event" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_too_small_semantic_external_cue(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()
    warning = manifest["postEditGoldenReference"]["externalEditElements"]["perScenePlan"][0]["elements"][0]
    warning["screenAreaRatio"] = 0.004

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "too small to be perceived" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_symbol_required_external_edit_default(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()
    salience = manifest["postEditGoldenReference"]["externalEditElements"]["perceptualSalience"]
    salience["recognizableSymbolRequired"] = True

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "must not require symbolic" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_active_external_elements_without_capcut_layers(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"]["externalEditElements"] = _active_external_edit_contract()

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "clean editorial mode cannot claim active external edit elements" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_requires_capcut_handoff(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["postEditGoldenReference"].pop("capcutHandoff")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "capcutHandoff object" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_ffmpeg_only_handoff(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["ffmpegOnlyAllowed"] = True
    handoff["ffmpegPreviewOnly"] = False

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "FFmpeg-only" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_missing_capcut_draft_artifact(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["draftContentPath"] = "storage/qa/capcut-draft/missing-draft_content.json"

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "CapCut handoff artifact missing" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_fake_capcut_audit_json(tmp_path):
    manifest = _passing_manifest(tmp_path)
    _write_json(tmp_path / "storage/qa/capcut-draft-audit.json", {"status": "pass"})

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "schema video-studio.capcut-draft-audit.v1" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_fake_capcut_draft_json(tmp_path):
    manifest = _passing_manifest(tmp_path)
    _write_json(tmp_path / "storage/qa/capcut-draft/draft_content.json", {"tracks": []})

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "draft_content.tracks" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_capcut_audit_draft_count_mismatch(tmp_path):
    manifest = _passing_manifest(tmp_path)
    audit = _capcut_draft_audit_payload()
    audit["trackCounts"]["video"] = 3
    _write_json(tmp_path / "storage/qa/capcut-draft-audit.json", audit)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "trackCounts" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_allows_clean_capcut_audit_without_effect_count_key(tmp_path):
    manifest = _passing_manifest(tmp_path)
    audit = _capcut_draft_audit_payload()
    audit["trackCounts"].pop("effect")
    _write_json(tmp_path / "storage/qa/capcut-draft-audit.json", audit)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "pass"
    assert report["renderAllowed"] is True


def test_golden_reference_gate_rejects_capcut_audit_keyframe_shortfall(tmp_path):
    manifest = _passing_manifest(tmp_path)
    audit = _capcut_draft_audit_payload()
    audit["actualVideoKeyframes"] = 4
    audit["totalMotionKeyframes"] = 4
    _write_json(tmp_path / "storage/qa/capcut-draft-audit.json", audit)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "keyframe count" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_zero_actual_keyframes_even_when_total_claimed(tmp_path):
    manifest = _passing_manifest(tmp_path)
    audit = _capcut_draft_audit_payload()
    audit["actualVideoKeyframes"] = 0
    audit["totalMotionKeyframes"] = 18
    _write_json(tmp_path / "storage/qa/capcut-draft-audit.json", audit)

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "keyframe count" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_weak_capcut_reference_basis(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["referenceBasis"] = ["CapCut draft exists"]

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "capcutHandoff.referenceBasis" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_unverified_capcut_automation_surface(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["automationSurface"]["capcutInstallVerified"] = False

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "capcutInstallVerified" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_requires_native_capcut_effect_pass(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff.pop("effectPass")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "capcutHandoff.effectPass object" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_effect_tracks_in_clean_editorial_mode(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["effectPass"]["effectTrackCount"] = 1
    handoff["effectPass"]["maxEffectTracks"] = 0
    handoff["mediaLinked"]["effectTracks"] = True

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "effectTrackCount must be 0" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_capcut_handoff_without_keyframed_motion(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["motionDesign"]["usesKeyframes"] = False
    handoff["motionDesign"]["minKeyframedElements"] = 0

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "usesKeyframes" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_capcut_handoff_without_editorial_motion_pass(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["motionDesign"].pop("editorialMotionPass")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "editorialMotionPass object" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_capcut_handoff_with_invisible_motion_delta(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["motionDesign"]["editorialMotionPass"]["minVisibleScaleDelta"] = 0.02

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "minVisibleScaleDelta" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_raw_capcut_preview_overlays_as_final(tmp_path):
    manifest = _passing_manifest(tmp_path)
    handoff = manifest["postEditGoldenReference"]["capcutHandoff"]
    handoff["motionDesign"]["noRawDrawboxDrawtextFinal"] = False

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "postEditGoldenReference" in report["failedChecks"]
    assert "noRawDrawboxDrawtextFinal" in report["checks"]["postEditGoldenReference"]["detail"]


def test_golden_reference_gate_rejects_black_or_caption_only_opening(tmp_path):
    manifest = _passing_manifest(tmp_path)
    cold_open = manifest["openingAudioContinuity"]["coldOpen"]
    cold_open["firstFrameHasPrimaryVisual"] = False
    cold_open["firstFrameIsBlack"] = True
    cold_open["captionOnlyOpening"] = True
    cold_open["blackScreenStartSec"] = 0.25

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "primary visual" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_rejects_caption_only_opening_even_without_black_screen(tmp_path):
    manifest = _passing_manifest(tmp_path)
    cold_open = manifest["openingAudioContinuity"]["coldOpen"]
    cold_open["firstFrameHasOnlySubtitleOrText"] = True

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "caption-only opening" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_rejects_placeholder_or_erased_bgm(tmp_path):
    manifest = _passing_manifest(tmp_path)
    audio_bed = manifest["openingAudioContinuity"]["audioBed"]
    audio_bed["bgmAudibleUnderVoice"] = False
    audio_bed["bgmNonPlaceholder"] = False
    audio_bed["bgmSourcePath"] = "lavfi:sine+anoisesrc-placeholder"
    audio_bed["bgmMeanVolumeDb"] = -39.0

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "BGM must remain audible" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_rejects_missing_audio_bridge_and_payoff_tail(tmp_path):
    manifest = _passing_manifest(tmp_path)
    continuity = manifest["openingAudioContinuity"]
    continuity["audioBridges"] = [{"mode": "hard-cut", "durationSec": 0.0}]
    continuity["payoffTail"]["finalVisualHoldSec"] = 0.2
    continuity["payoffTail"]["finalBgmTailSec"] = 0.1

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "at least 2 transition bridge" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_requires_tts_alignment_contract(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["openingAudioContinuity"].pop("ttsAlignment")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "ttsAlignment object" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_requires_tts_voice_quality_contract(tmp_path):
    manifest = _passing_manifest(tmp_path)
    manifest["openingAudioContinuity"]["ttsAlignment"].pop("voiceQuality")

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "voiceQuality object" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_rejects_windows_sapi_desktop_tts(tmp_path):
    manifest = _passing_manifest(tmp_path)
    voice_quality = manifest["openingAudioContinuity"]["ttsAlignment"]["voiceQuality"]
    voice_quality["provider"] = "windows-tts"
    voice_quality["voiceName"] = "Microsoft Heami Desktop"
    voice_quality["voiceClass"] = "desktop-sapi"

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "Windows SAPI/Desktop" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_rejects_tts_fallback_or_robotic_review(tmp_path):
    manifest = _passing_manifest(tmp_path)
    voice_quality = manifest["openingAudioContinuity"]["ttsAlignment"]["voiceQuality"]
    voice_quality["fallbackUsed"] = True
    voice_quality["perceivedRoboticOrSapi"] = True

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "fallback" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_requires_approved_evaluation_for_azure_or_melo_tts(tmp_path):
    manifest = _passing_manifest(tmp_path)
    voice_quality = manifest["openingAudioContinuity"]["ttsAlignment"]["voiceQuality"]
    voice_quality["provider"] = "azure-speech-f0"
    voice_quality["voiceName"] = "ko-KR-SunHiNeural"
    voice_quality["voiceClass"] = "neural"

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "approved candidate evaluation" in report["checks"]["openingAudioContinuity"]["detail"]

    voice_quality["candidateEvaluationStatus"] = "approved"
    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "pass"


def test_golden_reference_gate_rejects_tts_longer_than_video(tmp_path):
    manifest = _passing_manifest(tmp_path)
    alignment = manifest["openingAudioContinuity"]["ttsAlignment"]
    alignment["timelineDurationSec"] = 24.20
    alignment["narrationDurationSec"] = 26.09
    alignment["narrationStartSec"] = 0.50
    alignment["narrationEndSec"] = 26.59

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "exceeds video timeline" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_rejects_incomplete_final_tts_line(tmp_path):
    manifest = _passing_manifest(tmp_path)
    alignment = manifest["openingAudioContinuity"]["ttsAlignment"]
    alignment["finalSpokenLineComplete"] = False

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "complete every spoken line" in report["checks"]["openingAudioContinuity"]["detail"]


def test_golden_reference_gate_rejects_caption_voice_scene_desync(tmp_path):
    manifest = _passing_manifest(tmp_path)
    alignment = manifest["openingAudioContinuity"]["ttsAlignment"]
    alignment["sceneTimings"][1]["voiceEndSec"] = 6.10
    alignment["sceneTimings"][1]["sceneEndSec"] = 5.40

    report = evaluate_golden_reference_compliance(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert "openingAudioContinuity" in report["failedChecks"]
    assert "voice continues after the scene cut" in report["checks"]["openingAudioContinuity"]["detail"]


def test_compose_blocks_reference_render_before_ffmpeg_when_preflight_fails(tmp_path):
    manifest_dir = tmp_path / "storage/inputs/preflight-blocked"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "render-manifest.json"
    manifest = {
        "projectId": "preflight-blocked",
        "referenceStylePreset": "kr_curiosity_explainer",
        "renderDir": "storage/renders/preflight-blocked",
        "subtitleFilePath": "storage/renders/preflight-blocked/subtitles.ass",
        "concatFilePath": "storage/renders/preflight-blocked/concat.txt",
        "outputPath": "storage/renders/preflight-blocked/preflight-blocked.mp4",
        "scenes": [
            {
                "sceneId": "scene-001",
                "title": "Bad",
                "durationSec": 3.5,
                "visualKind": "video",
                "subtitleText": "설명문입니다",
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = compose_smoke_render(manifest_path=manifest_path, project_root=tmp_path)

    assert result.ok is False
    assert result.sceneClipPaths == []
    assert result.qualityReport is None
    assert result.goldenReferencePreflight is not None
    assert result.goldenReferencePreflight["renderAllowed"] is False
    assert (tmp_path / "storage/renders/preflight-blocked/golden-reference-preflight.json").exists()
    assert not (tmp_path / "storage/renders/preflight-blocked/preflight-blocked.mp4").exists()
