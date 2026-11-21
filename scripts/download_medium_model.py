from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "models" / "faster-whisper-medium"
REQUIRED = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ.pop(name, None)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id="Systran/faster-whisper-medium",
        allow_patterns=list(REQUIRED),
        local_dir=str(DESTINATION),
        max_workers=4,
    )
    files = []
    for name in REQUIRED:
        path = DESTINATION / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Medium model file is missing or empty: {path}")
        files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    cache = DESTINATION / ".cache"
    if cache.exists():
        shutil.rmtree(cache)
    report = {"repository": "Systran/faster-whisper-medium", "files": files}
    (DESTINATION / "model-source.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
