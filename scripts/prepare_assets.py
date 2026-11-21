from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build-cache"
MODEL_DIR = ROOT / "models" / "faster-whisper-small"
FFMPEG_DIR = ROOT / "ffmpeg"
MODEL_REPOSITORY = "Systran/faster-whisper-small"
FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
]


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "LocalTranscriber-Offline-Builder/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def prepare_model() -> None:
    if all((MODEL_DIR / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
        print("Local model already present.")
        return
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=MODEL_REPOSITORY, local_dir=MODEL_DIR)
    print(f"Model ready: {MODEL_DIR}")


def prepare_ffmpeg() -> None:
    if (FFMPEG_DIR / "ffmpeg.exe").is_file():
        print("FFmpeg already present.")
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / "ffmpeg.zip"
    errors = []
    for url in FFMPEG_URLS:
        try:
            print(f"Downloading FFmpeg from {url}")
            download(url, archive)
            with zipfile.ZipFile(archive) as package:
                names = package.namelist()
                ffmpeg_name = next(name for name in names if name.replace("\\", "/").endswith("/bin/ffmpeg.exe"))
                ffprobe_name = next(name for name in names if name.replace("\\", "/").endswith("/bin/ffprobe.exe"))
                FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
                for member, target in ((ffmpeg_name, "ffmpeg.exe"), (ffprobe_name, "ffprobe.exe")):
                    with package.open(member) as source, (FFMPEG_DIR / target).open("wb") as output:
                        shutil.copyfileobj(source, output)
                for member in names:
                    lower = member.lower()
                    if lower.endswith(("license", "license.txt", "copying", "copying.txt")):
                        target = FFMPEG_DIR / Path(member).name
                        with package.open(member) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
            print(f"FFmpeg ready: {FFMPEG_DIR}")
            return
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            archive.unlink(missing_ok=True)
    raise RuntimeError("Unable to download FFmpeg:\n" + "\n".join(errors))


def main() -> None:
    prepare_model()
    prepare_ffmpeg()
    required = [MODEL_DIR / name for name in ("model.bin", "config.json", "tokenizer.json")]
    required += [FFMPEG_DIR / "ffmpeg.exe"]
    manifest = {
        "model_repository": MODEL_REPOSITORY,
        "ffmpeg_sources": FFMPEG_URLS,
        "files": [
            {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in required
        ],
    }
    (ROOT / "assets-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All offline assets are ready.")


if __name__ == "__main__":
    main()
