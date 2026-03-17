from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

POWERSHELL_EXE = "powershell.exe"


@dataclass(slots=True)
class WindowsTtsResult:
    ok: bool
    outputPath: str
    voiceName: str | None
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def _write_utf8_sig(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8-sig")


def synthesize_windows_voiceover(
    text: str,
    output_path: Path | str,
    working_dir: Path | str,
) -> WindowsTtsResult:
    resolved_output = Path(output_path).resolve()
    resolved_working_dir = Path(working_dir).resolve()
    resolved_working_dir.mkdir(parents=True, exist_ok=True)

    text_path = resolved_working_dir / f"{resolved_output.stem}.tts-input.txt"
    script_path = resolved_working_dir / f"{resolved_output.stem}.tts.ps1"

    _write_utf8_sig(text_path, text.strip())
    _write_utf8_sig(
        script_path,
        "\n".join(
            [
                "param(",
                "    [Parameter(Mandatory=$true)][string]$TextFile,",
                "    [Parameter(Mandatory=$true)][string]$OutputFile",
                ")",
                '$ErrorActionPreference = "Stop"',
                "Add-Type -AssemblyName System.Speech",
                "$text = Get-Content -Path $TextFile -Raw -Encoding UTF8",
                "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer",
                "$voice = $null",
                "$preferred = $synth.GetInstalledVoices() |",
                "    ForEach-Object { $_.VoiceInfo } |",
                "    Where-Object { $_.Culture.Name -eq 'ko-KR' -or $_.Name -match 'Heami|SunHi|Korean' } |",
                "    Select-Object -First 1",
                "if ($preferred) {",
                "    $synth.SelectVoice($preferred.Name)",
                "    $voice = $preferred.Name",
                "} else {",
                "    $voice = $synth.Voice.Name",
                "}",
                "$synth.Rate = 0",
                "$synth.Volume = 100",
                "$synth.SetOutputToWaveFile($OutputFile)",
                "$synth.Speak($text)",
                "$synth.Dispose()",
                "$voice | Out-File -FilePath ($OutputFile + '.voice.txt') -Encoding utf8",
            ]
        ),
    )

    completed = subprocess.run(
        [
            POWERSHELL_EXE,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-TextFile",
            str(text_path),
            "-OutputFile",
            str(resolved_output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    voice_name: str | None = None
    voice_meta = Path(str(resolved_output) + ".voice.txt")
    if voice_meta.exists():
        voice_name = voice_meta.read_text(encoding="utf-8").strip() or None

    if completed.returncode != 0:
        return WindowsTtsResult(
            ok=False,
            outputPath=str(resolved_output),
            voiceName=voice_name,
            detail=completed.stderr.strip() or completed.stdout.strip() or f"PowerShell exited with {completed.returncode}",
        )

    return WindowsTtsResult(
        ok=resolved_output.exists(),
        outputPath=str(resolved_output),
        voiceName=voice_name,
        detail="windows-speech ok" if resolved_output.exists() else "PowerShell completed but no audio file was written",
    )
