from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .paths import APP_ROOT, DATA_ROOT, ensure_data_directories
from .update_common import read_update_package, validate_target


UPDATE_RUNTIME_NAME = ".tingtao-self-update.exe" if os.name == "nt" else ".tingtao-self-update"


def update_runtime_path() -> Path:
    """A temporary copy with private dependencies inside the protected data area."""
    return DATA_ROOT / "update-staging" / "runtime" / UPDATE_RUNTIME_NAME


def inspect_update(package: str | Path) -> dict:
    manifest = read_update_package(package)
    validate_target(manifest, APP_ROOT)
    return manifest


def launch_update(package: str | Path) -> Path:
    """Apply through a temporary copy of this app, never a separate updater.

    A running Windows image cannot replace its own executable. The copied
    runtime has a private _internal, starts after the main UI closes, updates
    TingTao.exe, starts the new UI and is removed by that new UI.
    """
    manifest = inspect_update(package)
    ensure_data_directories()
    staging = DATA_ROOT / "update-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    staged_package = staging / "pending.ttupdate"
    shutil.copy2(manifest["package_path"], staged_package)
    if not getattr(sys, "frozen", False):
        # Source runs have no locked executable; the caller invokes apply_update.
        return staged_package
    executable = Path(sys.executable).resolve()
    runtime = update_runtime_path()
    runtime.parent.mkdir(parents=True)
    # A copied exe still cannot share _internal: DLLs and base_library.zip
    # would remain locked. Give the embedded runtime a private dependency copy.
    shutil.copytree(APP_ROOT / "_internal", runtime.parent / "_internal")
    shutil.copy2(executable, runtime)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        subprocess.Popen(
            [str(runtime), "--apply-update", str(staged_package), "--update-target", str(APP_ROOT),
             "--parent-pid", str(os.getpid()), "--restart"],
            cwd=staging, close_fds=True, creationflags=flags,
        )
    except Exception:
        runtime.unlink(missing_ok=True)
        raise
    return staged_package


def cleanup_stale_update_runtime(attempts: int = 10) -> None:
    """Remove the previous process's temporary image after it has exited."""
    if not getattr(sys, "frozen", False):
        return
    staging = DATA_ROOT / "update-staging"
    if not staging.exists():
        return
    try:
        shutil.rmtree(staging)
    except OSError:
        if attempts > 1:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, lambda: cleanup_stale_update_runtime(attempts - 1))


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
            executable = Path(target).resolve() / ("TingTao.exe" if os.name == "nt" else "TingTao")
            subprocess.Popen([str(executable)], cwd=Path(target), close_fds=True)
        return 0
    except Exception as exc:
        message = f"升级未完成，已回滚到升级前状态。\n\n{exc}\n\n个人配置、音频库和转录记录未修改。"
        print(json_report({"success": False, "error": str(exc)}))
        try:
            log_directory = Path(target) / "data" / "logs"
            log_directory.mkdir(parents=True, exist_ok=True)
            (log_directory / "last-update-error.json").write_text(json_report({"success": False, "error": str(exc)}), encoding="utf-8")
        except OSError:
            pass
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "观海·听涛升级未完成", 0x30)
        return 1


def json_report(value: dict) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)
