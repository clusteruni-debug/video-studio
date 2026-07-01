---
title: Video Studio Dashboard UX and Information Architecture Reference
last_verified: 2026-06-25
sources:
  - CapCut online video editor
  - Runway product
  - B-Script transcript-based B-roll editing research
  - AVscript accessible video editing research
aliases:
  - video studio dashboard
  - dashboard UX
  - dashboard IA
  - production workflow UI
  - video editor workflow
  - gate dashboard
reliability: primary
refresh_trigger: when changing Video Studio dashboard navigation, stage IA, gate presentation, material handoff, dry-run readiness report, source/edit/review workflow, operator task surfaces, or default production flow
---

# Video Studio Dashboard UX and Information Architecture Reference

This ledger anchors the reusable UX rule for the Video Studio dashboard. The
dashboard is a production workflow surface, not a collection of implementation
modules. Navigation must expose the operator's next production decision before
raw tools, logs, queues, or gate details.

## Reference History

Checked on 2026-06-23.

Updated on 2026-06-25 for the canonical production status read-model and
thin-loop proof contract.

| Source | URL | Reusable finding | Video Studio application |
|---|---|---|---|
| CapCut online video editor | `https://www.capcut.com/tools/online-video-editor` | The public workflow is presented as upload, edit/create, then export/share. The tool set includes text, music, sound effects, captions, filters, effects, and background removal inside the editing workflow. | Video Studio must lead with production stages instead of peer-level module tabs. Source, caption, audio, edit, and export actions belong inside the current stage. |
| Runway product | `https://runwayml.com/product` | Runway frames the product as one creative workflow spanning image, video, audio, editing, language models, storyboarding, visual effects, and apps for use-case-specific tools. | AI generation, storyboarding, editing, and review should appear as connected stages. Individual tools must not dominate the primary navigation unless they are the next production task. |
| B-Script | `https://arxiv.org/abs/1902.11216` | Transcript-centered B-roll recommendations helped novice editors insert B-roll faster and made videos more engaging in a controlled study. | Planning and script/scene structure should stay close to source decisions. B-roll/source work should be presented in relation to the story beat, not as a detached asset bin. |
| AVscript | `https://arxiv.org/abs/2302.14117` | Script-embedded visual content, visual errors, and speech information reduced mental demand and increased confidence for accessible editing. | Gates and review evidence should be summarized inline as status, blockers, and next actions. Raw JSON/details belong in advanced disclosure. |

## Dashboard Contract

The default dashboard navigation must be workflow-first:

1. `Home`: current production state and next action.
2. `Topic`: material discovery, topic candidate comparison, and readiness gates.
3. `Plan`: storyboard, script, scene timing, TTS, and copy quality.
4. `Sources`: source acquisition, generation, source review, and continuity.
5. `Edit`: captions, audio, rhythm, transitions, and render candidate creation.
6. `Review`: final candidate evidence, quality reports, and release decision.
7. `Advanced`: raw gates, batch jobs, debug, queues, and operational details.

Implementation modules such as `images`, `sources`, `gates`, `batch`, and
`jobs` must not appear as equal primary tabs in the default experience. They
can remain available inside workflow stages or under `Advanced`.

## Gate Presentation Rules

- A gate tab must not start as a raw JSON console. It should first show status,
  failed checks, next action, and a safe operator path.
- A topic stage must not start with validation when no material exists. It
  starts with discovery surfaces, candidate collection, and a blank scaffold;
  validation comes only after real sources and candidates are filled.
- Topic discovery must work without a user-provided keyword. Empty input means
  an auto-hot-topic discovery mode, not a disabled form. A typed keyword is a
  filter, not a prerequisite.
- Topic discovery must show visible candidate cards before validation. Search
  links alone are not enough; the operator needs a candidate-select path that
  can prefill the validation scaffold while still requiring real source URLs.
- Topic discovery must feed a local material library. The dashboard should let
  the operator save the selected material, sourceLedger evidence, research plan,
  duplicate signals, and gate history without introducing DB or remote storage.
- Saved materials must provide a production handoff path into the planning
  surface. The handoff should carry the material memo, central question,
  sourceLedger refs, storyboard seed, and source prompt bible seed so the
  operator does not copy the same material by hand.
- Candidate cards must be loaded through a bridge route when possible and must
  disclose whether they are live-source candidates or fallback/local candidates.
  A fallback card cannot be presented as a real-time trend result.
- Production-wide gate status belongs with the material record. The operator
  should be able to see which stage is blocked across material intake, source
  ledger, topic validation, storyboard, source acquisition, prompt quality,
  import review, edit assembly, render preflight, quality review, publish
  readiness, and post-publish learning.
- The canonical server read-model is `/api/production/status`. UI panels may
  keep a local fallback for stale bridge sessions, but when the bridge exposes
  this endpoint, Home and shared workflow gate panels must treat it as the
  source of truth for `nextAction`, workflow gate rows, active approval packet
  blockers, and thin-loop state.
- The thin production loop is exposed through `/api/production/thin-loop/status`
  and must stay stricter than generic render evidence: material, rough-cut
  dry-run, accepted source, render candidate, and phone review pass before
  final/publish work can proceed.
- The `Home` dashboard should surface material library totals, source-ledger
  coverage, topic-gate pass counts, and a stale-bridge warning when the running
  bridge does not expose the current material DB API.
- Before a real dry-run begins, the dashboard should expose one explicit
  preflight action that can create a seed material when the library is empty,
  build the rough-cut dry-run packet, run the readiness evaluator, and store a
  durable readiness report artifact.
- A dry-run readiness report is not a final quality claim. The dashboard must
  keep final/publish gates visually separate from rough-cut preflight and must
  show skipped final gates as a release boundary, not as upload readiness.
- Every workflow screen must expose the current production gate state, not only
  the tool controls for that screen. `Topic`, `Plan`, `Sources`, `Edit`,
  `Review`, and `Advanced` should all show pass, pending, and blocked gates
  before the operator acts.
- UI-level gate status must not overclaim final quality. When a runtime proof,
  phone review, publish packet, platform analytics, external generation, or
  CapCut export is missing, the dashboard should show pending or blocked rather
  than "done".
- Raw payloads, debug detail, and test fixtures must use progressive disclosure
  under an advanced section.
- A passing gate score is not a user-facing quality claim unless the dashboard
  also shows the evidence path, reviewed asset, or release boundary that the
  gate represents.
- When a reference search is requested, a durable reference document with
  `last_verified`, `sources`, `aliases`, `reliability`, and `refresh_trigger`
  must exist before that reference becomes a dashboard or gate rule.

## Redesign Acceptance Checklist

Use this checklist before claiming a Video Studio dashboard UX change is done:

- The first screen answers "what should I do next?"
- Primary navigation follows production order, not backend component names.
- Raw gates and batch queues are available but not the default mental model.
- Korean labels are concise and production-oriented.
- Stage cards or panels show current state, blockers, and the next movement.
- The `Topic` tab opens to material discovery before validation and never
  defaults to a passing sample packet.
- Empty topic input still opens hot-topic discovery surfaces and creates a
  blank validation scaffold tagged as auto-hot-topic.
- The discovery surface shows ranked candidate cards and selecting one changes
  the validation scaffold's selected topic.
- The discovery surface exposes a candidate refresh action, route source state,
  and fallback warning when live candidate loading fails.
- Each candidate exposes search, trend, video, and community verification links
  as a source worklist, but those links do not count as `sourceLedger` evidence
  until the operator records the real observation.
- The `Topic` stage may provide semi-automated `sourceLedger` drafting from the
  selected candidate's verification links, but every entry must still contain an
  operator-confirmed URL and observation. A search-result link alone is not
  evidence.
- The `Topic` stage exposes a material library save action so externally found
  material can accumulate with dedupe keys, sourceLedger evidence, research
  query plans, and gate history.
- The material library shows duplicate candidates and a production-wide gate
  snapshot before the operator moves into storyboard/source/edit/review work.
- The material library exposes a "planning memo" handoff action that writes the
  selected material packet into the production memo and moves the operator to
  planning.
- The material library and `Home` dashboard expose a dry-run preflight action
  that saves a material seed if needed, builds the dry-run packet from that
  material, and persists `packet.json`, `readiness-report.json`, and
  `summary.json` before any external generation or CapCut export starts.
- The dry-run readiness report surface shows `dryrunAllowed`,
  `generationAllowed`, `renderAllowed`, failed checks, artifact paths, and the
  release boundary that keeps final/publish evidence out of rough-cut preflight.
- The `Home` dashboard shows material DB / production gate status before the
  stage cards and links back to material discovery or planning.
- `Plan`, `Sources`, `Edit`, `Review`, and `Advanced` each render the shared
  production workflow gate panel so missing storyboard, source, prompt,
  render-preflight, quality-review, and publish-readiness evidence remains
  visible outside the raw gate tab.
- The shared workflow gate panel separates `통과`, `대기`, and `차단` states,
  and every row links to the production tab where that evidence is repaired.
- The shared workflow gate panel uses `/api/production/status` when available
  and must disclose local fallback state when the bridge is stale or offline.
- The thin-loop route rejects Grok `/c/*` redirects as source proof. Grok source
  proof must reach `/imagine` and still needs generation plus import evidence
  before it can pass the source-accepted stage.
- The dashboard must include a process-wide audit surface that checks every
  production stage against four anchors: dashboard surface, gate code anchor,
  test anchor, and required evidence. This is distinct from a runtime pass/fail
  result; it answers whether the gate layer itself is wired and reviewable.
- The material library must expose a material evaluation gate, not only a saved
  material count. The evaluation should score basic fields, sourceLedger depth,
  research-surface diversity, selected topic structure, candidate score basis,
  and topic-gate pass history.
- The three user-visible completion buckets are separate:
  1. dashboard UI workflow surfaces,
  2. process-wide gate audit and reviewability,
  3. material collection DB plus material evaluation gate.
- Candidate scores must disclose their basis. Freshness, existing source seed,
  surface coverage, longform fit, and selection priority can rank the worklist,
  but they do not replace the topic-discovery gate.
- After the topic gate passes, the dashboard should prepare the longform dry-run
  packet from that same topic packet so the operator does not re-copy JSON by
  hand.
- Source, caption, audio, edit, and review controls are grouped by production
  stage.
- The reference ledger query for dashboard UX returns this document.
- `tests/test_dashboard_ia_contract.py` passes. This is the source-level gate
  that rejects primary module-tab regression, non-Korean default guidance
  labels, undisclosed advanced raw panels, and missing dashboard reference
  metadata.
