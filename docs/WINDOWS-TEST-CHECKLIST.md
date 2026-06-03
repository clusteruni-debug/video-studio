# Video Studio — Windows Runtime Test Checklist

> Date: 2026-03-17
> Context: CX-3 (SFX), CX-4 (tests), CX-5 (provider dropdown) implemented + code review done.
> Never been runtime-tested end-to-end on Windows.

---

## 1. Environment Check (1 min)

- [ ] `cd C:\vibe\projects\video-studio`
- [ ] `.\.venv\Scripts\Activate.ps1`
- [ ] `ffmpeg -version`
- [ ] `ollama list` — qwen2.5:7b should be listed
- [ ] `pip show edge-tts` — if missing: `pip install edge-tts`

## 2. Build Check (2 min)

- [ ] `npm run build` — 0 errors
- [ ] `python -m compileall worker shared -q` — 0 errors
- [ ] `pytest tests/ -v` — 16/16 passed

## 3. Bridge Server (1 min)

- [ ] `npm run bridge` (= `python -m worker.bridge.server`)
- [ ] Console shows `{"ok": true, "service": "video-studio-local-bridge", "port": 5161}`
- [ ] Browser: `http://127.0.0.1:5161/api/health` → JSON response
- [ ] In response: `media.edge-tts.ready: true`

## 4. UI + Basic Flow (5 min)

- [ ] New terminal: `npm run dev` → open `http://127.0.0.1:5160`
- [ ] Enter prompt (e.g. "한국의 봄 여행지 소개 영상") → plan generated
- [ ] Storyboard shows scene cards
- [ ] **SFX card** visible (3 cards per scene: visual / audio / sfx)
- [ ] **Provider dropdown** visible ("비주얼 프로바이더" select per scene)

## 5. Render Test — Free Path (10 min)

**This is the most important test. Never done a full render before.**

- [ ] Save project → "저장 완료"
- [ ] Click "렌더 시작" (SSE streaming mode)
- [ ] Progress display works ("장면 1/N 렌더 중" etc.)
- [ ] `storage/renders/<project-id>/` has final MP4 file
- [ ] Play MP4 and check:

| Item | Expected | Result |
|------|----------|--------|
| Playback | Plays without crash | |
| Audio (TTS) | Korean Edge TTS voice heard | |
| Subtitles | Per-scene subtitles shown | |
| Visuals | uploaded/Pexels/Gemini Flash OR gradient fallback | |
| Motion | Ken Burns zoom/pan effects applied | |
| Transitions | Fade between scenes | |

## 6. Upload Asset Test (5 min)

- [ ] Upload an image file to one scene's visual card
- [ ] Upload a .wav file to one scene's SFX card
- [ ] Re-render → uploaded scene uses the uploaded image
- [ ] SFX-uploaded scene has sound effect mixed in audio

## 7. Provider Override Test (3 min)

- [ ] Keep paid providers disabled; uploaded/free-stock/Gemini Flash paths only
- [ ] Save + render → check that scene's request.json has `"adapter": "pollinations"`
- [ ] Check `storage/cache/<project-id>/<scene-id>/` for `.request.json` file

---

## Troubleshooting

### Bridge won't start
- Check `.env` file exists
- `pip show python-dotenv` — must be installed
- `netstat -ano | findstr 5161` — port conflict?

### TTS silent or error
- `pip show edge-tts` — must be installed
- Network required (Edge TTS calls MS server)
- Fallback: Edge TTS fail → Windows TTS → sine tone

### All visuals are placeholders
- Normal behavior when optional free stock/image providers are unavailable
- Check that gradient+motion fallback is applied (not flat cards)
- Future work: find stable free image generation path

### FFmpeg error
- `ffmpeg -version` to verify PATH
- Check `.env` for `VIDEO_STUDIO_FFMPEG_PATH` if needed
- In health API: `tools.ffmpeg.ready` should be true

---

## After Testing

**MP4 works + quality OK** -> next: wire local Wan or optional free image/stock sources

**MP4 works but quality poor** → next: improve fallback visuals (gradient→motion quality)

**Render fails/crashes** → capture error log, debug in next session
