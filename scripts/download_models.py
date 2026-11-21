from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download, hf_hub_download


ROOT = Path(__file__).resolve().parents[1]
ASR_FILES = {
    "model.bin": {
        "small": (483546902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
        "medium": (1527906378, "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae"),
    },
    "config.json": {
        "small": (2370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
        "medium": (2257, "3622a2ddc41ec0e0fd4e68c13c6830f03b90c38d89aaad184de02c8c642cf807"),
    },
    "tokenizer.json": {
        "small": (2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
        "medium": (2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
    },
    "vocabulary.txt": {
        "small": (459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
        "medium": (459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path, expected: tuple[int, str]) -> None:
    size, expected_hash = expected
    if not path.is_file() or path.stat().st_size != size or sha256(path) != expected_hash:
        raise RuntimeError(f"模型文件大小或 SHA-256 校验失败：{path}；请人工审查模型更新，不要跳过校验。")


def download_asr(name: str) -> None:
    target = ROOT / "models" / f"faster-whisper-{name}"
    snapshot_download(
        repo_id=f"Systran/faster-whisper-{name}",
        allow_patterns=list(ASR_FILES),
        local_dir=target,
        max_workers=4,
    )
    for filename, variants in ASR_FILES.items():
        verify(target / filename, variants[name])
    cache = target / ".cache"
    if cache.exists():
        shutil.rmtree(cache)
    print(f"已下载并校验：{target}")


def download_speaker() -> None:
    target = ROOT / "models" / "wespeaker-cnceleb-resnet34-LM"
    target.mkdir(parents=True, exist_ok=True)
    filename = "cnceleb_resnet34_LM.onnx"
    hf_hub_download(
        repo_id="wespeaker/wespeaker-cnceleb-resnet34-LM",
        filename=filename,
        local_dir=target,
    )
    verify(target / filename, (26530309, "e7584940aeac8d5512d875e58ce6c09ba4ddad65d8128e1dac0d93aadd087ebb"))
    cache = target / ".cache"
    if cache.exists():
        shutil.rmtree(cache)
    print(f"已下载并校验：{target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="开发机联网获取模型；运行阶段保持离线。")
    parser.add_argument("--model", choices=("small", "medium", "speaker", "all"), default="all")
    args = parser.parse_args()
    for name in ("small", "medium"):
        if args.model in (name, "all"):
            download_asr(name)
    if args.model in ("speaker", "all"):
        download_speaker()


if __name__ == "__main__":
    main()
