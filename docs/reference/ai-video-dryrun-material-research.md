---
title: AI Video Dry-Run Material Research
last_verified: 2026-06-23
sources:
  - https://blog.google/innovation-and-ai/products/google-flow-veo-ai-filmmaking-tool/
  - https://deepmind.google/models/veo/
  - https://ai.google.dev/gemini-api/docs/video
  - https://www.theverge.com/news/640821/runway-gen-4-artificial-intelligence-video-generator-filmmaking
aliases:
  - ai video dry-run material
  - ai video workflow source ledger
  - veo flow runway consistency
  - dry-run source observations
reliability: vendor-doc
refresh_trigger: when refreshing the dry-run preflight material, changing AI video source-generation gates, or replacing the sourceLedger observations for AI video production workflow material
---

# AI Video Dry-Run Material Research

This reference anchors the external observations used to upgrade the initial
dry-run preflight material from a search worklist into reusable source-ledger
evidence.

## Observations

| Source | Observation | Video Studio use |
|---|---|---|
| Google Flow announcement | Flow is positioned as an AI filmmaking tool for Veo, Imagen, and Gemini. The workflow emphasizes reusable ingredients, consistent subjects/scenes, camera controls, scenebuilder, and asset management. | The material should test whether Video Studio carries material, source, asset, and scene continuity through the gate chain before generation. |
| Google DeepMind Veo model page | Veo 3.1 is positioned around video plus audio, realism, prompt adherence, creative control, consistency, and audio-aware cinematic output. | The dry-run packet should not treat source generation as just "make a clip"; it must check prompt adherence, audio intent, camera/motion control, and continuity evidence. |
| Google AI for Developers Veo guide | Gemini API video generation requires an asynchronous operation/poll/download workflow and supports portrait video, extension, first/last-frame generation, and up to three image references. | The production gate should preserve async job readiness, artifact download/import proof, portrait format, reference-image count, and extension/continuity constraints. |
| The Verge on Runway Gen-4 | Reporting on Runway Gen-4 highlights the recurring AI-video failure of consistency across shots and says Gen-4 tries to address characters and objects across shots with reference images. | Consistency is a real material-quality and source-review concern; duplicate source prompts without reference continuity should remain blocked before final claims. |

## Source-Ledger Rule

For this material, a passing dry-run preflight can use these sources to justify
rough-cut readiness only. Final or publish readiness still requires reviewed
external generation artifacts, source import proof, full-watch review, and
release evidence.
