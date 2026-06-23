---
last_verified: 2026-06-23
sources:
  - url: https://support.google.com/youtube/answer/14328491
    title: Disclosing use of GenAI content
    reliability: vendor-doc
  - url: https://support.google.com/youtube/answer/15447836
    title: Understanding How this content was made disclosures on YouTube
    reliability: vendor-doc
  - url: https://support.google.com/youtube/answer/15446725
    title: Building trust on YouTube Captured with a camera disclosure
    reliability: vendor-doc
  - url: https://support.google.com/youtube/answer/1311392
    title: YouTube channel monetization policies
    reliability: vendor-doc
---

# YouTube AI Disclosure Publish Gate Reference

Verified against YouTube Help on 2026-06-23.

## Gate Implications

- Upload candidates must include an explicit AI-use decision before publish.
- If the video realistically generates or meaningfully alters people, places,
  events, scenes, voice, music, or footage with AI, the publish packet must mark
  YouTube Studio AI use as `yes`.
- If the video does not require disclosure, the packet still needs a reviewer
  rationale explaining why the AI use is minor, non-realistic, production-only,
  or not present.
- Content Credentials/C2PA is separate from the manual upload disclosure. The
  packet must record whether C2PA metadata is absent, present, preserved, or
  externally verified.
- "Captured with a camera" is not a fallback claim. It only applies when C2PA
  2.1+ provenance-compatible capture tools preserve secure metadata and the
  audio/visual content has not been meaningfully altered.
- Monetization readiness needs an inauthentic-content review: the video must
  avoid mass-produced templates and must add original, authentic insight or
  educational/entertainment value.

## Required Publish Packet Fields

- `publishDisclosureReview.aiUseDecision`: `yes` or `no`.
- `publishDisclosureReview.realisticGenAiOrAltered`: boolean.
- `publishDisclosureReview.youtubeAiUseSelected`: boolean matching the decision
  when disclosure is required.
- `publishDisclosureReview.disclosureStatement`: operator-visible summary of
  the AI/synthetic/altered-content decision.
- `publishDisclosureReview.contentCredentialsStatus`: one of
  `not-present`, `present`, `preserved`, `verified`, `not-applicable`, or
  `unknown`.
- `publishDisclosureReview.viewerMisleadRiskReviewed`: true.
- `publishDisclosureReview.inaccurateAuthenticityClaim`: false.
- `publishDisclosureReview.inauthenticRiskReview.massProducedTemplate`: false.
- `publishDisclosureReview.inauthenticRiskReview.originalInsightAdded`: true.
- `publishDisclosureReview.inauthenticRiskReview.substantiveVariation`: true.
- `publishDisclosureReview.inauthenticRiskReview.metadataTruthful`: true.
