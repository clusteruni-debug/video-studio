# Getting Started For Human Operators

This guide is for a user who cloned the repository and does not have Claude
Code, Codex, Gemini, Grok, CapCut automation, or paid provider access.

## Supported First Path

Use **Demo Mode** first.

Demo Mode proves that the local app can:

- start the Python bridge on `127.0.0.1:5161`;
- start the dashboard on `127.0.0.1:5160`;
- inspect Python, Node/npm, FFmpeg, and writable `storage/`;
- prepare a deterministic no-LLM demo packet;
- render a local draft with FFmpeg;
- keep publish readiness blocked until source review and phone review are
  recorded.

The demo output is a draft proof. It is not an upload-ready production video.

## Required Local Tools

- Windows 10/11
- Python environment used by `npm run bridge`
- Node.js and npm
- FFmpeg visible to the bridge process
- writable project `storage/`

Optional provider keys such as `GEMINI_API_KEY`, `PEXELS_API_KEY`,
`KLIPY_API_KEY`, and `FREESOUND_API_KEY` are not required for Demo Mode.

Paid providers stay blocked unless `VIDEO_STUDIO_ALLOW_PAID_PROVIDERS=1` is set
manually by the operator.

## Run

Optional report-only setup check:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-human-setup.ps1
```

This script does not install dependencies and does not edit `.env` files.

Terminal 1:

```powershell
npm run bridge
```

Terminal 2:

```powershell
npm run dev
```

Open:

```text
http://127.0.0.1:5160
```

## Dashboard Flow

1. Open `Home`.
2. Read `Human operator P0`.
3. Fix any first-run setup blocker shown by the panel.
4. Click `No-LLM demo prepare` if the demo packet is not prepared.
5. Open `Edit`.
6. Run the no-LLM demo render from `Render health and recovery`.
7. Open `Sources`.
8. Save at least one `Accepted-source review` decision for an operator-owned
   local source.
9. Open `Review`.
10. Save `Phone review and publish packet` evidence after watching the render on
    a phone-sized viewport.
11. Inspect the publish packet blockers.

Upload remains an operator-owned action. The app prepares evidence and packet
state only.

## API Reference For Local Smoke

- `GET /api/human-operator/status`
- `GET /api/human-operator/setup-status`
- `GET /api/human-operator/provider-readiness`
- `GET /api/human-operator/adapter-command-readiness`
- `GET /api/human-operator/worklist`
- `POST /api/human-operator/demo/prepare`
- `POST /api/human-operator/demo/render`
- `GET /api/human-operator/sources/status`
- `POST /api/human-operator/sources/review`
- `GET /api/human-operator/render-health`
- `POST /api/human-operator/phone-review`
- `GET /api/human-operator/publish-packet`
- `GET /api/human-operator/operator-blockers`

## Contributor Source Checks

Use these no-provider checks before claiming source-level completion:

```bash
python3 -m py_compile worker/bridge/routes_human_operator.py worker/bridge/human_operator_mvp.py
pytest -q tests/test_human_operator_p0_routes.py tests/test_dashboard_ia_contract.py
./node_modules/.bin/tsc --noEmit
```

`npm run build` and Windows runtime smoke are still required before a
human-operable release claim when the local dependency state supports them.
