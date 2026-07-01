---
plan_id: VIDEO-STUDIO-FRONTEND-ROADMAP
project: video-studio
status: SHIPPED
status_reason: Historical frontend roadmap archive; unchecked body checkboxes are retained as historical notes, not active work.
milestones:
  - { id: P1, label: "Script quality", done: true }
  - { id: P2, label: "Scene editing", done: true }
  - { id: P3, label: "Delete and cleanup actions", done: true }
  - { id: P4, label: "Progress and timing UX", done: true }
  - { id: P5, label: "Layout and UI polish", done: true }
  - { id: P6, label: "Image pipeline enhancement", done: true }
decisions_pending: []
blockers: []
depends_on: []
git_strategy: sub-repo
last_verified: 2026-06-26
drift_overrides:
  W3: historical_checklist_retained
ko_translation:
  status_reason_ko: "과거 프론트엔드 로드맵 아카이브이며, 본문 미체크 항목은 활성 작업이 아니라 역사 기록으로 유지한다."
  milestones_ko:
    - { id: P1, label_ko: "스크립트 품질" }
    - { id: P2, label_ko: "씬 편집" }
    - { id: P3, label_ko: "삭제 및 정리 액션" }
    - { id: P4, label_ko: "진행 및 시간 UX" }
    - { id: P5, label_ko: "레이아웃 및 UI 정리" }
    - { id: P6, label_ko: "이미지 파이프라인 강화" }
  decisions_pending_ko: []
  blockers_ko: []
---

# Video Studio App — Frontend Roadmap

Status: SHIPPED historical archive (created 2026-03-28, verified 2026-04-02, archive marker refreshed 2026-06-26)

Archive note 2026-06-26: this file is retained for historical context. The
unchecked task boxes below are not the active queue. Active Video Studio work is
tracked in `projects/video-studio/docs/IMPLEMENTATION-ROADMAP.md` and active
`projects/video-studio/docs/plans/PLAN-*.md` files.

---

## Priority 1: Script Quality (Blocker) — DONE (2026-04-02)

**Problem**: Groq prompt is ~150 tokens with no examples, no storytelling guidance. Output is shallow ("전쟁이 임" level).
> **Implemented**: Gemini primary, few-shot golden examples per template, two-step generation (script → image prompts), quality gate (score 0-10, retry if < 7), hook enforcement, CJK ideograph stripping, abstract image prompt filtering.

**Approach** (informed by open-source survey — ShortGPT 7.2k★, MPT-Extended):

### 1a. Few-shot examples per template
- Add 2-3 good script examples per template type in the prompt
- MPT-Extended uses 8 full examples and gets dramatically better output
- Each example: narration + display_text + image_prompt + emotion

### 1b. Multi-step generation (split script vs search terms)
- Step 1: Generate script (narration + structure)
- Step 2: Separate prompt for image search terms (concrete nouns, not abstract)
- ShortGPT pattern: "NEVER use abstract nouns, choose more objects than people"

### 1c. Quality gate (generate → evaluate → retry)
- After generation, score the script (0-10) with a second LLM call
- If score < 7, regenerate with feedback from evaluation
- ShortGPT is the only project implementing this — big differentiator

### 1d. Hook enforcement
- Scene 1 MUST follow "hook-problem-solution-CTA" structure
- OpenShorts pattern: force viral formula in structure

**Files**: `worker/bridge/scene_generator.py`, `worker/bridge/templates.py`

---

## Priority 2: Scene Editing (Core Missing Feature) — DONE (commit bbb8e84)

**Problem**: Generated scenes are read-only. User cannot edit narration, reorder, add, or delete scenes. "Generate and pray" — no iteration possible.

**Reference UI analysis** (from HEdbg0vaEAASMCQ.jpg):
- Scenes should be vertical list with full narration visible (not thumbnail grid)
- Narration/subtitle must be editable inline (click to edit)
- Scene detail should be right panel or inline-expandable (not separate tab)

**Tasks**:
- [ ] Switch StoryboardPanel from grid → vertical list with full text
- [ ] Make narration/display_text editable inline in scene cards
- [ ] Add "씬 삭제" button per scene
- [ ] Add "씬 추가" button (insert blank scene)
- [ ] Add scene reorder (up/down arrows)
- [ ] Add duration editor per scene (number input)
- [ ] Add TTS preview button per scene (audio player using `/api/tts/<file>`)
- [ ] Add "CapCut 내보내기" button (calls existing save_draft_to_capcut)
- [ ] Store edited scenes in context state (mutable copy of API response)

**Files**: `SceneDetailPanel.tsx`, `StoryboardPanel.tsx`, `StudioContext.tsx`, `server.py`

---

## Priority 3: Delete / Cleanup Actions — DONE (commit bbb8e84)

**Problem**: Batches, CapCut drafts, and jobs cannot be deleted from UI.

**Tasks**:
- [ ] Backend: `DELETE /api/batch/<id>`, `DELETE /api/jobs/<id>` endpoints
- [ ] Backend: `DELETE /api/draft/<id>` → remove draft folder from CapCut dir
- [ ] Wire delete buttons in BatchPanel, JobsPanel, StoryboardPanel
- [ ] "새로 시작" button to clear current draft

**Files**: `server.py`, `BatchPanel.tsx`, `JobsPanel.tsx`, `StoryboardPanel.tsx`, `StudioContext.tsx`

---

## Priority 4: Progress / Timing UX — DONE (commit ef23648)

**Problem**: No elapsed time or ETA during operations. "생성 중..." indefinitely.

**Tasks**:
- [ ] Elapsed timer on draft creation (Sidebar: "생성 중... 12s")
- [ ] Elapsed timer per image in ImageCanvas
- [ ] ETA for batch operations
- [ ] Pollinations retry count display

**Files**: `Sidebar.tsx`, `ImageCanvas.tsx`, `BatchPanel.tsx`

---

## Priority 5: Layout & UI Polish — DONE (commit f8e1cdc)

**Problem**: Tab pills cramped, layout doesn't match reference.

**Reference design principles** (from HEdbg0vaEAASMCQ.jpg):
- Script-first layout: vertical scene list with full narration
- 3-column: Sidebar (settings) + Center (script) + Right (scene detail/images)
- Content over decoration: readability > empty thumbnails

**Tasks**:
- [ ] Increase tab pill padding/min-width
- [ ] Add icons to tabs (Film, Image, Rss, Layers, Briefcase)
- [ ] Consider 3-column layout (sidebar + center + right detail panel)
- [ ] Duration/length selector in sidebar (30s / 1min / custom)
- [ ] "추가 지시" textarea (appended to LLM prompt)

**Files**: `styles.css`, `TopBar.tsx`, `Sidebar.tsx`, layout restructure

---

## Priority 6: Image Pipeline Enhancement — PARTIAL (Pollinations dead, Imagen 4 + Pexels active)

**Tasks**:
- [ ] Better image_prompt from Priority 1 improvements
- [ ] Pollinations FLUX for AI-generated images (already in .env)
- [ ] Image source toggle per scene (Pexels vs FLUX vs upload)
- [ ] Semantic video matching (MPT-Extended pattern)

**Files**: `SceneDetailPanel.tsx`, `ImageCanvas.tsx`, `server.py`

---

## UI Reference

Screenshot: `HEdbg0vaEAASMCQ.jpg` (Shorts Studio)

Detailed area-by-area mapping:

| Reference Area | Function | Our Status | Action |
|---------------|----------|------------|--------|
| Top tabs (Brief/Minutes/Drafts/Export) | Workflow phases | △ 5 tabs (different split) | Reorganize around workflow |
| Duration selector (30s/1min) | Target length | ❌ Missing | Add to sidebar |
| Title + Prompt (separate) | Split input | ❌ Prompt only | Add title field |
| "추가 지시" button | Custom LLM instructions | ❌ Missing | Textarea, append to prompt |
| AI / Translate toggle | Dub mode | △ Backend only | Add toggle |
| Script full-text view | Read full narration | ❌ Missing | Document-style view |
| Vertical scene list | Browse scenes | △ Grid cards (truncated) | Switch to vertical list |
| Inline narration editing | Edit scenes | ❌ Read-only | Click-to-edit |
| "+ 씬 추가" button | Insert scene | ❌ Missing | Add button |
| Scene duration editor | Adjust timing | ❌ Read-only | Number input |
| Image preview in detail | Per-scene image | △ Separate tab | Integrate into scene detail |
| TTS/music controls | Audio preview | △ Settings only | Audio player |
| Export button | CapCut export | ❌ Missing | Wire to save_draft_to_capcut |

---

## Open-Source Survey (2026-03-28)

Key projects analyzed: MoneyPrinterTurbo (53.7k★), ShortGPT (7.2k★), MoneyPrinterV2 (26.9k★), MPT-Extended, AutoShorts, OpenShorts, ViMax, MoneyPrinterPlus

**Findings**:
1. Most projects use surprisingly simple prompts (even 53k-star ones)
2. Quality differentiators: few-shot examples (MPT-Extended), generate-evaluate loop (ShortGPT), multi-step decomposition
3. Our tone preset system (5 types) is unique — no other project has this
4. Nobody does: emotion curve control, style transfer from reference, automatic hook quality scoring

Full analysis: `docs/research/ai-shorts-survey.md` (to be created)

---

## Session Mapping

| Session | Focus | Key Deliverable |
|---------|-------|-----------------|
| Next | Priority 1: Script quality | Few-shot examples + quality gate + multi-step generation |
| +1 | Priority 2: Scene editing | Editable scenes + vertical list + add/delete/reorder |
| +2 | Priority 3: Delete actions | 3 DELETE endpoints + UI buttons |
| +3 | Priority 4+5: UX polish | Timers + layout rework per reference |
| +4 | Priority 6: Image pipeline | FLUX integration + semantic matching |
