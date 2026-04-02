"""Tests for worker.media.adapters configuration."""

from worker.media.adapters import ADAPTER_CONFIG, CATEGORIES, free_adapters_by_category

REQUIRED_FIELDS = ("label", "category", "model", "outputKind", "envPrefix", "costTier", "costPerUnit")


def test_adapter_config_has_required_fields():
    for key, config in ADAPTER_CONFIG.items():
        for field in REQUIRED_FIELDS:
            assert field in config, f"adapter '{key}' missing field '{field}'"


def test_free_adapters_by_category_returns_correct_keys():
    # Gemini Flash is the free AI image provider (500/day)
    image_free = free_adapters_by_category("image")
    assert "gemini-flash" in image_free

    tts_free = free_adapters_by_category("tts")
    assert "edge-tts" in tts_free
    assert "windows-tts" in tts_free

    sfx_free = free_adapters_by_category("sfx")
    assert "local-sfx" in sfx_free


def test_categories_constant_matches_config():
    config_categories = {v["category"] for v in ADAPTER_CONFIG.values()}
    for cat in config_categories:
        assert cat in CATEGORIES, f"category '{cat}' in config but not in CATEGORIES"
