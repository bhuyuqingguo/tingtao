from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .paths import APP_ROOT, DATA_ROOT, ensure_data_directories
from .update_common import read_update_package, validate_target


def updater_name() -> str:
    return "TingTaoUpdater.exe" if os.name == "nt" else "TingTaoUpdater"


def inspect_update(package: str | Path) -> dict:
    manifest = read_update_package(package)
    validate_target(manifest, APP_ROOT)
    return manifest


def launch_update(package: str | Path) -> Path:
    manifest = inspect_update(package)
    ensure_data_directories()
    name = updater_name()
    updater_source = APP_ROOT / name
    if not updater_source.is_file():
        raise FileNotFoundError(f"部署包缺少 {name}")
    runtime_directory = DATA_ROOT / "update-runtime"
    runtime_directory.mkdir(parents=True, exist_ok=True)
    updater_copy = runtime_directory / name
    shutil.copy2(updater_source, updater_copy)
    if os.name != "nt":
        updater_copy.chmod(0o755)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        [
            str(updater_copy), "--package", manifest["package_path"], "--target", str(APP_ROOT),
            "--parent-pid", str(os.getpid()), "--restart",
        ],
        cwd=runtime_directory,
        close_fds=True,
        creationflags=flags,
    )
    return updater_copy
