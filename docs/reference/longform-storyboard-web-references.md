---
title: Longform Storyboard Web References
last_verified: 2026-06-21
sources:
  - https://support.google.com/youtube/answer/9884579?hl=en
  - https://support.google.com/youtube/answer/9314415?hl=en
  - https://support.google.com/youtube/answer/9314486?hl=en
  - https://arxiv.org/abs/2309.13952
  - https://arxiv.org/abs/2507.07202
  - https://www.vogue.com/article/the-return-to-long-form-why-youtube-is-winning-back-brands
reliability: vendor-doc
refresh_trigger: when longform storyboard, chapter, retention, or web-reference gate rules change
---

# Longform Storyboard Web References

This ledger turns external longform references into reusable Video Studio gates.
It is not a one-off research note for a single episode. The gate implementation
is `worker/render/production_mode_gate.py`, and the registry is
`config/gate-ontology.json`.

## Why Storyboard Comes First

Shortform production can often recover through source takes, captions, and edit
polish. A 10-minute target cannot. Longform needs a chaptered argument,
evidence placement, retention plan, and visual continuity before any Grok or
Gemini source generation starts.

The practical rule is:

1. Define the central question and viewer promise.
2. Build chapter markers and timed beats.
3. Bind evidence to visual beats before source prompts.
4. Lock visual continuity and provider roles.
5. Keep a durable web-reference ledger that maps sources to gate keys.

## Reference Ledger

| Source | Reliability | Gate use | Applied requirement |
|---|---|---|---|
| [YouTube Help: Video Chapters](https://support.google.com/youtube/answer/9884579?hl=en) | official-platform | `chapterMarkerGate`, `longformStoryboardGate` | Chapter markers must start at `00:00`, be ascending, include at least three timestamps, and use sections at least 10 seconds long. |
| [YouTube Help: Audience Retention](https://support.google.com/youtube/answer/9314415?hl=en) | official-platform | `retentionPlanGate`, `storyboardBeatCoverageGate` | The storyboard must plan the first 30 seconds, top moments, spikes, and dip-risk mitigations rather than reviewing retention only after upload. |
| [YouTube Help: Impressions and Watch Time](https://support.google.com/youtube/answer/9314486?hl=en) | official-platform | `retentionPlanGate` | Title/thumbnail expectation and average-view-duration intent must be explicit because discovery promises affect watch behavior. |
| [VidChapters-7M](https://arxiv.org/abs/2309.13952) | research-paper | `chapterMarkerGate`, `evidenceVisualBindingGate` | Long videos benefit from temporal segmentation, chapter title generation, and grounding chapters to the correct time span. |
| [Long-Video Storytelling Generation Survey](https://arxiv.org/abs/2507.07202) | research-paper | `visualContinuityBibleGate`, `storyboardBeatCoverageGate` | Current long-video generation has known consistency and motion-coherence problems, so source prompts must inherit one continuity bible. |
| [Vogue Business: The return to long-form](https://www.vogue.com/article/the-return-to-long-form-why-youtube-is-winning-back-brands) | secondary | strategy only | Use longform for deeper retention and narrative engagement; do not use this as a hard gate by itself. |

## Gate Translation

### `longformStoryboardGate`

Requires a storyboard object with a thesis or central question, viewer promise,
and at least 18 timed beats. This prevents a 10-minute episode from starting as
a stretched shortform scene list.

### `chapterMarkerGate`

Requires at least three markers, first marker at 0 seconds, ascending order,
minimum 10-second chapter spacing, marker titles, and valid chapter ids when ids
are provided.

### `retentionPlanGate`

Requires `first30SecPromise`, `titleThumbnailExpectation`, `topMomentPreview`,
and `dipRiskMitigations`. This keeps the opening, title promise, and risk beats
visible during storyboard review.

### `storyboardBeatCoverageGate`

Requires every beat to include `beatId`, `chapterId`, `startSec`, `durationSec`,
`visualIntent`, audio or narration intent, and `providerRole`. Every chapter
must be represented by at least one beat.

### `evidenceVisualBindingGate`

Requires each chapter to have evidence ids and at least one storyboard beat
whose `evidenceRef` binds that evidence to a visual/narrative beat.

### `visualContinuityBibleGate`

Requires shot language, color treatment, layout rules, style rules, and
recurring assets. This is the longform analogue of "same video, same camera,
same light, same visual system" across generated source clips.

### `webReferenceLedgerGate`

Requires at least four durable references. Each reference must include title,
URL, source type, retrieval date, takeaways, and applied gate keys. The ledger
must include at least one official-platform source and one research-paper
source, and it must cover every longform storyboard gate except itself.

## Non-Goals

- Do not copy long excerpts from references into production packets.
- Do not make episode-specific rules global.
- Do not treat secondary trade commentary as a hard pass/fail rule.
- Do not use a web-reference ledger as a substitute for full-watch review after
  render.
