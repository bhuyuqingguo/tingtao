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

UPGRADE_README = """观海·听涛 1.4.0 · 声纹与纪要离线增量升级包
==========================================
适用版本：观海·听涛 TingTao 1.3.0 → 观海·听涛 TingTao 1.4.0
平台：Windows x64

使用步骤
1. 完整解压本 ZIP。顶层严格只有 TingTaoUpdater.exe 和 TingTaoUpdate 两项。
2. 关闭主程序，运行外层 TingTaoUpdater.exe。
3. 选择 TingTaoUpdate 内的 TingTao-1.3.0-to-1.4.0.ttupdate 和旧版 TingTao 资源目录。
4. 点击“开始升级”，完成后运行原 TingTao.exe。

新版内容
- 离线说话人分离与持久声纹库，可命名、重命名、删除并在以后转录中自动匹配。
- 一键生成结构化纪要：重点、决定事项、待办与主题词，不使用在线大模型。
- 记录手动重命名和根据文稿内容命名。
- 导出 TXT、Markdown、DOCX（Word／WPS 兼容）、SRT、VTT、JSON。
- 修复模型下拉弹窗黑色背景，与古典／现代主题保持一致。

安全与保留内容
- 全程离线；安装前校验源版本、旧文件哈希、载荷大小和 SHA-256，失败自动回滚。
- config.json、data（声纹库、记录、日志、输出）、small 和 medium 均不修改。
- 本包仅新增约 25.3 MiB 的 WeSpeaker 中文声纹模型，不重复携带两个转录模型。
- 短于 0.8 秒或重叠语音可能标记为未知说话人，声纹结果不用于司法身份认定。

命令行验收（可选）
TingTaoUpdater.exe --headless --package "TingTaoUpdate\\TingTao-1.3.0-to-1.4.0.ttupdate" --target "旧 TingTao 目录的完整路径"

注意：旧版程序文件若被手工修改，更新器会拒绝覆盖。升级时不要关闭更新器或切断电源。
"""


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
    parser = argparse.ArgumentParser(description="Create a two-top-level-item TingTao dual-model incremental package")
    parser.add_argument("--old", type=Path, default=ROOT / "dist" / "Windows-x64-1.3.0" / "TingTao")
    parser.add_argument("--new", type=Path, default=ROOT / "dist" / "Windows-x64" / "TingTao")
    parser.add_argument("--platform", choices=("windows", "kylin"), default="windows")
    parser.add_argument("--work", type=Path, default=ROOT / "build-cache" / "update-package-1.4.0")
    parser.add_argument("--archive", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    old = args.old.resolve()
    new = args.new.resolve()
    windows = args.platform == "windows"
    updater_name = "TingTaoUpdater.exe" if windows else "TingTaoUpdater"
    platform_name = "Windows x64" if windows else "Kylin V10 x86_64"
    archive = args.archive or ROOT / "dist" / (
        f"TingTao-1.3.0-to-1.4.0-{'Windows-x64' if windows else 'Kylin-x86_64'}-Incremental.zip"
    )
    update = args.work / "TingTao-1.3.0-to-1.4.0.ttupdate"

    old_info = json.loads((old / "build-info.json").read_text(encoding="utf-8"))
    new_info = json.loads((new / "build-info.json").read_text(encoding="utf-8"))
    if old_info.get("version") != "1.3.0" or new_info.get("version") != "1.4.0":
        raise RuntimeError("Expected source 1.3.0 and target 1.4.0")
    updater = new / updater_name
    voiceprint_model = new / "models" / "wespeaker-cnceleb-resnet34-LM" / "cnceleb_resnet34_LM.onnx"
    if not updater.is_file() or not voiceprint_model.is_file():
        raise RuntimeError("Updater or embedded voiceprint model is missing")

    old_files = files_by_relative(old)
    new_files = files_by_relative(new)
    changed = []
    for relative, new_path in sorted(new_files.items()):
        new_hash = sha256(new_path)
        old_path = old_files.get(relative)
        old_hash = sha256(old_path) if old_path else None
        if old_hash == new_hash:
            continue
        changed.append({
            "path": relative,
            "action": "replace",
            "size": new_path.stat().st_size,
            "sha256": new_hash,
            "from_sha256": old_hash,
        })
    deletes = sorted(relative for relative in old_files.keys() - new_files.keys())
    if any(relative.lower().startswith("models/") for relative in deletes):
        raise RuntimeError("Incremental package must not delete models")
    if not any(item["path"] == "models/wespeaker-cnceleb-resnet34-LM/cnceleb_resnet34_LM.onnx" for item in changed):
        raise RuntimeError("Incremental package must add the voiceprint model")
    if not changed:
        raise RuntimeError("No changed application files found")

    manifest = {
        "format": "tinglan-offline-update-v1",
        "package_kind": "application-with-voiceprint",
        "product": "TingTao",
        "product_name_zh": "观海·听涛",
        "from_version": "1.3.0",
        "to_version": "1.4.0",
        "platform": platform_name,
        "created_at": datetime.now().astimezone().isoformat(),
        "files": changed,
        "deletes": deletes,
        "total_payload_bytes": sum(item["size"] for item in changed),
        "protected_paths": ["data", "models/faster-whisper-small", "models/faster-whisper-medium", "config.json"],
        "release_notes": "新增离线说话人分离、持久声纹库、一键结构化纪要、记录命名与 TXT/MD/DOCX 导出；修复主题弹窗。仅新增声纹模型，保护已有识别模型、配置、声纹库和记录。",
    }
    args.work.mkdir(parents=True, exist_ok=True)
    if update.exists():
        update.unlink()
    with zipfile.ZipFile(update, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
        package.writestr("update-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for item in changed:
            package.write(new_files[item["path"]], arcname=f"payload/{item['path']}")
    checked = read_update_package(update)
    if checked["total_payload_bytes"] != manifest["total_payload_bytes"] or checked["package_kind"] != "application-with-voiceprint":
        raise RuntimeError("Update payload verification failed")

    info = {
        "from_version": "1.3.0",
        "to_version": "1.4.0",
        "changed_files": len(changed),
        "deleted_files": len(deletes),
        "payload_bytes": manifest["total_payload_bytes"],
        "ttupdate_bytes": update.stat().st_size,
        "ttupdate_sha256": sha256(update),
        "models_included": ["wespeaker-cnceleb-resnet34-LM"],
        "small_model_modified": False,
        "user_data_modified": False,
        "top_level_items": [updater_name, "TingTaoUpdate"],
    }
    readme = UPGRADE_README
    if not windows:
        readme = readme.replace("Windows x64", "银河麒麟 V10 x86_64").replace(
            "TingTaoUpdater.exe", "TingTaoUpdater"
        ).replace("TingTaoUpdate\\", "TingTaoUpdate/")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
        package.write(updater, arcname=updater_name)
        package.write(update, arcname=f"TingTaoUpdate/{update.name}")
        package.writestr("TingTaoUpdate/升级说明.txt", readme.encode("utf-8-sig"))
        package.writestr("TingTaoUpdate/update-package-info.json", json.dumps(info, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as package:
        bad = package.testzip()
        if bad:
            raise RuntimeError(f"Incremental ZIP CRC failure: {bad}")
        top_level = {Path(name).parts[0] for name in package.namelist() if Path(name).parts}
        if top_level != {updater_name, "TingTaoUpdate"}:
            raise RuntimeError(f"Incremental archive has invalid top-level entries: {top_level}")
    print(json.dumps({
        "update": str(update),
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        **info,
        "deletes": deletes,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
