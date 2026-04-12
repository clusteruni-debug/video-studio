# Video Studio — DESIGN.md

> Last updated: 2026-04-12
> Persona: tool / production-studio / dense-panel
> Stack: Vite 7 + React 19 + TypeScript + vanilla CSS (no Tailwind)
> Port: 5160
> Scope: `projects/video-studio/app/ui/` — content automation tool UI

## Identity

The defining choice is **professional studio density with purple accent discipline**: every pixel serves the content production workflow. The UI is a desktop-class panel layout (sidebar + canvas + storyboard) that borrows from video editing tools — scene cards with numbered thumbnails, status pills, duration chips, and cost tracking in the top bar. Purple `#7c6cf0` is the single accent — used for selection states, active borders, brand logo, and the generate button. Status colors (success green, warning amber, error red) are strictly semantic, never decorative. Inter + Pretendard Variable for the body, JetBrains Mono for debug output. 14px base font for maximum information density without sacrificing readability.

## 1. Color Palette (3-layer token architecture)

Three layers in `app/ui/src/styles.css`: **primitive** (raw hex) → **semantic** (purpose aliases, already well-structured) → **component** (component-specific). Dark-only, `color-scheme: dark` on `:root`. The project already has 25 well-organized tokens — this refactor adds layer markers and a few missing tokens.

### Primitive (raw hex — mode-agnostic)

| Token | Value | Notes |
|---|---|---|
| `--color-neutral-950` | `#0c0c0e` | Deepest surface (body) |
| `--color-neutral-900` | `#141416` | Elevated panels (sidebar, top bar) |
| `--color-neutral-850` | `#1a1a1e` | Card surface |
| `--color-neutral-800` | `#222228` | Hover surface |
| `--color-neutral-750` | `#2a2a30` | Active surface / border |
| `--color-neutral-700` | `#1e1e24` | Subtle border |
| `--color-white` | `#ffffff` | Pure white (button text) |
| `--color-text-light` | `#e8e8ec` | Primary text (off-white) |
| `--color-text-mid` | `#8a8a96` | Secondary text |
| `--color-text-dim` | `#5c5c68` | Tertiary text |
| `--color-purple-500` | `#7c6cf0` | Brand accent |
| `--color-purple-600` | `#6b5ce0` | Accent hover (darker) |
| `--color-purple-500-dim` | `rgba(124, 108, 240, 0.12)` | Accent tint |
| `--color-green-500` | `#34c77b` | Success / ready |
| `--color-green-500-dim` | `rgba(52, 199, 123, 0.12)` | Success tint |
| `--color-amber-500` | `#e8a33c` | Warning / generating |
| `--color-amber-500-dim` | `rgba(232, 163, 60, 0.12)` | Warning tint |
| `--color-red-500` | `#e85454` | Error / delete |
| `--color-red-500-dim` | `rgba(232, 84, 84, 0.12)` | Error tint |

### Semantic (purpose aliases — single dark palette)

| Token | Points to | Meaning |
|---|---|---|
| `--bg-base` | `var(--color-neutral-950)` | App canvas |
| `--bg-elevated` | `var(--color-neutral-900)` | Sidebar, top bar, right panel |
| `--bg-surface` | `var(--color-neutral-850)` | Cards, inputs, history items |
| `--bg-hover` | `var(--color-neutral-800)` | Hover state bg |
| `--bg-active` | `var(--color-neutral-750)` | Active/pressed state bg |
| `--text-primary` | `var(--color-text-light)` | Main text |
| `--text-secondary` | `var(--color-text-mid)` | Secondary text, labels |
| `--text-tertiary` | `var(--color-text-dim)` | Meta, timestamps, dim info |
| `--border` | `var(--color-neutral-750)` | Standard dividers |
| `--border-subtle` | `var(--color-neutral-700)` | Subtle panel borders |
| `--accent` | `var(--color-purple-500)` | Brand accent — selection, focus, CTA |
| `--accent-dim` | `var(--color-purple-500-dim)` | Accent tint bg |
| `--accent-hover` | `var(--color-purple-600)` | Accent hover state |
| `--success` | `var(--color-green-500)` | Ready / connected / done |
| `--success-dim` | `var(--color-green-500-dim)` | Success tint bg |
| `--warning` | `var(--color-amber-500)` | Generating / checking |
| `--warning-dim` | `var(--color-amber-500-dim)` | Warning tint bg |
| `--error` | `var(--color-red-500)` | Error / offline / delete |
| `--error-dim` | `var(--color-red-500-dim)` | Error tint bg |
| `--radius-sm` | `8px` | Small radius (buttons, inputs) |
| `--radius-md` | `12px` | Medium radius (cards) |
| `--radius-lg` | `16px` | Large radius (panels) |
| `--sidebar-width` | `320px` | Sidebar panel width |

### Component (component-specific)

| Token | Value | Used by |
|---|---|---|
| `--top-bar-height` | `44px` | Top bar fixed height |
| `--scene-thumb-width` | `88px` | Scene card thumbnail width |
| `--scene-idx-opacity` | `0.15` | Scene number watermark opacity |

### Legacy aliases

Not needed. Token names are already semantic (`--bg-base`, `--text-primary`, `--accent`). No external consumers. The 5 `#fff` hardcoded sites will be replaced with `var(--color-white)` in the refactor commit.

## 2. Typography

### Font strategy decision: dual-font (body + mono)

Inter/Pretendard for all UI text (sidebar, scene cards, meta, buttons). JetBrains Mono for debug drawer output and technical readouts. The body font pair covers both Latin and Korean; Pretendard Variable is the Korean fallback.

### Font stack

- **Body / UI**: `"Inter", "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` — geometric sans for dense panel readability
- **Mono / Debug**: `"JetBrains Mono", "Fira Code", monospace` — debug drawer, command previews, bridge diagnostics

### Hierarchy

| Role | Size | Weight | Line height | Letter spacing | Usage |
|---|---|---|---|---|---|
| Top bar title | 0.88rem (~14px) | 600 | 1.5 | -0.01em | App name, project title |
| Section label | 0.75rem (~12px) | 500 | 1.5 | 0 | Sidebar field labels |
| Section header (uppercase) | 0.65–0.72rem | 600 | 1.2 | 0.1em | History label, collapse toggles, scene detail headers |
| Body | 14px (base) | 400 | 1.5 | 0 | Descriptions, scene narration |
| Small / meta | 0.78rem (~12px) | 400 | 1.5 | 0 | Timestamps, costs, provider names |
| Card title | 0.82rem (~13px) | 600 | 1.3 | 0 | Scene title, history item title |
| Debug mono | 0.72rem | 400 | 1.4 | 0 | Debug drawer output |
| Status pill | 10px | 600 | 1.2 | 0.02em | READY / GENERATING labels |
| Duration chip | 9px | 600 | 1.2 | 0.02em | Scene duration overlay |

### Numeric display

- `font-variant-numeric: tabular-nums` on all cost displays, duration readouts, scene counts, and status numbers
- Cost values use success green when positive, secondary text for neutral

## 3. Component States

### Button (generate — primary CTA)

| State | Background | Text | Border | Extra |
|---|---|---|---|---|
| default | `var(--accent)` | `#fff` | none | — |
| hover | `var(--accent-hover)` | unchanged | none | — |
| active | `var(--accent-hover)` | unchanged | none | — |
| disabled | `var(--accent)` | unchanged | none | `opacity: 0.5; cursor: not-allowed` |
| focus | default | unchanged | none | `outline: 2px solid var(--accent); outline-offset: 2px` |

### Scene card (list mode — scene-row)

| State | Background | Border | Extra |
|---|---|---|---|
| default | `var(--bg-surface)` | `1px solid var(--border-subtle)` | Action buttons hidden |
| hover | `var(--bg-hover)` | `1px solid var(--border)` | Action buttons visible |
| selected | `var(--accent-dim)` | `1px solid var(--accent)` | Accent tint bg + purple border |
| focus | unchanged | `1px solid var(--accent)` | `outline: 2px solid var(--accent)` |

### Input / Textarea

| State | Background | Text | Border | Extra |
|---|---|---|---|---|
| default | `var(--bg-surface)` | `var(--text-primary)` | `1px solid var(--border-subtle)` | — |
| hover | unchanged | unchanged | `1px solid var(--border)` | — |
| focus | unchanged | unchanged | `1px solid var(--accent)` | — |
| disabled | `var(--bg-hover)` | `var(--text-tertiary)` | `1px solid var(--border-subtle)` | `cursor: not-allowed` |

## 4. Agent Prompt Guide

```
You are building a feature for Video Studio (content automation tool). The design system is defined in DESIGN.md at project root. When writing UI code:

1. Use semantic tokens (--bg-*, --text-*, --accent, --success, --warning, --error) defined in DESIGN.md Section 1.
   - DO NOT use raw hex values — use var(--token)
   - Purple (#7c6cf0) is the ONLY accent color — use var(--accent)
   - Status colors are strictly semantic: green=ready, amber=generating, red=error
   - For accent hover, use var(--accent-hover) not a darker purple hardcode

2. Match the typography hierarchy in DESIGN.md Section 2.
   - Dense 14px base — do not increase font sizes without justification
   - Uppercase + letter-spacing 0.1em for section labels
   - tabular-nums for any cost, duration, or count display
   - JetBrains Mono only for debug/technical output

3. Every interactive component must implement states per Section 3.
   - Hover: bg/border change only (no transform/scale/shadow)
   - Action buttons: hidden by default, visible on hover (always visible on mobile)
   - Focus must be visible (outline + offset)

4. Layout: respect the shell structure (top bar → sidebar | canvas | right panel).
   - Sidebar width: var(--sidebar-width) = 320px
   - Top bar height: 44px fixed
   - Panels use var(--bg-elevated), content uses var(--bg-base)

5. Voice & tone: follow Section 5 — professional, concise, cost-transparent.

6. Follow `ui-ux-pro-max` skill for contrast, spacing, animation timing, accessibility.

7. Icons: lucide-react only. Never inline SVG for standard icons.
```

## 5. Voice & Tone

### Channel reference

| Channel | Tone | Example |
|---|---|---|
| Microcopy (button labels) | Direct, verb-first, professional | "Generate", "Save project", "Add scene" |
| Empty state | Helpful, actionable, brief | "No scenes yet. Enter a prompt and generate." |
| Error message | Honest, specific, recoverable | "Bridge offline. Check Python server is running." |
| Success confirmation | Subtle, non-intrusive | "Project saved" (inline, no toast) |
| Cost display | Transparent, always visible | "$0.08 est" — never hide costs |
| Loading / generating | Progress-oriented, status-pill | "GENERATING" with pulse dot animation |

### Microcopy rules

- Sentence case for labels and descriptions
- UPPERCASE only for status pills (READY, GENERATING, ERROR) and section collapse labels
- Always show estimated cost for paid operations before user confirms
- Provider names displayed in scene meta (Imagen 4, Pexels, Gemini Flash) for cost transparency
- No exclamation marks in UI labels
- "Bridge" (not "backend" or "server") for the Python connection — domain term

---

## Appendix — Hardcoded color audit

| File | Line | Old value | New token | Notes |
|---|---|---|---|---|
| `styles.css` | 206, 512, 899, 1254, 1379 | `#fff` | `var(--color-white)` | Button/overlay text (5 sites) |
| `styles.css` | 213, 903 | `#6b5ce0` | `var(--accent-hover)` | Generate button hover (2 sites) |
| `ImageCanvas.tsx` | 110 | `"#fff"` | inline — follow-up | Overlay text |
| `PaidConfirmDialog.tsx` | 150 | `"#fff"` | inline — follow-up | Dialog text |
| `SceneDetailPanel.tsx` | 155 | `"#fff"`, `"rgba(0,0,0,0.6)"` | inline — follow-up | Badge overlay |

CSS sites (7): replaceable now. TSX inline sites (3): follow-up.

## Appendix — Related assets

- Cross-project UX rules: `~/.claude/skills/ui-ux-pro-max/SKILL.md`
- From-scratch creation: `~/.claude/skills/frontend-design/SKILL.md`
- Global design rules: `C:\vibe\CLAUDE.md` Design Rules section
- Rollout plan: `C:\vibe\docs\plans\PLAN-DESIGN-MD-ROLLOUT.md`
- Rendering spec: `docs/RENDERING-SPEC.md` (composition rules, safe zones)
