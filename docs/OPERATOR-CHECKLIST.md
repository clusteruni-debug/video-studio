# Operator Checklist

## What Codex Can Do
- scaffold the project
- write the UI, worker, and routing code
- prepare local scripts and config samples
- wire together local and paid provider adapters
- add verification commands and smoke checks

## What You Must Do Manually
- install local tools on the machine
- create provider accounts
- accept gated model terms where required
- store API keys in local environment variables
- decide budget limits and provider usage rules

## Step-by-Step

### 1. Machine Prep
- install or keep Python 3.14 x64
- install FFmpeg and ensure `ffmpeg -version` works
- install Ollama and confirm the local service runs
- keep enough free disk space for model weights and cache

For this project, "installed" is not enough. The tools must also be callable from the shell that runs the app. Verify:
- `npm run bridge`
- `ffmpeg -version`
- `ollama --version`
- `hf --help`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-phase1.ps1`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-phase2.ps1`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-bridge.ps1`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-render.ps1`

If `ffmpeg` is installed via WinGet, the bridge may resolve it from the WinGet link location even when a plain shell `where ffmpeg` result is inconsistent. Trust the bridge health output over PATH-only checks.

### 2. Hugging Face Setup
- create or sign in to a Hugging Face account
- request access to:
  - FLUX.1-schnell
  - Wan2.1-T2V-1.3B-Diffusers
- create a personal access token with read scope
- log in locally with `hf auth login`

Do **not** send the token value in chat.

### 3. Optional Paid Providers
- OpenAI:
  - create or use an existing project
  - enable billing
  - create an API key for Sora 2 usage
  - set a low spend limit first
- Google:
  - enable Gemini API billing
  - create an API key only if Veo 3 is actually needed
  - keep Veo 3 disabled by default until a real premium use case exists

Do **not** send secret values in chat.

### 4. Local Paths to Prepare
- choose a stable model cache root, for example `C:\AI\models`
- choose a render root, for example `C:\AI\renders`
- decide whether the project should keep cache inside `projects/video-studio-app/storage/` or outside the repo
- confirm the sample output under `storage/inputs/verify-project-save/` is readable from the same shell

### 5. Decisions to Send Back
Reply with status values only:
- `Python314`: done / not done
- `FFmpeg`: done / not done
- `Ollama`: done / not done
- `HF access`: done / pending
- `OpenAI Sora2`: yes / no
- `Google Veo3`: yes / no
- `Monthly budget`: number in USD
- `Priority`: speed / cost / quality

If a tool is installed but not found on PATH, report it as `partial`.

## Recommended First Budget Rule
- default mode: local only
- premium allowance: one Sora 2 hero scene per project
- Veo 3: disabled unless a specific scene needs it
