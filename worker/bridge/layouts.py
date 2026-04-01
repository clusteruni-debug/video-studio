"""Template layout configurations, subtitle styles, BGM mood mapping, and TTS defaults.

Extracted from server.py to keep the main bridge under the 660-line limit.
These are pure data — no logic, no imports beyond typing.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# TTS defaults
# ---------------------------------------------------------------------------
DEFAULT_TTS_RATE = "+35%"
DEFAULT_TTS_RATE_COMMENTARY = "+15%"

# ---------------------------------------------------------------------------
# BGM mood → template mapping
# ---------------------------------------------------------------------------
TEMPLATE_BGM_MOOD: dict[str, str] = {
    "news_explainer": "tense",
    "community_read": "calm",
    "hot_take": "upbeat",
    "ranking_list": "upbeat",
    "reddit_translation": "calm",
    "origin_story": "cinematic",
    "vs_comparison": "upbeat",
    "myth_buster": "cinematic",
    "tutorial_steps": "calm",
    "before_after": "cinematic",
}

# ---------------------------------------------------------------------------
# Subtitle style overrides for add_text_impl
# ---------------------------------------------------------------------------
SUBTITLE_STYLE_MAP: dict[str, dict] = {
    "": {},
    "default": {},
    "news": {"font_size": 14.0, "transform_y": -0.30},
    "story": {"font_size": 16.0, "border_width": 0.15},
    "ranking": {"font_size": 18.0, "transform_y": -0.20},
    "minimal": {"font_size": 10.0, "border_width": 0.06, "shadow_distance": 2.0},
    "impact": {"font_size": 20.0, "font_color": "#FFFF00", "border_width": 0.18},
}

# ---------------------------------------------------------------------------
# Template layouts: structurally different compositions per template
# ---------------------------------------------------------------------------
# Each layout defines dramatic visual differences (not just color tweaks).
# "img": image layer params, "text": narration text params,
# "hook": overrides for scene 1, "rank": overrides for rank scenes,
# "badge": optional second text layer (rank number, step counter, label)
TEMPLATE_LAYOUTS: dict[str, dict] = {
    "news_explainer": {
        # Full bg + heavy blur → bottom dark bar with white text
        "img": {"scale_x": 1.4, "scale_y": 1.4, "background_blur": 4},
        "text": {
            "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.40,
            "background_color": "#000000", "background_alpha": 0.55,
            "intro_animation": "Fade_In", "shadow_distance": 4.0,
        },
        "hook": {
            "text": {"font_size": 12.0, "transform_y": -0.15, "intro_animation": "Zoom_In",
                     "background_color": "#000000", "background_alpha": 0.65},
        },
        "default_transition": "Dissolve",
    },
    "community_read": {
        # Image pushed to top half, text in bottom half with speech-bubble bg
        "img": {"scale_x": 1.0, "scale_y": 1.0, "transform_y": 0.20},
        "text": {
            "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.38,
            "background_color": "#1A1A1A", "background_alpha": 0.65,
            "intro_animation": "Fade_In", "shadow_distance": 3.0,
        },
        "hook": {
            "text": {"font_size": 11.0, "transform_y": -0.20, "intro_animation": "Zoom_In"},
        },
        "default_transition": "Fade_In",
    },
    "hot_take": {
        # Full bg blur, CENTER large yellow text, red accent on hook
        "default_transition": "Dissolve",
        "img": {"scale_x": 1.5, "scale_y": 1.5, "background_blur": 3},
        "text": {
            "font_color": "#FFD700", "font_size": 9.0, "transform_y": -0.20,
            "intro_animation": "Zoom_In", "shadow_distance": 8.0,
        },
        "hook": {
            "text": {"font_size": 14.0, "transform_y": 0.0, "font_color": "#FFD700",
                     "background_color": "#CC0000", "background_alpha": 0.55},
        },
    },
    "ranking_list": {
        # Clean image, rank badge as separate large layer
        "img": {"scale_x": 1.2, "scale_y": 1.2},
        "default_transition": "Slide_Left",
        "text": {
            "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.35,
            "intro_animation": "Fade_In", "shadow_distance": 5.0,
        },
        "hook": {
            "text": {"font_size": 11.0, "transform_y": -0.15},
        },
        "rank": {
            "text": {"intro_animation": "Slide_Left"},
            "badge": {
                "font_size": 32.0, "transform_y": -0.08, "font_color": "#FFD700",
                "background_color": "#1A1A2E", "background_alpha": 0.75,
                "intro_animation": "Slide_Left",
            },
        },
    },
    "reddit_translation": {
        # Image at top, two-tone text: normal + gold commentary
        "default_transition": "Fade_In",
        "img": {"scale_x": 1.0, "scale_y": 1.0, "transform_y": 0.15},
        "text": {
            "font_color": "#F0F0F0", "font_size": 8.0, "transform_y": -0.38,
            "background_color": "#1A1A1A", "background_alpha": 0.50,
            "intro_animation": "Fade_In", "shadow_distance": 4.0,
        },
        "hook": {
            "text": {"font_size": 11.0, "transform_y": -0.20,
                     "background_color": "#FF4500", "background_alpha": 0.45},
        },
        "commentary": {
            "text": {"font_color": "#FFD700"},
        },
    },
    "origin_story": {
        # Cinematic: heavy zoom + blur, centered cream text with fade
        "img": {"scale_x": 1.6, "scale_y": 1.6, "background_blur": 2},
        "text": {
            "font_color": "#FFF8E1", "font_size": 9.0, "transform_y": -0.25,
            "intro_animation": "Fade_In", "shadow_distance": 6.0,
        },
        "hook": {
            "text": {"font_size": 12.0, "transform_y": -0.10, "intro_animation": "Zoom_In"},
        },
        "default_transition": "Dissolve",
    },
    "vs_comparison": {
        # Normal image, text with side labels
        "img": {"scale_x": 1.3, "scale_y": 1.3, "background_blur": 2},
        "text": {
            "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.35,
            "intro_animation": "Slide_Left", "shadow_distance": 6.0,
        },
        "hook": {
            "text": {"font_size": 13.0, "transform_y": -0.05, "intro_animation": "Zoom_In",
                     "background_color": "#1A1A2E", "background_alpha": 0.6},
        },
        "default_transition": "Slide_Left",
        # Side labels: odd scenes = A (blue), even scenes = B (orange)
        "side_labels": {
            "odd": {"label": "A", "font_color": "#00E5FF",
                    "background_color": "#0D47A1", "background_alpha": 0.75},
            "even": {"label": "B", "font_color": "#FF9100",
                     "background_color": "#E65100", "background_alpha": 0.75},
        },
    },
    "myth_buster": {
        # Full bg, verdict scenes get colored verdict badge
        "img": {"scale_x": 1.3, "scale_y": 1.3, "background_blur": 1},
        "text": {
            "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.35,
            "intro_animation": "Fade_In", "shadow_distance": 6.0,
        },
        "hook": {
            "text": {"font_size": 12.0, "transform_y": -0.10, "intro_animation": "Zoom_In",
                     "background_color": "#CC0000", "background_alpha": 0.55},
        },
        "default_transition": "Dissolve",
        # Verdict badge: shown when narration contains verdict keywords
        "verdict_keywords": {
            "사실": {"label": "O 사실", "font_color": "#00E676",
                    "background_color": "#1B5E20", "background_alpha": 0.80},
            "거짓": {"label": "X 거짓", "font_color": "#FF5252",
                    "background_color": "#B71C1C", "background_alpha": 0.80},
            "fact": {"label": "O FACT", "font_color": "#00E676",
                     "background_color": "#1B5E20", "background_alpha": 0.80},
            "myth": {"label": "X MYTH", "font_color": "#FF5252",
                     "background_color": "#B71C1C", "background_alpha": 0.80},
        },
    },
    "tutorial_steps": {
        # Smaller image (screen recording feel), step counter badge
        "default_transition": "Fade_In",
        "img": {"scale_x": 0.85, "scale_y": 0.85, "transform_y": 0.10},
        "text": {
            "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.38,
            "intro_animation": "Fade_In", "shadow_distance": 4.0,
        },
        "hook": {
            "text": {"font_size": 11.0, "transform_y": -0.20},
        },
        "rank": {
            "text": {},
            "badge": {
                "font_size": 24.0, "transform_y": 0.35, "font_color": "#FFFFFF",
                "background_color": "#2196F3", "background_alpha": 0.70,
                "intro_animation": "Fade_In",
            },
        },
    },
    "before_after": {
        # Normal image, "Before"/"After" label badge per scene half
        "default_transition": "Dissolve",
        "img": {"scale_x": 1.2, "scale_y": 1.2},
        "text": {
            "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.35,
            "intro_animation": "Fade_In", "shadow_distance": 5.0,
        },
        "hook": {
            "text": {"font_size": 12.0, "transform_y": -0.10, "intro_animation": "Zoom_In",
                     "background_color": "#333333", "background_alpha": 0.55},
        },
        "emotion_labels": {
            "sad": {"label": "Before", "font_color": "#FF6B6B",
                    "background_color": "#1A1A1A", "background_alpha": 0.70},
            "serious": {"label": "Before", "font_color": "#FF6B6B",
                        "background_color": "#1A1A1A", "background_alpha": 0.70},
            "shock": {"label": "After", "font_color": "#4ECDC4",
                      "background_color": "#1A1A1A", "background_alpha": 0.70},
            "funny": {"label": "After", "font_color": "#4ECDC4",
                      "background_color": "#1A1A1A", "background_alpha": 0.70},
        },
    },
}

# Fallback layout for unknown templates
DEFAULT_LAYOUT: dict = {
    "img": {"scale_x": 1.3, "scale_y": 1.3},
    "text": {
        "font_color": "#FFFFFF", "font_size": 8.0, "transform_y": -0.35,
        "intro_animation": "Fade_In", "shadow_distance": 5.0,
    },
    "hook": {"text": {"font_size": 12.0, "transform_y": -0.15, "intro_animation": "Zoom_In"}},
}
