---
title: Topic Discovery And Community Signal Gate
last_verified: 2026-06-22
reliability: vendor-doc
sources:
  - https://trends.google.com/trending?geo=KR
  - https://datalab.naver.com/
  - https://support.google.com/youtube/answer/9314486?hl=en
  - https://support.google.com/youtube/answer/9884579?hl=en
  - https://support.google.com/youtube/answer/9002587?hl=en
  - https://www.businessinsider.com/new-youtube-features-could-help-creators-but-come-with-risks-2024-9
  - https://www.theverge.com/2024/9/18/24247559/youtube-ai-videos-veo-inspiration-tab
  - https://arxiv.org/abs/2201.11709
  - https://www.theguardian.com/media/2024/nov/26/online-influencers-need-urgent-fact-checking-training-warns-unesco
  - projects/video-studio/worker/render/topic_discovery_gate.py
  - projects/video-studio/tests/test_topic_discovery_gate.py
refresh_trigger: when selecting a new topic, changing source-discovery surfaces, changing currentness windows, or preparing longform storyboard/source generation
---

# Topic Discovery And Community Signal Gate

This gate exists because production quality cannot start at source prompts. A
video can have clean Grok/Gemini sources, good captions, and good edit rhythm
while still failing because the topic was arbitrary, stale, copied from one
community post, or too thin for longform.

The executable source is `worker/render/topic_discovery_gate.py`.

## External Basis

Use external sources as a balanced signal stack, not as a popularity contest:

- Google Trends Trending Now can be filtered to South Korea, recent windows,
  categories, active status, CSV export, clipboard export, RSS, and trend
  breakdowns. Use it for current attention and query-cluster evidence, not as a
  standalone truth source.
- Naver DataLab exposes Korean search trend, shopping insight, regional/news
  comment surfaces, period controls, daily/weekly/monthly ranges, device,
  gender, and age filters. Use it to cross-check Korean-language search demand.
- YouTube audience-retention guidance separates flat retention, declines,
  spikes, dips, first-30-second performance, title/thumbnail expectation, and
  top moments. Treat this as a planning input before longform storyboard, not
  only as post-publish analytics.
- YouTube chapters require ordered timestamp sections and make longform
  structure visible to viewers. A longform topic should have chapter-level
  promises before it enters storyboard.
- YouTube Analytics trend and inspiration surfaces can expose audience demand,
  content gaps, and video ideas. Use them as one video-discovery surface, then
  cross-check against search/trend and community surfaces.
- YouTube creator idea surfaces such as the Inspiration Tab are useful only as
  a creator-workflow signal. Secondary reporting says the tool can suggest
  ideas, titles, thumbnails, and outlines from catalog/comment/related-video
  context, which makes it useful for brainstorming but risky for sameness.
- Recommendation research such as OtherTube shows that recommendation exchange
  can help discovery and reflection, but it also highlights personalization
  limits. Do not rely on one account's feed as evidence of broad interest.
- UNESCO-related reporting on creators and misinformation is the safety anchor:
  creator popularity, likes, or views are not equivalent to fact quality.

## Required Packet

Every selected topic packet should provide:

- `evaluationDate`
- `targetLocale`
- `targetFormat`
- `researchQueryPlan`
- `sourceLedger`
- `topicCandidates`
- `selection.selectedTopicId`
- `selection.rejections`

The query plan is the research intent ledger. It proves that the operator
looked across the right surfaces before writing candidates. Each entry needs:

- `provider`
- `surface`
- `query`
- `intent`
- `capturedAt`

For current topic selection, the query plan must cover search, trend, video,
and community surfaces within the 14-day window. Korean targets need at least
one Korean-language query. Supported providers include manual browser search,
Google search, Google Trends KR, Naver DataLab, YouTube search, YouTube
Analytics trends, and Korean community scans. `agy-google-search` and
`agy-youtube-search` can be recorded only when an approved agy run produces
usable evidence; agy output is a research surface, not an authority.

The source ledger is durable research history. It must not be replaced by a
one-line note like "looked at community posts." Each entry needs:

- `sourceId`
- `sourceType`
- `title`
- `url`
- `capturedAt`
- `observation`
- optional `topicRefs`

Supported source types are deliberately generic:

- `google-search`
- `google-trends-kr`
- `manual-browser-search`
- `naver-datalab`
- `youtube-inspiration`
- `youtube-search`
- `youtube-analytics-trends`
- `agy-google-search`
- `agy-youtube-search`
- `platform-analytics`
- `korean-community`
- `korean-social`
- `community-forum`

The currentness window for those source types is 14 days. Older material can be
used as background evidence, but not as proof that a topic is currently alive.

The ledger also has an authenticity check. Source IDs must be unique, URLs must
be real HTTP(S) locations, and placeholder hosts such as `example.com`,
localhost, or dummy URLs are rejected. A passing ledger must include multiple
community/social source types, multiple search/trend source types, at least one
video discovery source, and at least one general search source.

## Candidate Evidence

Each topic candidate should include:

- `topicId`
- `workingTitle`
- `centralQuestion`
- `knowledgeGap`
- `whyNow`
- `viewerPromise`
- `communitySignals`
- `trendEvidence`
- `sourcePlan`
- `longformPlan`
- `riskReview`
- `originalityReview`

Community signals must reference at least two distinct community/social source
IDs. One loud post, one comment thread, or one platform's hot list is not enough.

Trend evidence must reference at least two source IDs and include at least one
official/search trend surface such as Google Trends KR, Naver DataLab, YouTube
Inspiration, or first-party platform analytics.

## Longform Fit

For `targetFormat=longform_10m`, the selected topic must have enough planned
depth before storyboard:

- at least 5 evidence/source references
- at least 6 chapters
- at least 18 segments
- at least 3 retention hooks
- a first-30-second promise
- a title/thumbnail expectation
- a top-moment preview
- at least 2 dip-risk mitigations
- chapter promises for at least 6 chapters
- not marked as `oneShotMemeOnly`

Shortform can use a smaller evidence requirement, but it still needs a real
question, cross-check, safety review, and candidate comparison.

Retention fields are required before storyboard because they shape whether the
topic can survive a 10-minute timeline. They should name what the opening
promises, what viewer expectation the title/thumbnail create, which moment is
worth waiting for, where dips may happen, and what each chapter resolves.

## Safety And Originality

Community interest is not permission to copy, accuse, expose, or amplify
unverified claims. The selected topic is blocked when:

- it depends on unresolved rumor
- it creates defamation risk
- it exposes private people or identifying details
- it attacks a protected class
- it introduces minor-safety risk
- it enters medical/legal/financial high-stakes territory without expert source
  planning
- it copies a single community post instead of making a transformative video

The required safe path is a fact-check plan, source attribution plan, and
transformative angle.

## Selection Matrix

The selected topic must beat at least two alternatives. The gate computes its
own score out of 100:

| Area | Max |
|---|---:|
| Community signal diversity | 20 |
| Trend/search cross-check | 15 |
| Curiosity angle | 15 |
| Source depth | 20 |
| Format fit | 15 |
| Safety and originality | 15 |

The minimum score is 75. A declared score is rejected if it does not match the
computed score. Every non-selected candidate must have a rejection reason.

Executable gates:

- `topicSourceLedgerGate`
- `researchQueryPlanGate`
- `sourceAuthenticityGate`
- `communitySignalDiversityGate`
- `trendCrossCheckGate`
- `curiosityAngleGate`
- `longformTopicFitGate`
- `audienceRetentionFitGate`
- `safetyOriginalityGate`
- `topicSelectionMatrixGate`

## Workflow Position

Topic discovery sits before:

1. reference ledger
2. packaging premise
3. storyboard
4. source prompt bible
5. Grok/Gemini source generation
6. longform E2E dry-run

`worker/render/longform_dryrun_readiness.py` re-evaluates this packet through
`dryrunTopicDiscoveryGate`. A longform dry-run must not start without it.
