---
title: Longform Workflow Stage Gate
last_verified: 2026-06-21
reliability: primary
sources:
  - projects/video-studio/worker/render/longform_workflow_gate.py
  - projects/video-studio/tests/test_longform_workflow_gate.py
  - projects/video-studio/config/gate-ontology.json
refresh_trigger: when changing longform production order, source-generation readiness, render-readiness, final-readiness, or workflow verification policy
---

# Longform Workflow Stage Gate

This gate fixes the production order for longform work. It does not replace
the production-mode gate, source-quality gates, post-edit gates, or final
readiness gates. It decides whether the project is allowed to advance to the
next stage.

## Required Order

`LONGFORM_WORKFLOW_STAGE_KEYS` is the canonical order:

1. `reference-ledger`
2. `packaging-premise`
3. `storyboard`
4. `script-tts`
5. `source-prompt-bible`
6. `source-generation`
7. `source-review-import`
8. `rough-cut`
9. `render-preflight`
10. `full-watch-review`
11. `final-readiness`
12. `derivative-clips`

All twelve stages must be present in this order. Later stages may be
`pending`, but they cannot be omitted, skipped, or moved earlier.

## Stage Evidence Contract

Every stage needs one explicit decision surface:

- `decisionRule`
- `exitCriteria`
- `acceptanceCriteria`

Any stage marked `pass`, `passed`, `complete`, `completed`, or `approved` also
needs:

- `evidenceRefs`
- `reviewerRole`

A self-asserted stage pass without evidence does not advance the workflow.

## Dependency Rules

Only one stage may be active at a time.

A stage can be `active`, `in_progress`, `blocked`, `failed`, or `pass` only
after all previous stages have passed. Required stages cannot be `skipped` or
`deferred`.

Specific dependency locks:

- `source-generation` cannot start before the reference ledger, packaging
  premise, storyboard, script/TTS plan, and source prompt bible pass.
- `render-preflight` cannot pass before source generation, source review/import,
  and rough cut pass.
- `final-readiness` cannot pass before full-watch review passes.
- `derivative-clips` cannot advance before final readiness passes.

## Allowed Flags

`evaluate_longform_workflow_gate()` returns three advancement flags:

- `generationAllowed`: true only after stages 1-5 pass.
- `renderAllowed`: true only after stages 1-9 pass.
- `finalAllowed`: true only after `final-readiness` passes.

If any workflow gate fails, all three flags are forced false.

## Improvement Loop

The packet must include a workflow improvement policy:

```json
{
  "workflowImprovementLoop": {
    "mutationLedgerPath": "storage/longform-workflow/mutation-ledger.json",
    "reviewCadence": "after every blocked, failed, or rough-cut review stage"
  }
}
```

If any stage is `blocked`, `failed`, `fail`, or `rejected`, that stage must
include at least one actionable mutation:

```json
{
  "stageKey": "storyboard",
  "status": "blocked",
  "improvementActions": [
    {
      "owner": "codex",
      "nextMutation": "replace weak beats with evidence-bound beats",
      "verificationCommand": "python -B -m pytest -q tests/test_longform_workflow_gate.py"
    }
  ]
}
```

This prevents a gate from only saying "failed" without defining the next
change and how it will be verified.

## Seeded Failure Suite

The workflow packet must include a `seededFailureSuite` with at least six
passing cases. It must cover the order, evidence, dependency, and improvement
loop gates. Each case needs:

- `caseId`
- `failureMode`
- `expectedGateKey`
- `fixtureRef` or `fixture`
- `verificationCommand` or `testName`
- `status: pass`

This keeps gate scores from becoming arbitrary. A new workflow gate or a
newly discovered failure mode should add a seeded failure case in the same
change.

## How This Composes With Other Gates

Use this order before source generation:

1. Build or refresh the external reference ledger.
2. Pass packaging and premise checks.
3. Pass storyboard and web-reference gates.
4. Pass script, caption, and TTS planning checks.
5. Write the source prompt bible and provider-role matrix.
6. Only then generate Grok/Gemini sources.

Before render:

1. Source generation must pass.
2. Imported sources must pass source review/import.
3. Rough cut must have retention, edit, audio, caption, and layout evidence.
4. Render preflight must pass production-mode and active packet locks.

Before final readiness:

1. A full-watch review must pass.
2. Final readiness and phone/human review gates must pass.
3. Derivative clips are created only after final readiness so short clips do
   not hide unresolved longform problems.

## Non-Goals

This gate does not:

- judge source visual quality by itself
- score TTS quality by itself
- replace post-edit/golden-reference gates
- automate Grok, Gemini, CapCut, or FFmpeg
- allow longform render because a stage list merely exists

The point is to make the order and improvement loop impossible to skip.
