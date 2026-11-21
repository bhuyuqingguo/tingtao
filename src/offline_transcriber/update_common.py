from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


UPDATE_FORMAT = "tinglan-offline-update-v1"
PROTECTED_PREFIXES = ("data", "models")
PROTECTED_FILES = {"config.json"}
MEDIUM_MODEL_PREFIX = "models/faster-whisper-medium/"
VOICEPRINT_MODEL_PREFIX = "models/wespeaker-cnceleb-resnet34-LM/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative_path(value: str, allow_medium_model: bool = False, allow_voiceprint_model: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError(f"非法升级文件路径：{value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ValueError(f"非法升级文件路径：{value}")
    normalized = path.as_posix()
    lower = normalized.lower()
    first = path.parts[0].lower()
    medium_file = allow_medium_model and lower.startswith(MEDIUM_MODEL_PREFIX) and len(path.parts) >= 3
    voiceprint_file = allow_voiceprint_model and lower.startswith(VOICEPRINT_MODEL_PREFIX.lower()) and len(path.parts) >= 3
    if first == "data" or (first == "models" and not (medium_file or voiceprint_file)) or lower in PROTECTED_FILES:
        raise ValueError(f"升级包不能修改用户数据或受保护模型：{value}")
    return normalized


def read_update_package(package: str | Path) -> dict[str, Any]:
    package_path = Path(package)
    if not package_path.is_file():
        raise FileNotFoundError(f"找不到升级包：{package_path}")
    with zipfile.ZipFile(package_path) as archive:
        try:
            manifest = json.loads(archive.read("update-manifest.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("升级包缺少有效的 update-manifest.json") from exc
        if manifest.get("format") != UPDATE_FORMAT:
            raise ValueError("升级包格式不受支持")
        package_kind = manifest.get("package_kind")
        if package_kind not in {"application", "application-with-model", "application-with-voiceprint"}:
            raise ValueError("升级包类型不受支持")
        allow_medium = package_kind == "application-with-model"
        allow_voiceprint = package_kind == "application-with-voiceprint"
        if manifest.get("product") not in {"TingTao", "TingLan", "LocalTranscriber"}:
            raise ValueError("升级包与当前产品不匹配")
        for key in ("from_version", "to_version", "files"):
            if key not in manifest:
                raise ValueError(f"升级清单缺少字段：{key}")
        if manifest["from_version"] == manifest["to_version"]:
            raise ValueError("源版本与目标版本不能相同")
        seen = set()
        for item in manifest["files"]:
            relative = safe_relative_path(
                item.get("path", ""), allow_medium_model=allow_medium, allow_voiceprint_model=allow_voiceprint,
            )
            if relative.lower() in seen:
                raise ValueError(f"升级包包含重复路径：{relative}")
            seen.add(relative.lower())
            if item.get("action", "replace") != "replace":
                raise ValueError("当前仅支持 replace 文件操作")
            payload_name = f"payload/{relative}"
            if payload_name not in archive.namelist():
                raise ValueError(f"升级包缺少文件：{relative}")
            digest = hashlib.sha256()
            payload_size = 0
            with archive.open(payload_name) as payload:
                for block in iter(lambda: payload.read(4 * 1024 * 1024), b""):
                    payload_size += len(block)
                    digest.update(block)
            if payload_size != int(item["size"]):
                raise ValueError(f"文件大小校验失败：{relative}")
            if digest.hexdigest() != item["sha256"]:
                raise ValueError(f"文件哈希校验失败：{relative}")
        for relative in manifest.get("deletes", []):
            safe_relative_path(relative)
        manifest["total_payload_bytes"] = sum(int(item["size"]) for item in manifest["files"])
        manifest["package_path"] = str(package_path.resolve())
        return manifest


def validate_target(manifest: dict[str, Any], target: str | Path) -> Path:
    target_path = Path(target).resolve()
    build_info_path = target_path / "build-info.json"
    if not build_info_path.is_file():
        raise ValueError("目标目录不是有效的观海·听涛／听澜部署目录")
    build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
    current_version = str(build_info.get("version", ""))
    if current_version != manifest["from_version"]:
        raise ValueError(
            f"版本不匹配：升级包要求 {manifest['from_version']}，目标目录为 {current_version or '未知版本'}"
        )
    allow_medium = manifest.get("package_kind") == "application-with-model"
    allow_voiceprint = manifest.get("package_kind") == "application-with-voiceprint"
    for item in manifest["files"]:
        relative = safe_relative_path(
            item["path"], allow_medium_model=allow_medium, allow_voiceprint_model=allow_voiceprint,
        )
        target_file = target_path / relative
        expected_old = item.get("from_sha256")
        if expected_old:
            if not target_file.is_file():
                raise ValueError(f"目标目录缺少待升级文件：{relative}")
            if sha256(target_file) != expected_old:
                raise ValueError(f"目标文件已被修改，不能安全增量升级：{relative}")
        elif target_file.exists() and target_file.is_dir():
            raise ValueError(f"目标路径与目录冲突：{relative}")
    for relative in manifest.get("deletes", []):
        target_file = target_path / safe_relative_path(relative)
        if target_file.exists() and not target_file.is_file():
            raise ValueError(f"待移除路径不是文件：{relative}")
    return target_path
