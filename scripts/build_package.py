from __future__ import annotations

import json
import shutil
import subprocess
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "Windows-x64"
DIST = DIST_ROOT / "TingTao"
LAUNCHER = DIST_ROOT / "TingTao.exe"
STAGE = ROOT / "build-cache" / "stage-1.5.0"
WORK = ROOT / "build-cache" / "pyinstaller-1.5.0"
UPDATER_STAGE = ROOT / "build-cache" / "updater-stage-1.5.0"
UPDATER_WORK = ROOT / "build-cache" / "updater-pyinstaller-1.5.0"
LAUNCHER_STAGE = ROOT / "build-cache" / "launcher-stage-1.5.0"
LAUNCHER_WORK = ROOT / "build-cache" / "launcher-pyinstaller-1.5.0"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYINSTALLER = ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
VERSION = "1.5.0"

USAGE = """观海·听涛 1.5.0 · 完全离线语音转录
====================================
观海听涛，声落成章。

发布目录规则
解压后顶层只有两个项目：
- TingTao.exe：唯一启动入口，双击运行。
- TingTao：资源文件夹，内含程序、模型、FFmpeg、配置与数据。
请勿只拷贝外层 EXE，也不要删除资源文件夹。

多文件转录与导出
1. 点击拖入区可多选文件，也可一次拖入多个音频／视频。
2. 队列逐个转录：模型只加载一次，每个文件独立保存；合并模式按列表顺序生成连续时间轴。
3. 可导出 TXT、Markdown、DOCX（Word／WPS 兼容）、SRT、VTT、JSON；当前页签为纪要时导出纪要。
4. “一键形成纪要”在本地整理重点、决定事项和待办，不调用在线大模型，须结合原文复核。
5. 转录记录支持手动重命名和“根据内容命名”，不会自动批量改动旧记录。

录音、音频库与加密
1. “录音与音频库”页可选择系统输入音源，录制 16 kHz 单声道 WAV，命名收存后立即加入离线转录。
2. 支持导入、重命名、关键词库、搜索、播放、导出、删除和批量加入转录。
3. 可选 AES-256-GCM 加密，音频内容、名称和关键词均加密；密码至少 8 字符且不会保存，遗忘无法恢复。
4. 播放或转录加密音频时生成会话临时副本，锁定或退出自动清除。导出的普通音频和文稿不自动加密。

声纹识别
1. 勾选“识别讲话人并匹配声纹库”后按转录片段分离，导出文稿显示讲话人。
2. 完成后点击“命名声纹”保存到本机；以后转录自动匹配姓名。“模型与系统”页可管理声纹库。
3. 阈值越高越谨慎。短于 0.8 秒、重叠语音或相似声音可能无法可靠区分，显示未知说话人。
4. 声纹仅用于文稿整理，不用于司法身份认定；data/voiceprints.json 升级时受保护。

快捷键
Ctrl+O 添加文件；Ctrl+Enter 开始；Ctrl+S 另存 TXT。

古典皮肤
“模型与系统”页可切换“山海古典／素简现代”。古典标题使用系统楷体、宋体或 Noto 字体回退，
不捆绑商业字体。工作台可选择 small 或 medium，配置会记住上次选择；每次任务仅加载一个模型。

内置模型与资源
- small：模型约 461 MiB，速度优先，适合日常转录。
- medium：模型约 1457 MiB，精度优先；建议按 3–5 GB 峰值内存、small 的约 2–4 倍 CPU 时间预留。
- 两个模型均使用 CPU int8，队列复用同一个所选模型，内存不随文件数成倍增长。
- large-v3 未内置。实际资源取决于 CPU、音频长度、搜索宽度和系统负载。

离线增量升级
- “模型与系统”页导入 .ttupdate；仍兼容读取旧 .tlupdate 清单格式。
- 升级前校验版本与旧文件哈希，自动备份，失败回滚。
- config.json、data、small 和 medium 不受修改；音频库、声纹库、录音和转录记录均受保护。
- 从观海·听涛 1.4.0 升级：在当前软件“模型与系统”页选择解压后的 .ttupdate，点击“一键升级”。
  当前程序自行校验、备份、安装与失败回滚；Windows 自动重启一次，不使用独立升级工具。

完整性与自检
在资源文件夹运行：powershell -ExecutionPolicy Bypass -File verify_package.ps1
命令行单文件：TingTao.exe --self-test "音频.wav" --output "结果.json"
双文件队列：TingTao.exe --batch-test "a.wav" "b.wav" --output "队列结果.json"
双文件合并：TingTao.exe --batch-test "a.wav" "b.wav" --merge --output "合并结果.json"

第三方组件见 THIRD_PARTY_NOTICES.txt 与 licenses。
"""

VERIFY_PS1 = r"""$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Join-Path $root 'SHA256SUMS.txt'
if (-not (Test-Path $manifest)) { throw 'SHA256SUMS.txt is missing.' }
$failed = 0
$checked = 0
foreach ($line in [System.IO.File]::ReadLines($manifest)) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $expected = $line.Substring(0, 64)
    $relative = $line.Substring(66).TrimStart('*')
    $path = Join-Path $root ($relative -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Write-Host "MISSING $relative"; $failed++; continue }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { Write-Host "FAILED  $relative"; $failed++ }
    $checked++
}
$launcher = Join-Path (Split-Path -Parent $root) 'TingTao.exe'
$launcherManifest = Join-Path $root 'LAUNCHER_SHA256.txt'
if ((Test-Path $launcher -PathType Leaf) -and (Test-Path $launcherManifest -PathType Leaf)) {
    $expected = (Get-Content -LiteralPath $launcherManifest -Raw).Trim().ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $launcher).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { Write-Host 'FAILED  ../TingTao.exe'; $failed++ } else { $checked++ }
}
if ($failed -gt 0) { throw "Package verification failed: $failed file(s)." }
Write-Host "OK: $checked files verified. Package integrity is valid."
"""


def pyinstaller_base(work: Path, stage: Path) -> list[str]:
    return [
        str(PYTHON), "-m", "PyInstaller", "--noconfirm", "--clean",
        "--paths", str(ROOT / "src"), "--distpath", str(stage), "--workpath", str(work),
        "--specpath", str(ROOT / "build-cache"),
    ]


def run_builds() -> None:
    if DIST_ROOT.exists():
        shutil.rmtree(DIST_ROOT)
    DIST_ROOT.mkdir(parents=True)
    command = pyinstaller_base(WORK, STAGE) + [
        "--onedir", "--windowed", "--name", "TingTao", "--icon", str(ROOT / "assets" / "app.ico"),
        "--collect-all", "faster_whisper", "--collect-all", "ctranslate2", "--collect-all", "av",
        "--collect-all", "docx", "--collect-all", "lxml", "--collect-all", "onnxruntime",
        "--collect-all", "cryptography",
        "--hidden-import", "offline_transcriber.main_window", str(ROOT / "src" / "run_app.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    shutil.move(str(STAGE / "TingTao"), str(DIST))
    launcher = pyinstaller_base(LAUNCHER_WORK, LAUNCHER_STAGE) + [
        "--onefile", "--windowed", "--name", "TingTaoLauncher", "--icon", str(ROOT / "assets" / "app.ico"),
        str(ROOT / "src" / "launcher.py"),
    ]
    subprocess.run(launcher, cwd=ROOT, check=True)
    shutil.copy2(LAUNCHER_STAGE / "TingTaoLauncher.exe", LAUNCHER)
    if not (DIST / "TingTao.exe").is_file() or not LAUNCHER.is_file():
        raise RuntimeError("Main executable or two-item launcher was not created")


def copy_assets() -> None:
    shutil.copytree(ROOT / "models", DIST / "models")
    shutil.copytree(ROOT / "ffmpeg", DIST / "ffmpeg")
    assets = DIST / "assets"
    assets.mkdir(parents=True)
    for name in (
        "guanhai-tingtao-logo-generated.png", "guanhai-tingtao-logo.png",
        "guanhai-tingtao-logo-256.png", "guanhai-tingtao-logo-64.png", "app.ico",
    ):
        shutil.copy2(ROOT / "assets" / name, assets / name)
    if (ROOT / "assets-manifest.json").is_file():
        shutil.copy2(ROOT / "assets-manifest.json", DIST / "assets-manifest.json")
    for name in ("output", "temp", "logs"):
        (DIST / "data" / name).mkdir(parents=True, exist_ok=True)
    config = {"language": "zh", "beam_size": 5, "vad_filter": True, "output_directory": "", "batch_mode": "queue", "theme": "classical", "model_name": "small", "speaker_enabled": False, "speaker_threshold": 0.55}
    (DIST / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / "使用说明.txt").write_text(USAGE, encoding="utf-8-sig")
    (DIST / "verify_package.ps1").write_text(VERIFY_PS1, encoding="utf-8-sig")


def copy_licenses() -> None:
    license_dir = DIST / "licenses"
    license_dir.mkdir(exist_ok=True)
    package_names = [
        "faster-whisper", "ctranslate2", "av", "tokenizers", "numpy", "PySide6",
        "huggingface-hub", "onnxruntime", "tqdm", "urllib3", "certifi", "python-docx", "lxml", "cryptography", "cffi",
    ]
    notices = [
        "观海·听涛\n第三方组件清单\n",
        "FFmpeg 6.1.1 essentials build (gyan.dev), GPL-3.0-or-later",
        "FFmpeg source: https://github.com/FFmpeg/FFmpeg",
        "Build information: https://www.gyan.dev/ffmpeg/builds/",
        "The unmodified FFmpeg executable is launched as a separate process; see ffmpeg/LICENSE.txt.",
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
    (DIST / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices), encoding="utf-8-sig")


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
        "platform": "Windows x64",
        "mode": "fully-offline-portable-two-item-layout",
        "layout": {"executable": "TingTao.exe", "resource_directory": "TingTao"},
        "models": ["Systran/faster-whisper-small", "Systran/faster-whisper-medium", "wespeaker/wespeaker-cnceleb-resnet34-LM"],
        "default_model": "small",
        "model_selection": True,
        "single_model_resident_per_task": True,
        "speaker_recognition": {"offline": True, "persistent_library": "data/voiceprints.json", "minimum_segment_seconds": 0.8},
        "minutes": {"offline_rule_based": True, "online_llm_required": False},
        "document_exports": ["txt", "md", "docx", "srt", "vtt", "json"],
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
    }
    (DIST / "build-info.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    if not PYTHON.is_file() or not PYINSTALLER.is_file():
        raise RuntimeError("Build virtual environment is missing")
    for model in ("small", "medium"):
        if not (ROOT / "models" / f"faster-whisper-{model}" / "model.bin").is_file():
            raise RuntimeError(f"Local {model} model is missing")
    run_builds()
    copy_assets()
    copy_licenses()
    write_build_info()
    print(f"Two-item Windows package built: {DIST_ROOT}")


if __name__ == "__main__":
    main()
