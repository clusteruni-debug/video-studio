# Competitor UI/UX Analysis: Kling AI & Canva Video Editor

> Research date: 2026-03-17
> Purpose: Actionable design reference for Video Studio App

---

## Table of Contents

1. [Kling AI — Video Generation Interface](#kling-ai)
2. [Canva Video Editor — Editing Interface](#canva-video-editor)
3. [Cross-Product Patterns](#cross-product-patterns)
4. [Actionable Takeaways for Video Studio](#actionable-takeaways)

---

## Kling AI

### 1. Page Layout Structure

```
+-----------------------------------------------------------------------+
| TOP NAV BAR                                                           |
| Logo | Text-to-Video | Image-to-Video | AI Tools ▼ | Credits | Avatar|
+-----------------------------------------------------------------------+
|                                                                       |
|  +--LEFT PANEL (Settings)--+  +--CENTER (Preview/Results)----------+  |
|  |                         |  |                                    |  |
|  | [Model Selector]        |  |  Generated video preview           |  |
|  | [Mode: Std/Pro]         |  |  or                                |  |
|  | [Prompt Box]            |  |  Gallery of past generations       |  |
|  | [Negative Prompt]       |  |  or                                |  |
|  | [Aspect Ratio]          |  |  Empty state with examples         |  |
|  | [Duration]              |  |                                    |  |
|  | [Camera Movement]       |  |                                    |  |
|  | [Creativity Slider]     |  |                                    |  |
|  | [Image Upload]          |  |                                    |  |
|  |                         |  |                                    |  |
|  | [=== GENERATE BTN ===]  |  |                                    |  |
|  |                         |  |                                    |  |
|  +-------------------------+  +------------------------------------+  |
+-----------------------------------------------------------------------+
```

- **Left panel**: ~320-360px wide, scrollable settings column
- **Center area**: Flexible width, houses the preview player or generation gallery
- **No right panel** in the generation view (right panel appears only in Kling O1 editing mode)
- **Dark theme throughout** — deep dark backgrounds with subtle borders

### 2. Prompt Input Area

| Property | Detail |
|----------|--------|
| **Position** | Left panel, prominent placement near top (below model/mode selectors) |
| **Size** | Full panel width (~300px), multi-line textarea, approximately 120-150px tall |
| **Placeholder** | "Describe the video you want to create..." (guiding text) |
| **Character guidance** | Recommends < 50 words for optimal results |
| **Negative prompt** | Separate collapsible text area below the main prompt, labeled "Negative Prompt" |
| **Prompt suggestions** | "Refresh" button in the bottom-right corner of the prompt box generates random prompt ideas |
| **Attachments** | Image upload area (drag-and-drop zone) available in Image-to-Video mode — appears as a bordered dashed-outline upload zone above the prompt |
| **Prompt enhancement** | AI-assisted prompt improvement button (sparkle/wand icon) |

### 3. Generation Settings Organization

Settings are stacked vertically in the left panel, each as a distinct section with label + control:

#### Model & Mode Selection
- **Model selector**: Dropdown showing model version (e.g., "Kling 3.0", "Kling 2.6")
- **Mode toggle**: Two-option pill toggle — "Standard" (faster, lower cost) vs "Professional" (higher fidelity, slower)
- Professional mode shows credit cost difference inline

#### Aspect Ratio
- **Control type**: Icon-based toggle group (3 options side by side)
- **Options**: `16:9` (landscape icon), `9:16` (portrait icon), `1:1` (square icon)
- Each option shows a visual rectangle preview of the ratio
- Default: 16:9

#### Duration
- **Control type**: Segmented button / pill toggle
- **Options**: `5s` | `10s` (Kling 2.x), extended to `3-15s` in multi-shot mode (Kling 3.0)
- Credit cost displayed next to each option

#### Camera Movement
- **Control type**: Dropdown selector or grid of preset thumbnails
- **6 Basic movements**: Pan Left, Pan Right, Tilt Up, Tilt Down, Zoom In, Zoom Out
- **4 Master shots**: Dolly, Orbit, Tracking, Crane
- **20+ advanced presets** in Kling 3.0 Motion Control: push-ins, jibs, dollies with customizable speed and trajectory
- **Static option**: "Fixed Lens" — camera remains completely still
- Each movement option shows a small animated preview icon

#### Creativity vs Relevance Slider
- **Control type**: Horizontal slider with labeled endpoints
- **Left label**: "Creative" (AI takes artistic liberties)
- **Right label**: "Relevance" (strict adherence to prompt)
- **Optimal range**: 0.65-0.75 for professional use
- **Default**: Center-balanced

### 4. Results / Gallery Display

#### During Generation (Waiting State)
- **Progress indicator**: Circular or horizontal progress bar with percentage (0-100%)
- **Known issue**: Progress can freeze at 99% for free-tier users
- **Queue display**: Shows estimated wait time; paid users get priority
- **Typical times**: 3-5 min (simple, paid), up to hours/days (free tier, peak)
- **Animation**: Subtle pulsing or shimmer animation on the progress area

#### Completed Results
- **Preview player**: Video plays inline in the center panel with standard controls (play/pause, scrubber, fullscreen)
- **Download button**: Prominent button below/beside the video — exports clean MP4 (watermark-free for paid)
- **Regenerate**: Option to regenerate with same or modified settings
- **Gallery/History**: "My Creations" section accessible from navigation — grid layout of thumbnail cards showing generated videos
- **Community gallery**: Browse other users' creations with "Clone" button to copy settings

#### Gallery Card Layout
- Thumbnail preview (auto-playing on hover)
- Duration badge overlay (bottom-right)
- Prompt snippet (truncated, 1-2 lines below thumbnail)
- Download / Share / Delete actions

### 5. Color Values (Estimated from Dark Theme)

| Element | Approximate Color |
|---------|------------------|
| **Page background** | `#0d0d0f` to `#121215` (near-black with slight blue-purple tint) |
| **Panel/card background** | `#1a1a1f` to `#1e1e24` |
| **Elevated surface** | `#252530` |
| **Border / divider** | `#2a2a35` to `#333340` (subtle, low-contrast) |
| **Primary text** | `#e8e8ed` to `#f0f0f5` (off-white) |
| **Secondary text** | `#8a8a95` to `#9999a5` |
| **Placeholder text** | `#555560` |
| **Accent / primary action** | Blue-purple gradient `#4c6ef5` -> `#7c3aed` or similar |
| **Success / completed** | `#22c55e` (green) |
| **Warning / credits** | `#f59e0b` (amber) |
| **Error** | `#ef4444` (red) |

### 6. Button Styles

| Button Type | Style |
|-------------|-------|
| **Generate (Primary CTA)** | Full-width within left panel, ~44-48px height, blue-purple gradient background, white text, `border-radius: 8-12px`, subtle glow/shadow effect, shows credit cost ("10 credits"), disabled state grays out |
| **Secondary actions** | Ghost/outline style — transparent background, 1px border matching accent color, accent-colored text, `border-radius: 8px` |
| **Toggle pills** | Rounded pill shape (`border-radius: 20px`), selected state filled with accent, unselected is ghost/transparent |
| **Icon buttons** | 32-36px square, transparent bg, icon in secondary text color, hover brightens |
| **Dropdown triggers** | Dark background, subtle border, chevron indicator, `border-radius: 8px` |

### 7. Waiting / Generation State

- Left panel: "Generate" button transforms to show progress — may show spinning indicator or disable with "Generating..." text
- Center panel: Placeholder card appears with progress animation
- **Progress bar**: Linear bar or circular spinner showing 0-100%
- **Queue position**: Text indicator like "Position in queue: #3"
- **Time estimate**: "Estimated time: ~3 minutes"
- Cancel generation button appears during the wait
- Multiple generations can be queued simultaneously (paid users)

### 8. Scene / Shot Management (Kling 3.0 Multi-Shot)

```
+--STORYBOARD PANEL (replaces simple prompt in multi-shot mode)--------+
|                                                                       |
|  [Smart Storyboard] | [Custom Storyboard]  <-- mode tabs              |
|                                                                       |
|  +--Shot 1--+  +--Shot 2--+  +--Shot 3--+  +--Shot 4--+  [+ Add]    |
|  | Thumb    |  | Thumb    |  | Thumb    |  | Thumb    |              |
|  | preview  |  | preview  |  | preview  |  | preview  |              |
|  +----------+  +----------+  +----------+  +----------+              |
|                                                                       |
|  Selected Shot Details:                                               |
|  [Shot prompt textarea                                    ]           |
|  [Camera movement: dropdown     ] [Duration: 3s          ]           |
|  [Start frame: upload ] [End frame: upload ]                         |
+-----------------------------------------------------------------------+
```

- **Smart Storyboard**: AI automatically breaks a narrative prompt into 2-5 shots with optimal camera angles
- **Custom Storyboard**: Manual per-shot control
- **Shot cards**: Horizontal scrollable row of shot thumbnails (each ~80-100px wide)
- **Per-shot controls**: Individual prompt, camera movement, duration, start/end reference frames
- **Shot limit**: 2-6 shots per generation, total 3-15 seconds
- **Consistency**: AI maintains character/environment/lighting consistency across shots automatically
- **Transitions**: Automatic camera transitions between shots (shot-reverse-shot, smooth panning)

---

## Canva Video Editor

### 1. Page Layout Structure

```
+-----------------------------------------------------------------------+
| TOP MENU BAR                                                          |
| [Back] | Design Title (editable) | Undo/Redo | [Preview] [Share ▼]   |
+-----------------------------------------------------------------------+
| LEFT     |  CANVAS / PREVIEW AREA                     | CONTEXTUAL   |
| SIDEBAR  |                                             | TOOLBAR      |
| (tabs)   |  +-------------------------------+         | (appears     |
|          |  |                               |         |  on element  |
| Design   |  |    Video Preview              |         |  selection)  |
| Elements |  |    (16:9 or selected ratio)   |         |              |
| Text     |  |                               |         |              |
| Uploads  |  +-------------------------------+         |              |
| Photos   |                                             |              |
| Audio    |                                             |              |
| Brand    |  +--FLOATING TOOLBAR (contextual)--+       |              |
| Apps     |  | [font] [size] [B] [I] [color]   |       |              |
|          |  +----------------------------------+       |              |
+----------+-----------+------------------------------------+-----------+
|                    TIMELINE (Multi-Track)                              |
| [Play] [<<] [>>] [Time: 0:00/1:30]        [Zoom -][===][+]          |
| +-----------------------------------------------------------------+   |
| | Video Track   | [clip1    ] [clip2        ] [clip3   ]          |   |
| | Text Track    |     [Title ][       Subtitle      ]            |   |
| | Audio Track   | [~~waveform~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~]   |   |
| | FX Track      |        [transition]        [transition]        |   |
| +-----------------------------------------------------------------+   |
+-----------------------------------------------------------------------+
```

- **Left sidebar**: ~72px collapsed (icon rail) / ~300px expanded (with content panel)
- **Canvas area**: Flexible center, maintains aspect ratio of the project
- **Timeline**: Bottom section, ~150-200px default height, resizable
- **No persistent right panel** — uses floating contextual toolbar instead

### 2. Left Panel Organization

#### Tab Structure (Top to Bottom Icon Rail)

| Tab | Icon | Content When Expanded |
|-----|------|-----------------------|
| **Design** | Grid/Layout icon | Templates, styles, layouts for the current format |
| **Elements** | Shapes icon | Shapes, lines, frames, graphics, stickers, charts — searchable with categories |
| **Text** | "T" icon | Heading/subheading/body presets, font combinations, animated text templates, brand kit fonts |
| **Uploads** | Upload/arrow icon | User-uploaded images, videos, audio — drag-and-drop upload zone at top |
| **Photos** | Image icon | Stock photo library (Canva's built-in + third-party integrations) |
| **Videos** | Play icon | Stock video library |
| **Audio** | Music note icon | Royalty-free music tracks, sound effects — preview on hover, waveform visible |
| **Brand** | Building icon | Brand kit (Pro feature) — logos, colors, fonts |
| **Apps** | Grid/puzzle icon | Third-party integrations, AI tools (Magic Write, AI image generation, etc.) |

#### Panel Behavior
- Clicking a tab icon expands a ~240-280px content panel to the right of the icon rail
- Clicking the same tab again collapses the panel
- Panel includes search bar at top for most tabs
- Content is organized in scrollable grid or list format
- Items are draggable directly onto the canvas
- Hover states show quick preview or info tooltip
- Close icon ("X") appears on hover for removing tabs from the rail

### 3. Timeline Design

| Property | Detail |
|----------|--------|
| **Position** | Fixed at bottom of editor |
| **Default height** | ~150-200px |
| **Resizable** | Yes — drag the top edge of the timeline to resize |
| **Time ruler** | Top of timeline area — shows seconds/minutes markers |
| **Playhead** | Vertical line with handle at top — draggable to scrub through video |
| **Track types** | Video/image track (main), Text/graphic overlay track(s), Audio track(s) |
| **Audio waveform** | Visible on audio tracks — shows amplitude visualization for beat/sync alignment |
| **Clip representation** | Colored blocks with thumbnail preview inside; trimming via drag handles on edges |
| **Zoom control** | Slider or +/- buttons in the timeline toolbar to zoom in for frame-level precision |
| **Transition indicators** | Small diamond/icon between clips where transitions are applied |
| **Play controls** | Play/Pause button, skip forward/back, current time / total duration display |
| **Background track** | Full-width clips that serve as the background; other tracks layer on top |
| **Multi-track** | Unlimited overlay tracks above the main video track; separate audio tracks below |
| **Track labels** | Left side of timeline shows track type labels |
| **Snap/alignment** | Elements snap to playhead and other clip boundaries |

#### Previous vs New Timeline
- **Pre-Oct 2025**: Page-based editing (each page = one scene, linear sequence)
- **Post-Oct 2025**: True multi-track timeline (clips, audio, overlays on separate tracks)
- Old projects retain page-based editing; new projects default to multi-track
- Users can toggle back to old editor via Settings > Video Editing > "Use new multi-track video editor"

### 4. AI Features Integration

| Feature | Location | Behavior |
|---------|----------|----------|
| **Magic Video** | Apps tab in left panel + promoted in template selection | AI auto-generates social-ready clips: styles, cuts, and sequences clips automatically |
| **Highlights** | Video editing contextual menu | AI identifies best moments in long footage — suggests clips to extract |
| **Enhance Voice** | Audio track context menu | One-click background noise removal from voice recordings |
| **AI Image Generation** | Apps tab > "Text to Image" | Generates images from text prompts, insertable into video |
| **Magic Write** | Apps tab or text editing context | AI-generated text/copy for titles, captions |
| **Background Remover** | Image/video context toolbar | One-click background removal (Pro feature) |
| **Magic Resize** | Share menu or design toolbar | Resize video to different aspect ratios for multiple platforms |
| **AI Voiceover** | Audio tab or Apps | Text-to-speech generation with multiple voice options |
| **Ask Canva** | Floating assistant button (bottom-right) | AI design advisor — suggests improvements, answers questions |

AI features are integrated contextually — they appear where relevant rather than in a separate AI panel. The "Apps" tab in the left sidebar serves as the discovery hub for AI tools.

### 5. Canvas / Preview Area

| Property | Detail |
|----------|--------|
| **Background** | Light gray (`#f0f0f0` to `#e5e5e5`) workspace area surrounding the canvas |
| **Canvas** | White or colored rectangle at the set aspect ratio, centered in the workspace |
| **Aspect ratios** | Preset by template choice: 16:9, 9:16, 1:1, 4:5, custom dimensions |
| **Zoom controls** | Bottom-right of canvas area — zoom percentage selector, fit-to-screen button |
| **Grid/guides** | Optional alignment guides appear when dragging elements |
| **Safe zones** | Template-specific safe area indicators for social platform requirements |
| **Playback** | Preview button in top bar or Play button in timeline starts playback on canvas |
| **Element selection** | Click to select — shows blue bounding box with resize handles (8 points) and rotation handle |
| **Multi-select** | Shift+click or drag-select — group actions available |
| **Right-click menu** | Context menu with Copy, Paste, Delete, Bring Forward, Send Backward, Lock, etc. |

### 6. Contextual Toolbar (Replaces Traditional Right Panel)

Canva uses a **floating contextual toolbar** rather than a persistent right inspector panel:

| When Selected | Toolbar Shows |
|---------------|---------------|
| **Text element** | Font family, font size, bold/italic/underline, text color, alignment, spacing, effects (shadow, outline, curve), animate |
| **Image/Video** | Edit image, filters, adjust (brightness/contrast/saturation), crop, flip, animate, transparency, position, effects |
| **Shape** | Fill color, border (style/weight/color), corner rounding, transparency, position |
| **Audio clip** | Volume slider, fade in/out, trim, detach audio |
| **No selection** | Design background color, page/scene settings |

- **Position**: Appears as a horizontal bar above the canvas (below the top menu) when an element is selected
- **Behavior**: Contents change dynamically based on selected element type
- **"More" overflow**: Three-dot menu for less common options
- **Position/size**: Accessible via right-click > "Position" or toolbar — shows X, Y, Width, Height, Rotation numerically

### 7. Templates and Scenes

#### Template System
- Templates are pre-designed multi-page/multi-scene video projects
- Found in the **Design** tab of the left sidebar
- Categorized by platform: YouTube Intro, Instagram Reel, TikTok, Presentation, etc.
- Each template includes pre-set transitions, text animations, and timing
- **Customization**: Every element (text, colors, images, fonts, music) is replaceable

#### Scene Management (Multi-Track Era)
- **Adding scenes**: "+" button in the timeline adds a new page/scene
- **Scene thumbnails**: Visible as separate blocks in the timeline
- **Transitions between scenes**: Click the diamond icon between scenes to add/edit transitions
- **Transition types**: Dissolve, Slide, Wipe, Match & Move (auto-detects reused elements and animates them between positions)
- **Transition duration**: Adjustable via slider (typically 0.5-2.0 seconds)
- **Reordering**: Drag scenes in timeline to reorder
- **Duplicate scene**: Right-click > Duplicate

### 8. Export Flow

#### Step-by-Step
1. Click **"Share"** button (top-right corner, prominent purple/blue button)
2. Dropdown shows options: Share link, Present, Download, Schedule, More
3. Click **"Download"**
4. Export panel slides down or opens as modal:
   - **File type**: Dropdown — `MP4 Video` (default) | `GIF`
   - **Quality**: `1080p (HD)` default | `4K (UHD)` for Pro users
   - **Pages**: Select which pages/scenes to include (all or specific range)
5. Click **"Download"** button (purple/blue, prominent)
6. Progress bar shows rendering/export progress
7. File auto-downloads to browser's download folder

#### Export Constraints
- Free users: Max 30 min MP4, 1 min GIF
- Pro users: Max 2 hours MP4, 2 min GIF
- 4K export available but uploaded 4K footage is stored at 1080p internally
- No frame rate selection in standard UI (locked to template default, typically 30fps)

---

## Cross-Product Patterns

### Spacing Patterns

| Pattern | Kling AI | Canva |
|---------|----------|-------|
| **Section padding** | 16-20px within panels | 12-16px within panels |
| **Gap between controls** | 12-16px vertical gap between settings groups | 8-12px between elements |
| **Input field padding** | 12px internal padding | 8-12px internal padding |
| **Button padding** | 12-16px vertical, full-width | 8-12px vertical, varies width |
| **Card gap (gallery)** | 12-16px grid gap | 8-12px grid gap |
| **Panel-to-content gap** | 0px (flush panel edges) | 0px (flush panel edges) |

### Border Radius Values

| Element | Kling AI | Canva |
|---------|----------|-------|
| **Buttons (primary)** | 8-12px (softly rounded) | 8px (consistent rounding) |
| **Toggle pills** | 20px+ (full pill shape) | 20px+ (full pill shape) |
| **Input fields** | 8px | 8px |
| **Cards/thumbnails** | 8-12px | 8-12px |
| **Modals/panels** | 12-16px | 12px |
| **Avatar/profile** | 50% (full circle) | 50% (full circle) |
| **Small tags/badges** | 4-6px | 4-6px |

### Empty States

| Product | Behavior |
|---------|----------|
| **Kling AI** | Center panel shows example generation thumbnails or a "Get started" prompt with sample prompts the user can click to try; no blank emptiness |
| **Canva** | Template gallery is the landing state — user picks a template or starts blank; blank canvas shows a subtle "Click to add text" or element prompts; AI-suggested templates based on project type |

### Loading / Progress Indicators

| Product | Style |
|---------|-------|
| **Kling AI** | Linear progress bar with percentage + queue position text; shimmer/pulse animation on waiting cards; can freeze at 99% (known UX issue) |
| **Canva** | Skeleton loaders for panel content (gray animated placeholder blocks); spinner for export/download; progress bar during video rendering/export; smooth indeterminate progress for AI operations |

### Mobile vs Desktop

| Aspect | Kling AI | Canva |
|--------|----------|-------|
| **Mobile optimization** | Suboptimal — web app not well-optimized for mobile; no native mobile apps; mobile browser is cumbersome for creation, acceptable for viewing | Fully native mobile app (iOS/Android); same feature set with adapted layout; bottom-sheet panels replace left sidebar; timeline becomes horizontal scroll at bottom; drag-and-drop still works |
| **Responsive breakpoints** | Desktop-first, mobile is afterthought | Desktop + tablet + mobile all considered; responsive breakpoints for sidebar collapse |
| **Mobile timeline** | N/A (no timeline in generation tool) | Compact horizontal timeline with swipe gestures; simplified track view |

---

## Actionable Takeaways

### Design System Decisions for Video Studio

1. **Dark theme** for AI generation views (like Kling), **light theme option** for editing views (like Canva) — or offer both
2. **Left panel for controls/settings**, center for preview, bottom for timeline — this is the universal standard
3. **Contextual floating toolbar** (Canva pattern) is superior to persistent right panels for editing — reduces visual clutter
4. **Progress indicators must be honest** — Kling's 99% freeze is a cautionary tale; use server-sent events for real progress
5. **Multi-shot storyboard** (Kling 3.0) is the direction for AI video — horizontal shot cards with per-shot controls
6. **Multi-track timeline** (Canva 2.0) is now standard — must support video, text overlay, and audio tracks minimum
7. **AI features integrated contextually** (Canva pattern) rather than in a separate "AI section"
8. **Prompt input should be generous** — large textarea, negative prompt support, prompt suggestions/enhancement
9. **Gallery cards with hover-preview** for generation history
10. **Export flow should be 2-3 clicks max** — Share > Download > format/quality > Download

### Specific Component Patterns to Adopt

| Component | Recommended Pattern | Source |
|-----------|-------------------|--------|
| Aspect ratio selector | Icon-based toggle group (visual rectangles) | Kling |
| Duration selector | Segmented pill toggle with credit cost | Kling |
| Camera movement | Grid of animated preview thumbnails | Kling |
| Settings panel | Vertical stack with collapsible sections | Kling |
| Timeline | Multi-track with waveform, snap, zoom | Canva |
| Element properties | Floating contextual toolbar | Canva |
| Left sidebar | Icon rail + expandable content panel | Canva |
| Export | Top-right Share button > slide-down panel | Canva |
| Template browser | Grid with categorization by platform/use-case | Canva |
| AI generation wait | Progress bar + time estimate + cancel button | Both |

---

## Sources

### Kling AI
- [Kling AI Official Platform](https://klingai.com/global/)
- [Kling AI 3.0 Review - CyberNews](https://cybernews.com/ai-tools/kling-ai-review/)
- [Kling 3.0 User Guide - VEED](https://www.veed.io/learn/kling-3-0-guide)
- [Kling 3.0 Review: Multi-Shot Storyboarding - SeaArt](https://www.seaart.ai/blog/kling-3-0-review)
- [Kling 3.0 Multi-Shot](https://kling3.io/multi-shot)
- [Kling AI Camera Movement Guide - Pollo AI](https://pollo.ai/hub/how-to-use-kling-ai-camera-movement)
- [How to Use Kling AI - Stable Diffusion Art](https://stable-diffusion-art.com/kling/)
- [Kling AI Step-by-Step Guide - DreamLux](https://dreamlux.ai/blog/how-to-use-kling-ai)
- [Kling AI Text to Video - Pollo AI](https://pollo.ai/hub/how-to-use-kling-ai-text-to-video)
- [Kling AI Video Generator Guide - AllAboutAI](https://www.allaboutai.com/ai-how-to/use-kling-ai-video-generator/)
- [Kling AI Stuck at 99% - Segmind](https://blog.segmind.com/kling-ai-video-generator-stuck-at-99-heres-why/)
- [Kling O1 Unified Video Generation & Editing - Higgsfield](https://higgsfield.ai/kling-o1-intro)
- [Kling 3.0 Tutorial - Cliprise/Medium](https://medium.com/@cliprise/kling-3-0-tutorial-the-complete-guide-to-4k-ai-video-generation-in-2026-0e8cfed0e042)
- [Kling AI Comprehensive Guide - EEsel](https://www.eesel.ai/blog/kling-ai)
- [Kling AI Review - Desking](https://desking.app/kling-ai-review/)

### Canva Video Editor
- [Canva Video Editor Help Center](https://www.canva.com/help/creating-and-editing-videos/)
- [Canva Video Editor 2.0 Beta Review](https://www.webeducationservices.com/canva-video-editor-2-0-beta)
- [Canva Video Timeline Mobile](https://www.canva.com/design-school/resources/video-timeline-mobile)
- [Canva Side Panel Tabs - C# Corner](https://www.c-sharpcorner.com/article/canva-sidebar-and-its-tabs-learn-canva/)
- [Canva Menubar and Toolbar](https://www.c-sharpcorner.com/article/exploring-canvas-menubar-and-toolbar/)
- [Canva Page Transitions](https://www.canva.com/help/page-transitions/)
- [Canva Download as Video](https://www.canva.com/help/download-as-video/)
- [Canva AI Video Editor](https://www.canva.com/video-editor/ai/)
- [Canva Video Suite Launch](https://www.canva.com/newsroom/news/introducing-canva-video-suite/)
- [Canva vs CapCut - Android Police](https://www.androidpolice.com/canva-vs-capcut-video/)
- [Canva 2025 Video Editor - LilysAI](https://lilys.ai/notes/en/design-with-canva-20251118/canva-2025-video-editor-game-changer)
- [Canva Visual Effects - Engineering Blog](https://product.canva.com/five-visual-effects)
- [Canva Mobile Design Guidelines](https://www.canva.dev/docs/apps/design-guidelines/mobile/)
- [Canva Mobile vs Desktop - Dicloak](https://dicloak.com/video-insights-detail/canva-mobile-vs-desktop-in-2025-pros-cons-features-and-more)
- [How to Turn Off Canva Video 2.0 - Brenda Cadman](https://brendacadman.com/how-to-turn-off-canvas-video-2-0-editor/)
