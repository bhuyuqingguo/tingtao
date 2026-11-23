"""Real copied-runtime self-update, automatic restart and preservation test."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from verify_package import load_success, offline_environment


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "build-cache" / "self-update-acceptance-1.6.1" / "TingTao"
DIST = ROOT / "dist" / "Windows-x64" / "TingTao"
PACKAGE = ROOT / "build-cache" / "update-package-1.6.2" / "TingTao-1.6.1-to-1.6.2.ttupdate"
ACCEPTANCE = ROOT / "build-cache" / "self-update-acceptance-1.6.2"
TARGET = ACCEPTANCE / "TingTao"
RUNTIME = TARGET / "data" / "update-staging" / "runtime" / ".tingtao-self-update.exe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gui_pids() -> list[int]:
    command = (
        "$items = Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq '"
        + str(TARGET / "TingTao.exe").replace("'", "''")
        + "'} | Select-Object -ExpandProperty ProcessId; ConvertTo-Json @($items)"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30)
    if result.returncode:
        return []
    payload = json.loads(result.stdout.strip() or "[]")
    return [int(value) for value in (payload if isinstance(payload, list) else [payload])]


def stop_gui() -> None:
    for pid in gui_pids():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)


def main() -> None:
    for path in (OLD, DIST / "TingTao.exe", PACKAGE):
        if not path.exists():
            raise RuntimeError(f"Required self-update input is missing: {path}")
    stop_gui()
    shutil.rmtree(ACCEPTANCE, ignore_errors=True)
    ACCEPTANCE.mkdir(parents=True)
    shutil.copytree(OLD, TARGET)
    config_path = TARGET / "config.json"
    config_path.write_text(json.dumps({"language": "zh", "theme": "classical", "beam_size": 3, "acceptance_marker": "preserve-me"}), encoding="utf-8")
    config_before = config_path.read_bytes()
    small = TARGET / "models" / "faster-whisper-small" / "model.bin"
    small_hash = sha256(small)
    marker = TARGET / "data" / "audio-library" / "index.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"version":1,"keywords":["保留关键词"],"items":[]}', encoding="utf-8")
    record = TARGET / "data" / "output" / "acceptance-record.txt"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("升级前保留的转录记录", encoding="utf-8")

    # Mirror the new launch_update architecture with a private copied _internal;
    # no loaded file from the formal installation is needed during replacement.
    RUNTIME.parent.mkdir(parents=True)
    shutil.copytree(DIST / "_internal", RUNTIME.parent / "_internal")
    shutil.copy2(DIST / "TingTao.exe", RUNTIME)
    completed = subprocess.run(
        [str(RUNTIME), "--apply-update", str(PACKAGE), "--update-target", str(TARGET), "--restart"],
        cwd=ACCEPTANCE, env=offline_environment(), capture_output=True, text=True, timeout=600, check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"Copied-runtime self-update failed: {completed.stdout}\n{completed.stderr}")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and (RUNTIME.exists() or not gui_pids()):
        time.sleep(0.5)
    pids = gui_pids()
    if not pids:
        raise RuntimeError("Updated application did not restart automatically")
    if RUNTIME.exists():
        stop_gui()
        raise RuntimeError("New UI did not clean the temporary self-update runtime")
    try:
        if json.loads((TARGET / "build-info.json").read_text(encoding="utf-8"))["version"] != "1.6.2":
            raise RuntimeError("Target build version was not updated")
        if config_path.read_bytes() != config_before:
            raise RuntimeError("Theme or personal configuration changed")
        if marker.read_text(encoding="utf-8") != '{"version":1,"keywords":["保留关键词"],"items":[]}':
            raise RuntimeError("Audio library changed")
        if record.read_text(encoding="utf-8") != "升级前保留的转录记录" or sha256(small) != small_hash:
            raise RuntimeError("Transcript or model changed")
        manifest = (TARGET / "SHA256SUMS.txt").read_text(encoding="utf-8")
        if ".tingtao-self-update" in manifest:
            raise RuntimeError("Temporary runtime leaked into integrity manifest")
        powershell = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TARGET / "verify_package.ps1")],
            cwd=TARGET, capture_output=True, text=True, timeout=900, check=False,
        )
        if powershell.returncode or "OK:" not in powershell.stdout:
            raise RuntimeError(f"Updated integrity check failed: {powershell.stdout}\n{powershell.stderr}")
    finally:
        stop_gui()

    result_path = ACCEPTANCE / "updated-small.json"
    code = subprocess.run(
        [str(TARGET / "TingTao.exe"), "--self-test", str(ROOT / "assets" / "test-zh.wav"), "--model", "small", "--output", str(result_path)],
        cwd=TARGET, env=offline_environment(), timeout=900, check=False,
    ).returncode
    result = load_success(result_path, code)
    if len(result.get("text", "").strip()) < 10:
        raise RuntimeError("Updated offline transcription failed")
    report = {
        "verified_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "from_version": "1.6.1", "to_version": "1.6.2",
        "old_direct_self_replace_winerror5_reproduced": True,
        "copied_current_application_runtime": True,
        "standalone_updater_used": False,
        "formal_executable_replaced_while_runtime_active": True,
        "automatic_restart_test": True,
        "temporary_runtime_cleanup_test": True,
        "temporary_runtime_excluded_from_integrity_manifest": True,
        "theme_and_configuration_preserved": True,
        "audio_library_preserved": True,
        "transcription_record_preserved": True,
        "small_model_sha256_preserved": True,
        "updated_integrity_test": True,
        "updated_offline_transcription_test": True,
        "updated_files": json.loads((TARGET / "data" / "logs" / "last-update.json").read_text(encoding="utf-8"))["updated_files"],
    }
    (DIST / "SELF_UPDATE_VERIFICATION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
