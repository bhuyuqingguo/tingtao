"""Generate the embedded Chinese tutorial narration with an installed offline voice."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from offline_transcriber.tutorial_content import TUTORIAL_CHAPTERS  # noqa: E402

OUT = ROOT / "assets" / "tutorial"
VOICE = "Microsoft Huihui Desktop"


def synthesize(text: str, destination: Path, rate: int = 0) -> None:
    # Encode the PowerShell source to preserve Chinese text and avoid shell interpolation.
    escaped_text = text.replace("'", "''")
    escaped_path = str(destination).replace("'", "''")
    source = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
    $synth.SelectVoice('{VOICE}')
    $synth.Rate = {rate}
    $synth.Volume = 100
    $synth.SetOutputToWaveFile('{escaped_path}')
    $synth.Speak('{escaped_text}')
}} finally {{
    $synth.Dispose()
}}
"""
    encoded = base64.b64encode(source.encode("utf-16le")).decode("ascii")
    subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded,
    ], check=True, capture_output=True, text=True, timeout=180)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for chapter in TUTORIAL_CHAPTERS:
        destination = ROOT / chapter["audio"]
        synthesize(chapter["narration"], destination)
        with wave.open(str(destination), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
            assert seconds > 5 and audio.getnchannels() == 1
        report.append({
            "chapter": chapter["number"], "title": chapter["title"],
            "file": chapter["audio"], "bytes": destination.stat().st_size,
            "duration_seconds": round(seconds, 2), "voice": VOICE, "language": "zh-CN",
        })
        print(f"{chapter['number']:02d} {chapter['title']}: {seconds:.1f}s")
    (OUT / "narration-manifest.json").write_text(
        json.dumps({"offline": True, "voice": VOICE, "chapters": report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {len(report)} local narration files: {OUT}")


if __name__ == "__main__":
    main()
