# Deploy / Runtime - Video Studio

Video Studio is a local Windows runtime with a React/Vite UI and Python worker.

## UI

```powershell
npm run dev
npm run build
```

Default UI port: `5160` when launched through the workspace registry.

## Worker

```powershell
.venv\Scripts\python.exe -m worker.bridge.server
```

Render and source jobs write under `storage/**`.

## Environment

Use `.env.example` for names only. Agents must not edit `.env`.

## Smoke

1. `npm run build` passes.
2. Worker modules compile or focused tests pass for touched worker code.
3. One representative render proof is produced for render behavior changes.
4. QA summary and contact sheet are saved with the render artifact.
