from pathlib import Path

from worker.render import compose_ffmpeg
from worker.render.foley import (
    create_procedural_foley,
    infer_procedural_foley_pattern,
    procedural_foley_metadata,
)


def test_infer_procedural_foley_pattern_from_grok_prompt():
    assert infer_procedural_foley_pattern({"grokPrompt": "same worker opens fridge and slices vegetables"}) == "kitchen-prep"
    assert infer_procedural_foley_pattern({"grokPrompt": "desk notebook writing under a warm lamp"}) == "desk-notes"
    assert infer_procedural_foley_pattern({"grokPrompt": "phone face-down, notebook open, hand writes one line"}) == "desk-notes"
    assert infer_procedural_foley_pattern({"grokPrompt": "rolls out a mat beside the desk lamp and does a shoulder stretch"}) == "mat-rustle"
    assert infer_procedural_foley_pattern({"grokPrompt": "lowers the desk lamp and closes notebook"}) == "lamp-switch"
    assert infer_procedural_foley_pattern({"grokPrompt": "Seoul subway platform, phone-camera realism, and train lights"}) == "commute-room"


def test_create_procedural_foley_uses_local_lavfi_sources(monkeypatch, tmp_path):
    captured = {}

    def fake_run_ffmpeg(ffmpeg_path, args, log_lines, cwd=None):
        captured["ffmpeg_path"] = ffmpeg_path
        captured["args"] = args
        captured["cwd"] = cwd
        Path(args[-1]).write_bytes(b"fake-wav")
        log_lines.append("fake ffmpeg ok")

    monkeypatch.setattr("worker.render.foley.run_ffmpeg", fake_run_ffmpeg)
    output = tmp_path / "scene-02.sfx.wav"
    log_lines = []

    create_procedural_foley(
        ffmpeg_path="ffmpeg",
        output_path=output,
        duration_sec=3.5,
        pattern="kitchen-prep",
        log_lines=log_lines,
    )

    args = captured["args"]
    assert captured["ffmpeg_path"] == "ffmpeg"
    assert output.exists()
    assert args.count("-f") >= 2
    assert "lavfi" in args
    assert "-filter_complex" in args
    assert "amix=inputs=" in args[args.index("-filter_complex") + 1]
    assert any(line.startswith("procedural_foley=generate pattern=kitchen-prep") for line in log_lines)


def test_procedural_foley_metadata_is_free_audio_credit_ready(tmp_path):
    output = tmp_path / "storage" / "cache" / "project" / "scene-02" / "scene-02.sfx.wav"
    metadata = procedural_foley_metadata(
        pattern="kitchen-prep",
        output_path=output,
        project_root=tmp_path,
    )
    asset = {
        "id": "scene-02-sfx",
        "sceneId": "scene-02",
        "role": "sfx",
        **metadata,
    }

    credit = compose_ffmpeg._build_free_audio_credit(asset)

    assert asset["provider"] == "local-sfx"
    assert asset["sourceOrigin"] == "generated-procedural-local"
    assert asset["sourceUrl"] == "local://video-studio/procedural-foley/kitchen-prep"
    assert asset["sourceLicense"].startswith("Operator-owned procedural audio")
    assert credit is not None
    assert credit["missingFields"] == []
    assert compose_ffmpeg._asset_has_license_provenance(asset, require_license_note=True)
