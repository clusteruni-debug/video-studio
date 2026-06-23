from __future__ import annotations

import json
from pathlib import Path

import pytest

from worker.render import capcut_handoff


def _touch(path: Path, data: bytes = b"asset") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _image(path: Path) -> None:
    _touch(path, b"\xff\xd8" + b"review-evidence" * 4 + b"\xff\xd9")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _editorial_direction_contract() -> dict:
    return {
        "required": True,
        "referenceBasis": [
            "YouTube Shorts timeline editing: text timing, audio, voiceover, and Shorts pacing",
            "CapCut caption and sound tools: editable captions plus sound effects matched to motion and scene changes",
            "Sound design research: SFX and foley must be synchronized to visible source events",
            "Short-form accessibility research: avoid dense on-screen text, rapid changes, and unrelated audio",
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
                "role": "answer",
                "viewerQuestionOrAnswer": "what action resolves the question",
                "visibleEvent": "final source action resolves the question",
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
                "cutAtSec": 2.0,
                "cutReason": "payoff",
                "visibleContinuityBridge": False,
                "newInformationRevealed": True,
                "actionContinuesAcrossCut": False,
                "unmotivatedHoldSec": 0,
            }
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
                }
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
                    "startSec": 0.20,
                    "endSec": 1.20,
                    "text": "첫 단서입니다",
                },
                {
                    "sceneId": "scene-002",
                    "startSec": 2.20,
                    "endSec": 3.20,
                    "text": "결론을 보세요",
                },
            ],
            "ttsSegments": [
                {
                    "sceneId": "scene-001",
                    "startSec": 0.22,
                    "endSec": 1.18,
                    "text": "처음 보이는 상태를 먼저 확인하세요.",
                },
                {
                    "sceneId": "scene-002",
                    "startSec": 2.18,
                    "endSec": 3.18,
                    "text": "마지막 변화까지 보고 판단하세요.",
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
        "reasonNoGeneratedExternalElements": "The default CapCut handoff keeps the edit clean and relies on visible source events, cuts, captions, BGM, and keyframed motion.",
        "rejectionBasis": [
            "Generated symbolic stickers are not quality proof.",
            "Generated SFX hits are rejected unless they bind to a visible source event.",
            "Effect counts are not a quality signal.",
        ],
        "perScenePlan": [
            {"sceneId": "scene-001", "elements": [], "reasonNoExternalElement": "hook source event remains readable without a symbol"},
            {"sceneId": "scene-002", "elements": [], "reasonNoExternalElement": "answer beat uses subject hold and BGM tail"},
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


def _reference_comparison_payload() -> dict:
    return {
        "schema": "video-studio.reference-comparison.v1",
        "status": "pass",
        "externalReferences": [
            {"source": "YouTube Shorts timeline editing", "usedFor": "text and music timing"},
            {"source": "Continuity editing", "usedFor": "cut motivation"},
        ],
        "noHudAbReviewed": True,
        "editImprovesComprehensionOverNoHud": True,
    }


def _score_payload() -> dict:
    dimensions = {
        "sourceTakeQuality": 70,
        "sourceSequenceContinuity": 70,
        "hookClarity": 70,
        "storyPayoff": 70,
        "copyTtsQuality": 70,
        "captionAccessibility": 70,
        "editRhythm": 70,
        "audioMix": 70,
        "colorTechnicalQuality": 70,
        "platformReferenceFit": 70,
    }
    return {
        "schema": "video-studio.post-edit-score.v1",
        "status": "pass",
        "computedScore": {"overall": 74, "dimensions": dimensions},
        "scoreInputs": {
            "shotIntentMap": True,
            "motivatedCutPlan": True,
            "captionPlan": True,
            "audioCueSheet": True,
            "capcutDraftAudit": True,
        },
    }


def _manifest(root: Path) -> Path:
    render_dir = root / "storage" / "renders" / "sample"
    source_dir = root / "storage" / "source"
    for idx in range(1, 3):
        _touch(source_dir / f"scene-{idx:03d}.mp4")
        _touch(render_dir / f"scene-{idx:03d}.tts.mp3")
    _touch(root / "assets" / "bgm" / "warm.wav")
    _touch(root / "assets" / "sfx" / "error-02.mp3")
    _touch(root / "assets" / "sfx" / "chime-03.mp3")
    _touch(root / "assets" / "sfx" / "whoosh-01.mp3")
    _touch(root / "assets" / "sfx" / "whoosh-04.mp3")
    _touch(root / "assets" / "sfx" / "resonance-03.mp3")
    _touch(root / "assets" / "sfx" / "bling-03.mp3")
    _image(root / "storage" / "qa" / "contact.jpg")
    _image(root / "storage" / "qa" / "first.jpg")
    _image(root / "storage" / "qa" / "caption.jpg")
    _write_json(root / "storage" / "qa" / "audio.json", {"status": "pass"})
    _write_json(root / "storage" / "qa" / "color.json", {"status": "pass"})
    _image(root / "storage" / "qa" / "final.jpg")
    _write_json(root / "storage" / "qa" / "score.json", _score_payload())
    _write_json(root / "storage" / "qa" / "external-plan.json", {"status": "pass"})
    _image(root / "storage" / "qa" / "external-preview.jpg")
    _write_json(root / "storage" / "qa" / "tts-review.json", {"status": "pass"})
    _write_json(root / "storage" / "qa" / "editorial-direction-plan.json", _editorial_plan_payload())
    _image(root / "storage" / "qa" / "editorial-phone-review.jpg")
    _write_json(root / "storage" / "qa" / "editorial-reference-comparison.json", _reference_comparison_payload())
    _image(root / "storage" / "qa" / "editorial-no-hud-ab.jpg")
    payload = {
        "projectId": "sample",
        "referenceStylePreset": "kr_curiosity_explainer",
        "goldenReferenceComplianceRequired": True,
        "sourceContactSheetPath": "storage/qa/contact.jpg",
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
                "entityContinuity": 70,
                "environmentContinuity": 70,
                "actionContinuity": 70,
                "cameraContinuity": 70,
                "lightingContinuity": 70,
                "styleContinuity": 70,
                "repairability": 70,
            },
            "topicSpecificCriteriaInGlobalGate": False,
        },
        "visualUnityTreatment": {
            "required": True,
            "appliesToAllScenes": True,
            "subjectSafe": True,
            "treatmentTypes": ["shared grade", "minimal frame"],
            "reviewChecklist": [
                "all scenes read as one package",
                "no subject occlusion",
                "no debug guide marks",
            ],
        },
        "openingAudioContinuity": {
            "coldOpen": {
                "firstFrameHasPrimaryVisual": True,
                "firstFrameIsBlack": False,
                "captionOnlyOpening": False,
                "firstFrameHasOnlySubtitleOrText": False,
                "blackScreenStartSec": 0.0,
                "firstVisibleActionSec": 0.2,
                "firstTwoSecReviewPath": "storage/qa/first.jpg",
            },
            "audioBed": {
                "bgmPresent": True,
                "bgmAudibleUnderVoice": True,
                "introBgmAudible": True,
                "outroBgmTailAudible": True,
                "bgmNonPlaceholder": True,
                "bgmSourcePath": "assets/bgm/warm.wav",
                "bgmMeanVolumeDb": -22,
                "audioMixEvidencePath": "storage/qa/audio.json",
            },
            "audioBridges": [{"mode": "sound-bridge", "durationSec": 0.25}],
            "payoffTail": {
                "finalBeatHasVisualResolution": True,
                "endingIsBlank": False,
                "blankOutroSec": 0,
                "finalVisualHoldSec": 1.0,
                "finalBgmTailSec": 1.0,
                "finalAudioFadeSec": 0.7,
                "finalTwoSecReviewPath": "storage/qa/final.jpg",
            },
            "ttsAlignment": {
                "required": True,
                "timelineReviewed": True,
                "timelineDurationSec": 4.0,
                "voiceTimelineSpanSec": 3.6,
                "narrationStartSec": 0,
                "narrationEndSec": 3.6,
                "voiceEndsBeforeVideoEndSec": 0.4,
                "maxCaptionVoiceDesyncSec": 0.2,
                "maxSceneVoiceOverflowSec": 0.0,
                "allVoiceLinesComplete": True,
                "finalSpokenLineComplete": True,
                "finalCaptionCoversFinalVoiceLine": True,
                "captionsDoNotAdvanceBeforeVoice": True,
                "voiceQuality": {
                    "required": True,
                    "provider": "edge-tts",
                    "voiceName": "ko-KR-SunHiNeural",
                    "voiceClass": "neural",
                    "ratePercent": 0,
                    "voiceNaturalnessReviewed": True,
                    "speechRateReviewed": True,
                    "fallbackUsed": False,
                    "perceivedRoboticOrSapi": False,
                    "candidateComparisonPath": "storage/qa/tts-review.json",
                },
                "sceneTimings": [
                    {
                        "sceneId": "scene-001",
                        "sceneStartSec": 0,
                        "sceneEndSec": 2,
                        "voiceStartSec": 0.1,
                        "voiceEndSec": 1.8,
                        "captionStartSec": 0.2,
                        "captionEndSec": 1.9,
                        "ttsDurationSec": 1.7,
                    },
                    {
                        "sceneId": "scene-002",
                        "sceneStartSec": 2,
                        "sceneEndSec": 4,
                        "voiceStartSec": 2.1,
                        "voiceEndSec": 3.6,
                        "captionStartSec": 2.2,
                        "captionEndSec": 3.7,
                        "ttsDurationSec": 1.5,
                    },
                ],
            },
        },
        "postEditGoldenReference": {
            "required": True,
            "referenceBasis": [
                "YouTube Shorts editing tips",
                "TikTok Creative Center Top Ads",
                "first three seconds hook",
                "short-form accessibility",
            ],
            "score": {
                "overall": 74,
                "minOverall": 72,
                "minDimension": 60,
                "dimensions": {
                    "sourceTakeQuality": 70,
                    "sourceSequenceContinuity": 70,
                    "hookClarity": 70,
                    "storyPayoff": 70,
                    "copyTtsQuality": 70,
                    "captionAccessibility": 70,
                    "editRhythm": 70,
                    "audioMix": 70,
                    "colorTechnicalQuality": 70,
                    "platformReferenceFit": 70,
                },
            },
            "firstThreeSecReviewPath": "storage/qa/first.jpg",
            "captionSafeZoneEvidencePath": "storage/qa/caption.jpg",
            "audioMixEvidencePath": "storage/qa/audio.json",
            "colorMatchEvidencePath": "storage/qa/color.json",
            "finalTwoSecReviewPath": "storage/qa/final.jpg",
            "scoringReviewPath": "storage/qa/score.json",
            "editorialDirection": _editorial_direction_contract(),
            "hook": {
                "firstThreeSecHasPrimaryVisual": True,
                "firstThreeSecHasMotionOrAction": True,
                "firstThreeSecHasAudioBed": True,
                "viewerQuestionClear": True,
                "firstCaptionStartSec": 0.3,
            },
            "captions": {
                "maxLines": 2,
                "maxCharsPerCaption": 20,
                "stableSafeZone": True,
                "mainSubjectOcclusion": False,
                "timelineReviewed": True,
                "maxScreenAreaRatio": 0.1,
            },
            "layoutHud": {
                "referenceBasis": ["YouTube Shorts", "TikTok Top Ads", "WCAG", "Netflix timed text"],
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
                    "textContrastRatio": 7.0,
                    "boxOpacity": 0.4,
                },
                "hud": {
                    "mode": "minimal-frame",
                    "opacity": 0.05,
                    "screenAreaRatio": 0.01,
                    "textLabels": False,
                    "debugMarks": False,
                },
                "transitions": {
                    "purposeDeclaredPerCut": True,
                    "beatAligned": True,
                    "decorativeOnlyTransitions": False,
                    "maxTransitionDurationSec": 0.2,
                },
            },
            "externalEditElements": _clean_external_edit_contract(),
            "rhythm": {
                "transitionCount": 1,
                "actionBeatsAlignedToCuts": True,
                "noHardJumpWithoutBridge": True,
                "minShotHoldSec": 1.2,
                "maxDeadAirSec": 0.2,
            },
            "audio": {
                "duckingApplied": True,
                "bgmContinuous": True,
                "sourceAmbienceOrFoleyPresent": True,
                "speechBgmSeparationReviewed": True,
                "fullMixMeanDb": -18,
            },
            "color": {
                "colorGradeAppliedToAllScenes": True,
                "noUnmotivatedFlashes": True,
                "maxLumaDelta": 0.2,
                "maxSaturationDelta": 0.2,
            },
            "payoff": {
                "finalAnswerResolved": True,
                "noNewInfoInLastSecond": True,
                "finalVisualHoldSec": 1.0,
                "finalAudioTailSec": 0.8,
            },
        },
        "scenes": [
            {
                "sceneId": "scene-001",
                "durationSec": 2,
                "visualKind": "video",
                "sourceType": "video",
                "sourcePath": "storage/source/scene-001.mp4",
                "subtitleText": "첫 장면",
                "narrationText": "첫 장면이에요.",
                "referenceEditRole": "hook-question",
                "layoutVariantKey": "headline-evidence",
                "sourceContract": {
                    "requiredObject": "primary subject",
                    "mustShow": ["primary subject"],
                    "forbidden": ["text overlay"],
                },
                "sourceQualityRubric": {
                    "required": True,
                    "minDimension": 60,
                    "dimensions": {
                        "promptIntentFit": 70,
                        "primarySubjectIntegrity": 70,
                        "actorOrManipulatorIntegrity": 70,
                        "actionReadability": 70,
                        "physicalPlausibility": 70,
                        "cameraGrammar": 70,
                        "lightingColorNaturalness": 70,
                        "temporalStability": 70,
                        "aiArtifactControl": 70,
                        "editability": 70,
                    },
                    "topicSpecificCriteriaInGlobalGate": False,
                },
                "promptContract": {
                    "camera": "vertical camera",
                    "action": "shows primary subject moving",
                    "mustShow": ["primary subject"],
                    "mustNotShow": ["caption text"],
                    "prompt": "Vertical camera shot showing primary subject moving.",
                },
                "captionContract": {"role": "hook-question", "maxLines": 2},
                "layoutContract": {
                    "captionZone": "top",
                    "fontSize": 60,
                    "enterTimingSec": 0.3,
                    "displayDurationSec": 1.2,
                    "mustNotCover": ["primary subject"],
                    "decorativeOverlayAllowed": False,
                },
                "ttsScriptContract": {
                    "role": "hook-question",
                    "tone": "natural Korean",
                    "maxKoreanCharsPerSec": 10,
                    "avoidOverFriendlyTone": True,
                },
            },
            {
                "sceneId": "scene-002",
                "durationSec": 2,
                "visualKind": "video",
                "sourceType": "video",
                "sourcePath": "storage/source/scene-002.mp4",
                "subtitleText": "둘째 장면",
                "narrationText": "둘째 장면이에요.",
                "referenceEditRole": "answer",
                "layoutVariantKey": "headline-evidence",
                "sourceContract": {
                    "requiredObject": "primary subject",
                    "mustShow": ["primary subject"],
                    "forbidden": ["text overlay"],
                },
                "sourceQualityRubric": {
                    "required": True,
                    "minDimension": 60,
                    "dimensions": {
                        "promptIntentFit": 70,
                        "primarySubjectIntegrity": 70,
                        "actorOrManipulatorIntegrity": 70,
                        "actionReadability": 70,
                        "physicalPlausibility": 70,
                        "cameraGrammar": 70,
                        "lightingColorNaturalness": 70,
                        "temporalStability": 70,
                        "aiArtifactControl": 70,
                        "editability": 70,
                    },
                    "topicSpecificCriteriaInGlobalGate": False,
                },
                "promptContract": {
                    "camera": "vertical camera",
                    "action": "shows primary subject moving",
                    "mustShow": ["primary subject"],
                    "mustNotShow": ["caption text"],
                    "prompt": "Vertical camera shot showing primary subject moving.",
                },
                "captionContract": {"role": "answer", "maxLines": 2},
                "layoutContract": {
                    "captionZone": "middle",
                    "fontSize": 58,
                    "enterTimingSec": 0.3,
                    "displayDurationSec": 1.2,
                    "mustNotCover": ["primary subject"],
                    "decorativeOverlayAllowed": False,
                },
                "ttsScriptContract": {
                    "role": "answer",
                    "tone": "natural Korean",
                    "maxKoreanCharsPerSec": 10,
                    "avoidOverFriendlyTone": True,
                },
            },
        ],
    }
    manifest_path = render_dir / "preflight-render-manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def test_build_capcut_handoff_injects_gate_contract(tmp_path, monkeypatch):
    manifest_path = _manifest(tmp_path)
    draft_root = tmp_path / "capcut-root"
    draft_root.mkdir()
    capcut_exe = tmp_path / "CapCut.exe"
    _touch(capcut_exe)

    calls = []

    monkeypatch.setattr(capcut_handoff, "create_capcut_draft", lambda width, height: (object(), "dfd_test"))
    monkeypatch.setattr(capcut_handoff, "vb_add_video", lambda *args, **kwargs: calls.append(("video", args, kwargs)) or True)
    monkeypatch.setattr(capcut_handoff, "vb_add_video_keyframes", lambda *args, **kwargs: calls.append(("keyframe", args, kwargs)) or True)
    monkeypatch.setattr(capcut_handoff, "vb_add_effect", lambda *args, **kwargs: calls.append(("effect", args, kwargs)) or True)
    monkeypatch.setattr(capcut_handoff, "vb_add_subtitle", lambda *args, **kwargs: calls.append(("text", args, kwargs)) or True)
    monkeypatch.setattr(capcut_handoff, "vb_add_image", lambda *args, **kwargs: calls.append(("image", args, kwargs)) or True)
    monkeypatch.setattr(capcut_handoff, "vb_add_narration", lambda *args, **kwargs: calls.append(("tts", args, kwargs)) or True)
    monkeypatch.setattr(capcut_handoff, "vb_add_bgm", lambda *args, **kwargs: calls.append(("bgm", args, kwargs)) or True)
    monkeypatch.setattr(capcut_handoff, "vb_add_audio_clip", lambda *args, **kwargs: calls.append(("sfx", args, kwargs)) or True)

    def fake_save(**kwargs):
        draft_dir = draft_root / "dfd_test"
        draft_dir.mkdir(parents=True)

        def keyframed_segment():
            return {
                "common_keyframes": [
                    {"keyframe_list": [{}, {}, {}]},
                    {"keyframe_list": [{}, {}, {}]},
                    {"keyframe_list": [{}, {}, {}]},
                ]
            }

        (draft_dir / "draft_content.json").write_text(
            json.dumps(
                {
                    "tracks": [
                        {"type": "video", "segments": [keyframed_segment(), keyframed_segment()]},
                        {"type": "audio", "segments": [{}, {}, {}]},
                        {"type": "text", "segments": [{}, {}, {}, {}]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return str(draft_dir)

    monkeypatch.setattr(capcut_handoff, "save_draft_to_capcut", fake_save)

    result = capcut_handoff.build_capcut_handoff(
        manifest_path,
        project_root=tmp_path,
        capcut_draft_dir=draft_root,
        capcut_exe=capcut_exe,
    )

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    handoff = updated["postEditGoldenReference"]["capcutHandoff"]
    assert Path(result.preflight_path).exists()
    assert handoff["automationSurface"]["tool"] == "VectCutAPI"
    assert handoff["automationSurface"]["capcutInstallVerified"] is True
    assert handoff["motionDesign"]["minKeyframedElements"] == 2
    editorial_motion = handoff["motionDesign"]["editorialMotionPass"]
    assert editorial_motion["mode"] == "capcut-scene-directed-motion"
    assert editorial_motion["sceneDirectedMotion"] is True
    assert editorial_motion["capcutKeyframesNotPreviewOnly"] is True
    assert editorial_motion["captionAnimationDesigned"] is True
    assert editorial_motion["sceneMotionProfileCount"] == 2
    assert editorial_motion["totalKeyframeCount"] == 18
    assert editorial_motion["minKeyframesPerScene"] == 9
    assert editorial_motion["minVisibleScaleDelta"] >= 0.05
    assert len(editorial_motion["motionProfiles"]) == 2
    assert handoff["mediaLinked"]["sfxTracks"] is False
    assert handoff["editModel"]["extraTextCalloutsAllowed"] is False
    assert handoff["editModel"]["editElementsUseNonTextVisuals"] is False
    assert handoff["editModel"]["nativeCapCutEffectsRequired"] is False
    assert handoff["editModel"]["generatedEffectLayersAllowed"] is False
    assert handoff["editModel"]["cleanEditorialMode"] is True
    assert handoff["effectPass"]["required"] is True
    assert handoff["effectPass"]["mode"] == "clean-editorial-no-canned-effects"
    assert handoff["effectPass"]["usesNativeCapCutEffects"] is False
    assert handoff["effectPass"]["nativeEffectsDisabled"] is True
    assert handoff["effectPass"]["generatedVisualEffectsDisabled"] is True
    assert handoff["effectPass"]["forbidPngOnlyClaim"] is True
    assert handoff["effectPass"]["visualBindingRequired"] is True
    assert handoff["effectPass"]["forbidUnanchoredEffects"] is True
    assert handoff["effectPass"]["forbidPresetSpray"] is True
    assert handoff["effectPass"]["cannedEffectsRejected"] is True
    assert handoff["effectPass"]["effectTrackCount"] == 0
    assert handoff["effectPass"]["maxEffectTracks"] == 0
    assert "atmosphere-light" in handoff["effectPass"]["disallowedUnanchoredFamilies"]
    assert handoff["mediaLinked"]["effectTracks"] is False
    assert handoff["mediaLinked"]["editElementTracks"] is False
    assert Path(handoff["draftContentPath"]).exists()
    assert Path(handoff["draftAuditPath"]).exists()
    keyframe_calls = [call for call in calls if call[0] == "keyframe"]
    assert len(keyframe_calls) == 2
    assert all(len(call[2]["property_types"]) == 9 for call in keyframe_calls)
    assert all(len(call[2]["times"]) == 9 for call in keyframe_calls)
    assert all(len(call[2]["values"]) == 9 for call in keyframe_calls)
    assert len([call for call in calls if call[0] == "sfx"]) == 0
    assert len([call for call in calls if call[0] == "image"]) == 0
    effect_calls = [call for call in calls if call[0] == "effect"]
    assert len(effect_calls) == 0
    text_values = [call[1][1] for call in calls if call[0] == "text"]
    assert text_values == ["첫 장면", "둘째 장면"]
    assert "X" not in text_values
    assert "OK" not in text_values
    assert "마시지 않기" not in text_values
    assert "새 물은 그늘에" not in text_values
    audit = json.loads(Path(handoff["draftAuditPath"]).read_text(encoding="utf-8"))
    beat_ops = [op for op in audit["operations"] if op["kind"] == "sfxBeat"]
    visual_ops = [op for op in audit["operations"] if op["kind"] == "editElementVisualCue"]
    effect_ops = [op for op in audit["operations"] if op["kind"] == "capcutEffectLayer"]
    motion_ops = [op for op in audit["operations"] if op["kind"] == "sourceMotionProfile"]
    assert len(motion_ops) == 2
    assert audit["totalMotionKeyframes"] == 18
    assert audit["transitionCount"] == 1
    assert len(audit["editorialMotionProfiles"]) == 2
    assert len(audit["captionAnimationProfiles"]) == 2
    assert len(beat_ops) == 0
    assert len(visual_ops) == 0
    assert len(effect_ops) == 0
    assert audit["effectTracks"] == 0
    assert audit["editElementTextLayers"] == 0
    assert audit["editElementVisualLayers"] == 0
    assert all(op["containsText"] is False for op in visual_ops)
    assert handoff["motionDesign"]["beatDesignedSfx"] is False


def test_build_capcut_handoff_rejects_draft_without_exported_keyframes(tmp_path, monkeypatch):
    manifest_path = _manifest(tmp_path)
    draft_root = tmp_path / "capcut-root"
    capcut_exe = tmp_path / "CapCut.exe"
    _touch(capcut_exe)

    monkeypatch.setattr(capcut_handoff, "create_capcut_draft", lambda width, height: (object(), "dfd_no_keyframes"))
    monkeypatch.setattr(capcut_handoff, "vb_add_video", lambda *args, **kwargs: True)
    monkeypatch.setattr(capcut_handoff, "vb_add_video_keyframes", lambda *args, **kwargs: True)
    monkeypatch.setattr(capcut_handoff, "vb_add_effect", lambda *args, **kwargs: True)
    monkeypatch.setattr(capcut_handoff, "vb_add_subtitle", lambda *args, **kwargs: True)
    monkeypatch.setattr(capcut_handoff, "vb_add_image", lambda *args, **kwargs: True)
    monkeypatch.setattr(capcut_handoff, "vb_add_narration", lambda *args, **kwargs: True)
    monkeypatch.setattr(capcut_handoff, "vb_add_bgm", lambda *args, **kwargs: True)
    monkeypatch.setattr(capcut_handoff, "vb_add_audio_clip", lambda *args, **kwargs: True)

    def fake_save(**kwargs):
        draft_dir = draft_root / "dfd_no_keyframes"
        draft_dir.mkdir(parents=True)
        (draft_dir / "draft_content.json").write_text(
            json.dumps({"tracks": [{"type": "video", "segments": [{}, {}]}]}),
            encoding="utf-8",
        )
        return str(draft_dir)

    monkeypatch.setattr(capcut_handoff, "save_draft_to_capcut", fake_save)

    with pytest.raises(RuntimeError, match="missing exported video keyframes"):
        capcut_handoff.build_capcut_handoff(
            manifest_path,
            project_root=tmp_path,
            capcut_draft_dir=draft_root,
            capcut_exe=capcut_exe,
        )
