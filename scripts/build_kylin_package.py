from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "Kylin-x86_64"
DIST = DIST_ROOT / "TingTaoData"
LAUNCHER = DIST_ROOT / "TingTao"
STAGE = ROOT / "build-cache" / "kylin-stage-1.5.0"
WORK = ROOT / "build-cache" / "kylin-pyinstaller-1.5.0"
UPDATER_STAGE = ROOT / "build-cache" / "kylin-updater-stage-1.5.0"
UPDATER_WORK = ROOT / "build-cache" / "kylin-updater-pyinstaller-1.5.0"
LAUNCHER_STAGE = ROOT / "build-cache" / "kylin-launcher-stage-1.5.0"
LAUNCHER_WORK = ROOT / "build-cache" / "kylin-launcher-pyinstaller-1.5.0"
ARCHIVE = ROOT / "dist" / "TingTao-1.5.0-Kylin-x86_64-Offline.zip"
VERSION = "1.5.0"

USAGE = """观海·听涛 1.5.0 · 银河麒麟 V10 x86_64 完全离线语音转录
======================================================
观海听涛，声落成章。

发布目录规则
解压后顶层只有两个项目：
- TingTao：唯一启动入口，双击或在终端运行。
- TingTaoData：资源文件夹，内含程序、模型、FFmpeg、配置与数据。
请勿只拷贝外层启动器，也不要删除资源文件夹。

多文件转录
1. 点击拖入区可多选文件，也可一次拖入多个音频／视频。
2. 队列逐个转录：模型只加载一次，每个文件独立保存四种格式，另有批次汇总。
3. 合并为一份文稿：按列表顺序识别，以连续时间轴合并导出，不额外生成拼接 WAV。
4. 可使用上移／下移调整顺序；单文件失败会记录并继续后续队列。
5. TXT、SRT、VTT、JSON 均保留来源文件名；正式文稿请人工复核。

古典皮肤与双模型
“模型与系统”页可切换“山海古典／素简现代”。工作台可选择 small 或 medium，并记住上次选择。
small 速度优先；medium 精度优先。每次任务只加载一个模型，队列复用同一实例，均使用 CPU int8。
medium 模型约 1457 MiB，建议按 3–5 GB 峰值内存、small 的约 2–4 倍 CPU 时间预留。
large-v3 未内置；实际资源取决于 CPU、音频长度、搜索宽度和系统负载。

离线增量升级
“模型与系统”页导入 .ttupdate；仍兼容旧 .tlupdate 清单格式。升级前流式校验版本与文件哈希，
自动备份，失败回滚。config.json、data、音频库、声纹和已有 small／medium 模型受保护。
全部升级在当前软件内一键完成，不使用独立升级工具。
麒麟增量 ZIP 的顶层同样严格只有 TingTao 和 TingTaoUpdate 两项。

完整性与自检
在资源文件夹运行：bash verify_package.sh
单文件：./TingTao --self-test "音频.wav" --output "结果.json"
双文件队列：./TingTao --batch-test "a.wav" "b.wav" --output "队列结果.json"
双文件合并：./TingTao --batch-test "a.wav" "b.wav" --merge --output "合并结果.json"

第三方组件见 THIRD_PARTY_NOTICES.txt 与 licenses。
"""

VERIFY_SH = r"""#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
sha256sum -c SHA256SUMS.txt
expected="$(tr -d '[:space:]' < LAUNCHER_SHA256.txt)"
actual="$(sha256sum ../TingTao | awk '{print $1}')"
if [[ "$actual" != "$expected" ]]; then
  echo "外层 TingTao 启动器哈希校验失败" >&2
  exit 1
fi
echo "OK: 观海·听涛部署包完整性校验通过。"
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pyinstaller_base(work: Path, stage: Path) -> list[str]:
    return [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--paths", str(ROOT / "src"), "--distpath", str(stage), "--workpath", str(work),
        "--specpath", str(ROOT / "build-cache"),
    ]


def run_builds() -> None:
    if DIST_ROOT.exists():
        shutil.rmtree(DIST_ROOT)
    DIST_ROOT.mkdir(parents=True)
    command = pyinstaller_base(WORK, STAGE) + [
        "--onedir", "--windowed", "--name", "TingTao",
        "--collect-all", "faster_whisper", "--collect-all", "ctranslate2", "--collect-all", "av",
        "--collect-all", "docx", "--collect-all", "lxml", "--collect-all", "onnxruntime",
        "--collect-all", "cryptography",
        "--hidden-import", "offline_transcriber.main_window", str(ROOT / "src" / "run_app.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    shutil.move(str(STAGE / "TingTao"), str(DIST))
    launcher = pyinstaller_base(LAUNCHER_WORK, LAUNCHER_STAGE) + [
        "--onefile", "--console", "--name", "TingTaoLauncher", str(ROOT / "src" / "launcher.py"),
    ]
    subprocess.run(launcher, cwd=ROOT, check=True)
    shutil.copy2(LAUNCHER_STAGE / "TingTaoLauncher", LAUNCHER)
    for executable in (LAUNCHER, DIST / "TingTao"):
        if not executable.is_file():
            raise RuntimeError(f"Expected executable was not created: {executable}")
        executable.chmod(0o755)


def copy_assets() -> None:
    shutil.copytree(ROOT / "models", DIST / "models")
    ffmpeg_source = ROOT / "ffmpeg" / "linux-amd64" / "ffmpeg"
    if not ffmpeg_source.is_file():
        raise RuntimeError("请将 Linux x86_64 静态 FFmpeg 放到 ffmpeg/linux-amd64/ffmpeg 后重新构建")
    ffmpeg_target = DIST / "ffmpeg"
    ffmpeg_target.mkdir(parents=True)
    shutil.copy2(ffmpeg_source, ffmpeg_target / "ffmpeg")
    (ffmpeg_target / "ffmpeg").chmod(0o755)
    optional_ffprobe = ffmpeg_source.with_name("ffprobe")
    if optional_ffprobe.is_file():
        shutil.copy2(optional_ffprobe, ffmpeg_target / "ffprobe")
        (ffmpeg_target / "ffprobe").chmod(0o755)
    for name in ("LICENSE.txt", "SOURCE.txt"):
        for source in (ffmpeg_source.parent / name, ROOT / "ffmpeg" / name):
            if source.is_file():
                shutil.copy2(source, ffmpeg_target / name)
                break
    assets = DIST / "assets"
    assets.mkdir(parents=True)
    for name in (
        "guanhai-tingtao-logo-generated.png", "guanhai-tingtao-logo.png",
        "guanhai-tingtao-logo-256.png", "guanhai-tingtao-logo-64.png", "app.ico",
    ):
        shutil.copy2(ROOT / "assets" / name, assets / name)
    for name in ("output", "temp", "logs"):
        (DIST / "data" / name).mkdir(parents=True, exist_ok=True)
    config = {"language": "zh", "beam_size": 5, "vad_filter": True, "output_directory": "", "batch_mode": "queue", "theme": "classical", "model_name": "small", "speaker_enabled": False, "speaker_threshold": 0.55}
    (DIST / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / "使用说明.txt").write_text(USAGE, encoding="utf-8")
    (DIST / "verify_package.sh").write_text(VERIFY_SH, encoding="utf-8")
    (DIST / "verify_package.sh").chmod(0o755)


def copy_licenses() -> None:
    license_dir = DIST / "licenses"
    license_dir.mkdir(exist_ok=True)
    package_names = [
        "faster-whisper", "ctranslate2", "av", "tokenizers", "numpy", "PySide6",
        "huggingface-hub", "onnxruntime", "tqdm", "urllib3", "certifi", "python-docx", "lxml", "cryptography", "cffi",
    ]
    notices = [
        "观海·听涛\n第三方组件清单\n",
        "Linux x86_64 FFmpeg: supplied at build time in ffmpeg/linux-amd64; see bundled LICENSE.txt and SOURCE.txt.",
        "FFmpeg source: https://github.com/FFmpeg/FFmpeg",
        "faster-whisper-small model, MIT License; https://huggingface.co/Systran/faster-whisper-small",
        "faster-whisper-medium model, MIT License; https://huggingface.co/Systran/faster-whisper-medium",
        "WeSpeaker CNCeleb ResNet34-LM ONNX, Apache-2.0; https://huggingface.co/wespeaker/wespeaker-cnceleb-resnet34-LM",
        "Logo generated for Guanhai Tingtao; system fonts are referenced, not redistributed.",
    ]
    for name in package_names:
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        notices.append(f"\n{distribution.metadata['Name']} {distribution.version}")
        notices.append(f"License: {distribution.metadata.get('License', 'See bundled license files')}")
        candidates = []
        if distribution.files:
            for item in distribution.files:
                lower = str(item).lower()
                if any(token in lower for token in ("license", "copying", "notice")) and item.name.lower() != "entry_points.txt":
                    candidates.append(item)
        for index, item in enumerate(candidates[:8]):
            source = Path(distribution.locate_file(item))
            if source.is_file() and source.stat().st_size < 2_000_000:
                shutil.copy2(source, license_dir / f"{name}-{index}-{source.name}")
    (DIST / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices), encoding="utf-8")


def write_build_info() -> None:
    versions = {}
    for name in ("faster-whisper", "ctranslate2", "PySide6", "av", "numpy"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    payload = {
        "application": "TingTao",
        "product_name_zh": "观海·听涛",
        "version": VERSION,
        "platform": "Kylin V10 x86_64",
        "mode": "fully-offline-portable-two-item-layout",
        "layout": {"executable": "TingTao", "resource_directory": "TingTaoData"},
        "models": ["Systran/faster-whisper-small", "Systran/faster-whisper-medium", "wespeaker/wespeaker-cnceleb-resnet34-LM"],
        "default_model": "small",
        "model_selection": True,
        "single_model_resident_per_task": True,
        "compute": "CPU int8",
        "batch_modes": ["queue", "merged"],
        "update_format": "tinglan-offline-update-v1",
        "application_and_model_updates_separated": False,
        "application_update_excludes": ["data", "models/faster-whisper-small", "models/faster-whisper-medium", "config.json"],
        "model_update_policy": "1.5.0 adds only models/wespeaker-cnceleb-resnet34-LM; existing ASR models and user data are protected",
        "larger_model_estimates_not_benchmarked": {
            "large-v3": {"model_gb": 3.09, "peak_ram_gb": [6, 10], "relative_cpu_time": [4, 8]},
        },
        "components": versions,
        "acceptance": "Build only. Run offline inference and GUI acceptance on the target Kylin host before deployment.",
    }
    (DIST / "build-info.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_manifests() -> None:
    (DIST / "LAUNCHER_SHA256.txt").write_text(sha256(LAUNCHER), encoding="ascii")
    files = sorted(
        path for path in DIST.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt" and path.relative_to(DIST).parts[0] != "data"
    )
    content = "".join(f"{sha256(path)} *{path.relative_to(DIST).as_posix()}\n" for path in files)
    (DIST / "SHA256SUMS.txt").write_text(content, encoding="utf-8")


def make_archive() -> dict:
    all_files = sorted(
        path for path in DIST.rglob("*") if path.is_file() and path.relative_to(DIST).parts[0] != "data"
    )
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
        package.write(LAUNCHER, arcname="TingTao")
        for path in all_files:
            package.write(path, arcname=(Path("TingTaoData") / path.relative_to(DIST)).as_posix())
    with zipfile.ZipFile(ARCHIVE) as package:
        bad = package.testzip()
        if bad:
            raise RuntimeError(f"Kylin ZIP CRC failure: {bad}")
        top_level = {Path(name).parts[0] for name in package.namelist() if Path(name).parts}
        if top_level != {"TingTao", "TingTaoData"}:
            raise RuntimeError(f"Kylin package top-level rule failed: {top_level}")
    archive_hash = sha256(ARCHIVE)
    ARCHIVE.with_name(ARCHIVE.name + ".sha256.txt").write_text(f"{archive_hash} *{ARCHIVE.name}\n", encoding="ascii")
    return {
        "archive": str(ARCHIVE), "bytes": ARCHIVE.stat().st_size, "sha256": archive_hash,
        "top_level_items": ["TingTao", "TingTaoData"], "zip_crc_test": True,
        "inference_and_gui_tested": False,
    }


def main() -> None:
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        raise RuntimeError("Build this package on Kylin V10 x86_64 or a compatible Linux x86_64 host")
    for model in ("small", "medium"):
        if not (ROOT / "models" / f"faster-whisper-{model}" / "model.bin").is_file():
            raise RuntimeError(f"Local {model} model is missing")
    run_builds()
    copy_assets()
    copy_licenses()
    write_build_info()
    write_manifests()
    print(json.dumps(make_archive(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
