# Troubleshooting

## Bridge Or Dashboard Does Not Start

Check:

- bridge port: `127.0.0.1:5161`
- dashboard port: `127.0.0.1:5160`
- `npm run bridge`
- `npm run dev`

If the UI cannot see new human-operator fields, restart the bridge. A running
bridge can be stale after code changes.

## Missing Rollup Optional Native Package

If `npm run build` fails inside WSL with a Rollup optional native package error,
do not treat that as proof that the app cannot run on Windows. Reinstalling
dependencies is a dependency/environment action and should be deliberate.

Use `./node_modules/.bin/tsc --noEmit` for source-level TypeScript validation
until the local dependency state is repaired.

## Missing Python Packages

If broad `pytest` collection fails because optional bridge packages are missing,
run focused no-provider tests first:

```bash
pytest -q tests/test_human_operator_p0_routes.py tests/test_dashboard_ia_contract.py
```

Do not mark runtime behavior verified from source tests alone.

## FFmpeg Missing

Symptoms:

- `GET /api/human-operator/render-health` returns `failureCategory=missing-ffmpeg`
- Demo Mode cannot render
- setup status lists FFmpeg as missing

Fix:

- install FFmpeg;
- ensure the shell running `npm run bridge` can see it;
- restart the bridge;
- refresh Home.

## Render Failure Categories

`GET /api/human-operator/render-health` separates:

- `missing-ffmpeg`
- `missing-source-file`
- `invalid-manifest`
- `subtitle-error`
- `audio-error`
- `write-permission`
- `active-approval-lock`
- `unknown`

Use the route's `repairActions` field before retrying.

## Source Proof Problems

Accepted source proof requires an operator decision.

Passes:

- local upload accepted by the operator;
- direct import accepted by the operator;
- browser generation proof only when generation and local import are both
  recorded.

Does not pass:

- browser preview only;
- Grok `/c/*` chat-thread redirect;
- generated-source intent without a local accepted file.

## Phone Review Blocks Publish

Publish packet readiness requires:

- render candidate path;
- at least one accepted source;
- full-watch phone review;
- captions, source fit, audio, pacing, and disclosure checks accepted.

Upload remains manual and operator-owned.

## Gemini 429

Gemini quota/rate errors are provider blockers, not local app success or failure.
Demo Mode and Manual Production must stay usable without Gemini.

## Grok Browser Proof

The accepted rail is the existing signed-in Chrome profile with recorded proof.
Do not claim success from:

- a fresh isolated browser profile;
- `/c/*` redirects;
- prompt field visibility without generation/import proof;
- downloaded files that were not imported and accepted.

## CapCut Export

CapCut automatic export is blocked unless the operator separately approves the
required UI automation dependency and workflow. Manual CapCut export can be
tracked as evidence, but the app must not claim repeatable automation by
default.
