# Operator Checklist

## What Codex Can Do
- scaffold the project
- write the UI, worker, and routing code
- prepare local scripts and config samples
- wire together local and paid provider adapters
- add verification commands and smoke checks

## What You Must Do Manually
- install local tools on the machine
- create provider accounts (only for premium features)
- store API keys in local environment variables
- decide budget limits and provider usage rules

## Step-by-Step

### 1. Machine Prep
- install or keep Python 3.14 x64
- install FFmpeg and ensure `ffmpeg -version` works
- install Ollama and confirm the local service runs
- pull the default planner model with `ollama pull qwen2.5:7b`
- keep enough free disk space for model weights and cache

For this project, "installed" is not enough. The tools must also be callable from the shell that runs the app. Verify:
- `npm run bridge`
- `ffmpeg -version`
- `ollama --version`
- `ollama list`

If `ffmpeg` is installed via WinGet, the bridge may resolve it from the WinGet link location even when a plain shell `where ffmpeg` result is inconsistent. Trust the bridge health output over PATH-only checks.

### 2. Zero-Cost Quick Start
With `GEMINI_API_KEY` set, the tool produces real content using:
- **Gemini 2.5 Flash Image** for AI images (free, 500/day)
- **Edge TTS** for narration (`pip install edge-tts` in project venv)
- **Local BGM** library from `assets/bgm/` (mood-matched)
- **FFmpeg** for composition with xfade transitions

Set these in your environment or `.env`:
```
GEMINI_API_KEY=your_key_here
VIDEO_STUDIO_GEMINI_FLASH_MODE=command
VIDEO_STUDIO_GEMINI_FLASH_COMMAND=["python", "scripts/gemini_flash_image.py", "--prompt-path", "{prompt_path}", "--output-path", "{output_path}"]
VIDEO_STUDIO_EDGE_TTS_MODE=command
VIDEO_STUDIO_LOCAL_BGM_MODE=command
```

See `.env.example` for full command templates.

### 3. Provider Setup by Category

#### Image Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Gemini 2.5 Flash Image | `GEMINI_API_KEY` | Free tier, 500 images/day |
| Imagen 4 | `GEMINI_API_KEY` | Paid ($0.02/img), same key |
| DALL-E 3 | `OPENAI_API_KEY` | OpenAI billing required |

#### Video Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Local Wan2.1 | `VIDEO_STUDIO_WAN_MODE=command` | Requires HF model download |
| Sora 2 | `OPENAI_API_KEY` | OpenAI billing, ~$0.10/sec |
| Veo 3 | `GOOGLE_API_KEY` | Google billing, ~$0.15/sec |

#### TTS Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Edge TTS | (none needed) | `pip install edge-tts`, free |
| Windows TTS | (none needed) | Windows only, built-in |
| ElevenLabs | `ELEVENLABS_API_KEY` | ElevenLabs account |
| OpenAI TTS | `OPENAI_API_KEY` | OpenAI billing |

#### BGM Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Local library | (none needed) | Place .mp3/.wav in `assets/bgm/` |
| Suno | `SUNO_API_KEY` | [UNCERTAIN] Suno subscription |

### 4. Cost Management
- **Free mode**: all providers use free tier, $0.00 cost
- **Standard mode**: free default, paid on per-scene approval
- **Premium mode**: paid providers preferred for high-priority scenes
- UI shows cost preview before render — paid scenes require explicit approval
- Monthly cap can be set in the UI budget controls

### 5. Local Paths to Prepare
- choose a stable model cache root, for example `C:\AI\models`
- render outputs go to `storage/renders/<project-id>/`
- scene asset files selected in the browser are copied into `storage/inputs/<project-id>/uploads/` when save/render triggers
- save writes `storage/cache/<project-id>/local-media-plan.json`
- render writes `storage/renders/<project-id>/local-media-report.json`

### 6. Verification Commands
```
npm run bridge          # start local Python bridge on port 5161
npm run dev             # build and serve UI on port 5160
ffmpeg -version         # confirm FFmpeg
ollama --version        # confirm Ollama
```

### 7. Decisions to Send Back
Reply with status values only:
- `Python314`: done / not done
- `FFmpeg`: done / not done
- `Ollama`: done / not done
- `Edge TTS`: done / not done
- `OpenAI key`: yes / no
- `Google key`: yes / no
- `ElevenLabs key`: yes / no
- `Monthly budget`: number in USD
- `Priority`: speed / cost / quality

## Recommended First Budget Rule
- default mode: free only (Gemini Flash Image + Edge TTS + local BGM)
- premium allowance: one paid image or video scene per project
- Sora 2 / Veo 3: disabled unless a specific scene needs it
