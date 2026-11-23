from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .paths import APP_ROOT, DATA_ROOT, ensure_data_directories
from .update_common import read_update_package, validate_target


def inspect_update(package: str | Path) -> dict:
    manifest = read_update_package(package)
    validate_target(manifest, APP_ROOT)
    return manifest


def launch_update(package: str | Path) -> Path:
    """Stage and apply through this application's own executable, never a separate updater."""
    manifest = inspect_update(package)
    ensure_data_directories()
    staging = DATA_ROOT / "update-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    staged_package = staging / "pending.ttupdate"
    shutil.copy2(manifest["package_path"], staged_package)
    if not getattr(sys, "frozen", False):
        # Source runs have no locked executable; the caller can invoke apply_update directly.
        return staged_package
    executable = Path(sys.executable).resolve()
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        [str(executable), "--apply-update", str(staged_package), "--update-target", str(APP_ROOT),
         "--parent-pid", str(os.getpid()), "--restart"],
        cwd=staging, close_fds=True, creationflags=flags,
    )
    return staged_package


def wait_for_parent(pid: int, timeout: float = 60.0) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.2)
    time.sleep(0.5)


def run_embedded_update(package: str | Path, target: str | Path, parent_pid: int = 0, restart: bool = False) -> int:
    from .update_engine import apply_update

    try:
        wait_for_parent(parent_pid)
        report = apply_update(package, target, print)
        print(json_report(report))
        if restart:
            executable = Path(sys.executable).resolve()
            subprocess.Popen([str(executable)], cwd=Path(target), close_fds=True)
        return 0
    except Exception as exc:
        print(json_report({"success": False, "error": str(exc)}))
        return 1


def json_report(value: dict) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)
