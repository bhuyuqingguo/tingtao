from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from .update_common import read_update_package, safe_relative_path, sha256, validate_target
from .update_manager import UPDATE_RUNTIME_NAME


def rebuild_integrity_manifest(target: Path) -> None:
    files = sorted(
        path for path in target.rglob("*")
        if path.is_file() and path.name not in {"SHA256SUMS.txt", UPDATE_RUNTIME_NAME}
        and path.relative_to(target).parts[0].lower() != "data"
    )
    content = "".join(f"{sha256(path)} *{path.relative_to(target).as_posix()}\n" for path in files)
    temporary = target / "SHA256SUMS.txt.tingtao-new"
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target / "SHA256SUMS.txt")


def apply_update(package: str | Path, target: str | Path, log=lambda message: None) -> dict:
    package, target = Path(package), Path(target)
    manifest = read_update_package(package)
    target = validate_target(manifest, target)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = target / "data" / "update-backups" / f"{manifest['from_version']}-to-{manifest['to_version']}-{timestamp}"
    backup.mkdir(parents=True, exist_ok=False)
    replaced: list[str] = []
    deleted: list[str] = []
    added: list[str] = []
    log(f"版本：{manifest['from_version']} → {manifest['to_version']}")
    try:
        allow_medium = manifest.get("package_kind") == "application-with-model"
        allow_voiceprint = manifest.get("package_kind") == "application-with-voiceprint"
        with zipfile.ZipFile(package) as archive:
            for item in manifest["files"]:
                relative = safe_relative_path(item["path"], allow_medium, allow_voiceprint)
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_file():
                    backup_file = backup / relative
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_file)
                else:
                    added.append(relative)
                temporary = destination.with_name(destination.name + ".tingtao-new")
                with archive.open(f"payload/{relative}") as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                if sha256(temporary) != item["sha256"]:
                    raise RuntimeError(f"写入后哈希校验失败：{relative}")
                os.replace(temporary, destination)
                replaced.append(relative)
                log(f"已更新：{relative}")
            for relative_value in manifest.get("deletes", []):
                relative = safe_relative_path(relative_value)
                destination = target / relative
                if destination.is_file():
                    backup_file = backup / relative
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_file)
                    destination.unlink()
                    deleted.append(relative)
        for item in manifest["files"]:
            if sha256(target / item["path"]) != item["sha256"]:
                raise RuntimeError(f"升级后校验失败：{item['path']}")
        integrity_path = target / "SHA256SUMS.txt"
        if integrity_path.is_file():
            shutil.copy2(integrity_path, backup / "SHA256SUMS.txt")
        else:
            added.append("SHA256SUMS.txt")
        replaced.append("SHA256SUMS.txt")
        rebuild_integrity_manifest(target)
        report = {
            "success": True, "from_version": manifest["from_version"], "to_version": manifest["to_version"],
            "updated_files": len(replaced), "deleted_files": len(deleted), "backup": str(backup),
            "completed_at": datetime.now().astimezone().isoformat(),
        }
        log_directory = target / "data" / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        (log_directory / "last-update.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log("升级完成，全部文件校验通过；配置、音频库、声纹和记录均已保留。")
        return report
    except Exception:
        log("升级失败，正在回滚……")
        for relative in replaced:
            backup_file = backup / relative
            destination = target / relative
            if backup_file.is_file():
                shutil.copy2(backup_file, destination)
            elif relative in added:
                destination.unlink(missing_ok=True)
        for relative in deleted:
            backup_file = backup / relative
            if backup_file.is_file():
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, destination)
        log("已回滚到升级前状态。")
        raise
