# Video Studio Domain Map

| Domain | Files | Owner | Notes |
|---|---|---|---|
| React UI | `app/**`, `shared/**`, `vite.config.ts` | CX | Run `npm run build` after UI or type changes. |
| Python worker | `worker/**`, `scripts/**`, `tools/**` | CX | Verify with focused pytest/compile checks; FFmpeg behavior is runtime-sensitive. |
| Render specs | `docs/RENDERING-SPEC.md`, `docs/REFERENCE-STYLE-GOLD-SAMPLES-20260615.md` | CC/CX | Keep quality gates and docs aligned. |
| Storage artifacts | `storage/**` | CC/CX | Treat large generated media as proof artifacts; avoid unrelated cleanup. |
| Provider/runtime config | `.env*`, provider keys, browser sessions | USER/CC | Agents must not edit secrets. |

## Verification

- Default static gate: `npm run build`.
- Worker changes: run focused `pytest` or `python -m compileall worker`.
- Render changes: produce a named proof artifact and QA summary.

