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
STAGE = ROOT / "build-cache" / "stage-1.6.6"
WORK = ROOT / "build-cache" / "pyinstaller-1.6.6"
UPDATER_STAGE = ROOT / "build-cache" / "updater-stage-1.6.6"
UPDATER_WORK = ROOT / "build-cache" / "updater-pyinstaller-1.6.6"
LAUNCHER_STAGE = ROOT / "build-cache" / "launcher-stage-1.6.6"
LAUNCHER_WORK = ROOT / "build-cache" / "launcher-pyinstaller-1.6.6"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYINSTALLER = ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
VERSION = "1.6.6"

USAGE = """观海·听涛 1.6.6 · 完全离线语音转录
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
2. 最近 60 秒历史波形右对齐并持续向左滚动；-12／-6／0 dB 分色电平显示实时峰值。提示音不会把麦克风回放到扬声器。
3. 自动防爆音默认开启，自动增益默认关闭，降噪默认关闭并可选择低／中／高；录音中也可切换，三项处理真实作用于写入的 WAV。
4. 防爆音不能修复麦克风或声卡输入端已经发生的削波；强降噪可能损失轻声和远场语音，重要录音建议先比较档位。
5. 录音时标志太阳在赭金与朱红间呼吸，标志边框在原色与朱红间切换，窗口红框、标题和任务栏图标同步提示。
6. 支持导入、重命名、关键词库、搜索、播放、导出、删除和批量加入转录。
7. 可选 AES-256-GCM 加密，音频内容、名称和关键词均加密；密码至少 8 字符且不会保存，遗忘无法恢复。
8. 播放或转录加密音频时生成会话临时副本，锁定或退出自动清除。导出的普通音频和文稿不自动加密。

开场与转录前处理
- 潮生、远山、听涛、星夜四套开场每次随机出现，标题与标志采用独立固定区域；海浪音效为本地资源，可点击跳过。
- 工作台默认“原声”，可选轻度或标准降噪与响度归一化；只处理识别用临时音频，不修改原文件。
- 清晰合成中文样本的三档识别文本一致，但不代表所有真实噪声环境都有收益；建议重要音频先与原声对照。

声纹识别
1. 勾选“识别讲话人并匹配声纹库”后按转录片段分离，导出文稿显示讲话人。
2. 完成后点击“命名声纹”保存到本机；以后转录自动匹配姓名。“模型与系统”页可管理声纹库。
3. 阈值越高越谨慎。短于 0.8 秒、重叠语音或相似声音可能无法可靠区分，显示未知说话人。
4. 声纹仅用于文稿整理，不用于司法身份认定；data/voiceprints.json 升级时受保护。

内嵌使用教学
- 左侧“使用教学”或 F1 打开“听涛学堂”，共 12 章详细图文与中文语音讲解。
- 每章包含原创四步流程图和当前软件真实界面截图，共 24 张本地 PNG；先读图，再对照界面操作。
- 支持全文搜索、上一章／下一章、播放／暂停／停止、进度拖动、音量及 0.75–1.5 倍速。
- 所有 WAV 讲解均随程序本地提供，播放不联网、不调用在线语音服务；离开教学页或退出自动停止。

快捷键
Ctrl+O 添加文件；Ctrl+Enter 开始；Ctrl+S 另存 TXT；F1 打开使用教学。

古典皮肤
“模型与系统”页可切换“山海古典／素简现代”。古典标题使用系统楷体、宋体或 Noto 字体回退，
不捆绑商业字体。工作台可选择 small 或 medium，配置会记住上次选择；每次任务仅加载一个模型。

内置模型与资源
- small：模型约 461 MiB，速度优先，适合日常转录。
- medium：模型约 1457 MiB，精度优先；建议按 3–5 GB 峰值内存、small 的约 2–4 倍 CPU 时间预留。
- 两个模型均使用 CPU int8，队列复用同一个所选模型，内存不随文件数成倍增长。
- large-v3 未内置。实际资源取决于 CPU、音频长度、搜索宽度和系统负载。

离线增量升级
- 直接选择收到的增量 ZIP 即可，无需解压或进入 TingTaoUpdate；仍兼容单独选择 .ttupdate。
- 软件自动定位唯一载荷并校验版本与文件哈希，在古典风确认页直接展示发行说明、文件数量和载荷大小。
- 点击“一键升级并重启”后自动备份、安装并启动新版，失败回滚，不使用独立升级工具。
- config.json、data、small 和 medium 不受修改；音频库、声纹库、录音和转录记录均受保护。
- 1.5.0／1.6.0 的旧流程会让正在运行的 exe 替换自身，Windows 会拒绝；请使用本过渡完整包，旧增量包不要再用。

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
        "ocean-intro.wav", "source-chime.wav",
    ):
        shutil.copy2(ROOT / "assets" / name, assets / name)
    shutil.copytree(ROOT / "assets" / "tutorial", assets / "tutorial")
    if (ROOT / "assets-manifest.json").is_file():
        shutil.copy2(ROOT / "assets-manifest.json", DIST / "assets-manifest.json")
    for name in ("output", "temp", "logs"):
        (DIST / "data" / name).mkdir(parents=True, exist_ok=True)
    config = {"language": "zh", "beam_size": 5, "vad_filter": True, "output_directory": "", "batch_mode": "queue", "theme": "classical", "model_name": "small", "speaker_enabled": False, "speaker_threshold": 0.55, "audio_preset": "original"}
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
        "model_update_policy": "1.6.6 updates application and local sound assets only; existing ASR, voiceprint models and user data are protected",
        "audio_presets": {"default": "original", "optional": ["light", "standard"], "modifies_source": False},
        "recording": {"history_waveform_seconds": 60, "peak_meter_db_ticks": [-12, -6, 0], "limiter_default": True, "automatic_gain_default": False, "denoise_levels": ["off", "low", "medium", "high"], "controls_live_during_recording": True, "window_and_taskbar_tally": True},
        "opening_scene": {"local_animation": True, "local_ocean_sound": True, "skippable": True},
        "tutorial": {"chapters": 12, "detailed_html": True, "local_chinese_narration": True, "audio_files": 12, "workflow_diagrams": 12, "real_interface_screenshots": 12, "visual_assets_offline": True, "audio_directory": "assets/tutorial", "search": True, "playback_rates": [0.75, 1.0, 1.25, 1.5], "keyboard_shortcut": "F1", "online_tts_required": False},
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
