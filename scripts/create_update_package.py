from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from offline_transcriber.update_common import read_update_package  # noqa: E402

EXCLUDED_FILES = {"config.json", "SHA256SUMS.txt", "LAUNCHER_SHA256.txt"}
VOICEPRINT_PREFIX = "models/wespeaker-cnceleb-resnet34-LM/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if not path.is_file():
        return False
    normalized = relative.as_posix()
    if normalized in EXCLUDED_FILES or not relative.parts or relative.parts[0] == "data":
        return False
    if relative.parts[0] == "models":
        return normalized.lower().startswith(VOICEPRINT_PREFIX.lower()) and len(relative.parts) >= 3
    return True


def files_by_relative(root: Path) -> dict[str, Path]:
    return {path.relative_to(root).as_posix(): path for path in root.rglob("*") if included(path, root)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a two-item TingTao in-app incremental update package")
    parser.add_argument("--old", type=Path, default=ROOT / "build-cache" / "self-update-acceptance-1.6.5" / "TingTao")
    parser.add_argument("--new", type=Path, default=ROOT / "dist" / "Windows-x64" / "TingTao")
    parser.add_argument("--platform", choices=("windows", "kylin"), default="windows")
    parser.add_argument("--work", type=Path, default=ROOT / "build-cache" / "update-package-1.6.6")
    parser.add_argument("--archive", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    old, new = args.old.resolve(), args.new.resolve()
    windows = args.platform == "windows"
    launcher_name = "TingTao.exe" if windows else "TingTao"
    platform_name = "Windows x64" if windows else "Kylin V10 x86_64"
    old_info = json.loads((old / "build-info.json").read_text(encoding="utf-8"))
    new_info = json.loads((new / "build-info.json").read_text(encoding="utf-8"))
    from_version, to_version = str(old_info["version"]), str(new_info["version"])
    if from_version == to_version:
        raise RuntimeError("Source and target versions must differ")
    archive = args.archive or ROOT / "dist" / f"TingTao-{from_version}-to-{to_version}-{'Windows-x64' if windows else 'Kylin-x86_64'}-Incremental.zip"
    update = args.work / f"TingTao-{from_version}-to-{to_version}.ttupdate"
    launcher = new.parent / launcher_name
    if not launcher.is_file():
        raise RuntimeError("Two-item launcher is missing")

    old_files, new_files = files_by_relative(old), files_by_relative(new)
    changed = []
    for relative, new_path in sorted(new_files.items()):
        new_hash = sha256(new_path)
        old_path = old_files.get(relative)
        old_hash = sha256(old_path) if old_path else None
        if old_hash != new_hash:
            changed.append({"path": relative, "action": "replace", "size": new_path.stat().st_size,
                            "sha256": new_hash, "from_sha256": old_hash})
    deletes = sorted(relative for relative in old_files.keys() - new_files.keys())
    if any(relative.lower().startswith("models/") for relative in deletes):
        raise RuntimeError("Incremental package must not delete models")
    if not changed:
        raise RuntimeError("No changed application files found")
    manifest = {
        "format": "tinglan-offline-update-v1", "package_kind": "application",
        "product": "TingTao", "product_name_zh": "观海·听涛",
        "from_version": from_version, "to_version": to_version, "platform": platform_name,
        "created_at": datetime.now().astimezone().isoformat(), "files": changed, "deletes": deletes,
        "total_payload_bytes": sum(item["size"] for item in changed),
        "protected_paths": ["data", "models/faster-whisper-small", "models/faster-whisper-medium", "config.json"],
        "release_notes": "一、12 章新增步骤流程图：每章四个关键步骤与重要提醒一图读懂，采用统一古典配色。\n二、12 张真实界面截图：对应工作台、录音与音频库、转录记录、模型与系统等当前软件页面。\n三、图文声一体学习：先读流程图，再对照界面截图和详细正文，同时可播放本章中文语音。\n四、完全离线与安全保留：24 张 PNG 随程序本地提供，不访问网络；配置、音频库、记录和模型保持不变。",
    }
    args.work.mkdir(parents=True, exist_ok=True)
    update.unlink(missing_ok=True)
    with zipfile.ZipFile(update, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
        package.writestr("update-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for item in changed:
            package.write(new_files[item["path"]], arcname=f"payload/{item['path']}")
    checked = read_update_package(update)
    if checked["total_payload_bytes"] != manifest["total_payload_bytes"]:
        raise RuntimeError("Update payload verification failed")

    info = {
        "from_version": from_version, "to_version": to_version, "changed_files": len(changed),
        "deleted_files": len(deletes), "payload_bytes": manifest["total_payload_bytes"],
        "ttupdate_bytes": update.stat().st_size, "ttupdate_sha256": sha256(update),
        "embedded_updater": True, "standalone_updater_included": False,
        "small_and_medium_models_modified": False, "user_data_modified": False,
        "top_level_items": [launcher_name, "TingTaoUpdate"],
    }
    readme = f"""观海·听涛 {to_version} · 教学流程图与真实截图离线增量包
================================================
适用版本：{from_version} → {to_version}；平台：{platform_name}

一键升级
1. 打开现有观海·听涛 {from_version}，进入“模型与系统”→“导入离线增量包”。
2. 直接选择本 ZIP，无需解压或进入 TingTaoUpdate。
3. 阅读发行说明后点击“一键升级并重启”，软件自动校验、备份、安装并启动新版。
4. 不需要任何独立升级工具；失败自动回滚。

新版内容
- 12 章各新增一张四步流程图，标明操作顺序与关键提醒，统一古典配色。
- 12 张当前软件真实界面截图，覆盖工作台、录音、音频库、记录和系统设置。
- 点击流程图或截图可在软件内查看原图；详细正文与本地中文语音继续保留。
- 共新增 24 张本地 PNG，看图学习全程离线。

安全与保留内容
- 安装前校验源版本、旧文件哈希、载荷大小和 SHA-256，失败自动回滚。
- config.json、data（音频库、声纹库、记录、日志、输出）、small 和 medium 均不修改。
- 增量 ZIP 顶层严格只有 {launcher_name} 与 TingTaoUpdate 两项。
"""
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
        package.write(launcher, arcname=launcher_name)
        package.write(update, arcname=f"TingTaoUpdate/{update.name}")
        package.writestr("TingTaoUpdate/升级说明.txt", readme.encode("utf-8-sig"))
        package.writestr("TingTaoUpdate/update-package-info.json", json.dumps(info, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as package:
        bad = package.testzip()
        if bad:
            raise RuntimeError(f"Incremental ZIP CRC failure: {bad}")
        top_level = {Path(name).parts[0] for name in package.namelist() if Path(name).parts}
        if top_level != {launcher_name, "TingTaoUpdate"}:
            raise RuntimeError(f"Incremental archive has invalid top-level entries: {top_level}")
    print(json.dumps({"update": str(update), "archive": str(archive), "archive_bytes": archive.stat().st_size,
                      "archive_sha256": sha256(archive), **info, "deletes": deletes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
