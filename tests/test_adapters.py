"""Tests for worker.media.adapters configuration."""

from worker.media.adapters import ADAPTER_CONFIG, CATEGORIES, free_adapters_by_category, probe_local_media_adapter

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


def test_edge_tts_has_builtin_zero_paid_command_without_env(monkeypatch, tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "edge_tts.py").write_text("print('ok')", encoding="utf-8")
    python_dir = tmp_path / ".venv" / "Scripts"
    python_dir.mkdir(parents=True)
    python_exe = python_dir / "python.exe"
    python_exe.write_text("", encoding="utf-8")
    monkeypatch.delenv("VIDEO_STUDIO_EDGE_TTS_MODE", raising=False)
    monkeypatch.delenv("VIDEO_STUDIO_EDGE_TTS_COMMAND", raising=False)

    status = probe_local_media_adapter("edge-tts", project_root=tmp_path)

    assert status.mode == "command"
    assert status.ready is True
    assert status.entryPoint == str(python_exe.resolve())
    assert "edge_tts.py" in (status.commandPreview or "")
    assert "built-in zero-paid edge-tts command" in status.detail
