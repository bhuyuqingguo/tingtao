from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from verify_package import load_success, offline_environment


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "dist" / "Windows-x64-1.4.0" / "TingTao"
DIST_ROOT = ROOT / "dist" / "Windows-x64"
DIST = DIST_ROOT / "TingTao"
ARCHIVE = ROOT / "dist" / "TingTao-1.4.0-to-1.5.0-Windows-x64-Incremental.zip"
ACCEPTANCE = ROOT / "build-cache" / "update-acceptance-1.5.0"
AUDIO = ROOT / "assets" / "test-zh.wav"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    for path in (OLD, DIST, ARCHIVE, AUDIO):
        if not path.exists():
            raise RuntimeError(f"Required update acceptance input is missing: {path}")
    if ACCEPTANCE.exists():
        shutil.rmtree(ACCEPTANCE)
    ACCEPTANCE.mkdir(parents=True)
    incremental = ACCEPTANCE / "incremental"
    with zipfile.ZipFile(ARCHIVE) as archive:
        top_level = {Path(name).parts[0] for name in archive.namelist() if Path(name).parts}
        if top_level != {"TingTao.exe", "TingTaoUpdate"} or archive.testzip():
            raise RuntimeError(f"Incremental ZIP rule or CRC failed: {top_level}")
        archive.extractall(incremental)
    package = incremental / "TingTaoUpdate" / "TingTao-1.4.0-to-1.5.0.ttupdate"
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if any(name.startswith("payload/data/") or name == "payload/config.json" for name in names):
            raise RuntimeError("Incremental package contains protected user data")
        if any(name.lower().endswith("tingtaoupdater.exe") for name in names):
            raise RuntimeError("Incremental package still contains a standalone updater")
        if archive.testzip():
            raise RuntimeError("Update container CRC validation failed")

    target = ACCEPTANCE / "TingTao"
    shutil.copytree(OLD, target)
    config_path = target / "config.json"
    config_path.write_text(json.dumps({"language": "zh", "beam_size": 3, "acceptance_marker": "preserve-me"}), encoding="utf-8")
    config_before = config_path.read_bytes()
    small_path = target / "models" / "faster-whisper-small" / "model.bin"
    small_before = sha256(small_path)
    record = target / "data" / "output" / "acceptance-record.txt"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("升级前保留的转录记录", encoding="utf-8")
    audio_marker = target / "data" / "audio-library" / "index.json"
    audio_marker.parent.mkdir(parents=True, exist_ok=True)
    audio_marker.write_text('{"version":1,"keywords":["保留关键词"],"items":[]}', encoding="utf-8")
    executable = target / "TingTao.exe"
    old_exe_hash = sha256(executable)
    embedded_engine = DIST / "TingTao.exe"

    def run_embedded() -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(embedded_engine), "--apply-update", str(package), "--update-target", str(target)],
            cwd=DIST, env=offline_environment(), capture_output=True, text=True, timeout=1800, check=False,
        )

    build_info_path = target / "build-info.json"
    original_build_info = build_info_path.read_bytes()
    build_info_path.write_text(json.dumps({"application": "TingTao", "version": "9.9.9"}), encoding="utf-8")
    rejected = run_embedded()
    if rejected.returncode == 0 or (target / "data" / "update-backups").exists():
        raise RuntimeError("Wrong-version update was accepted or wrote before validation")
    if sha256(executable) != old_exe_hash or config_path.read_bytes() != config_before:
        raise RuntimeError("Wrong-version update modified the target")
    build_info_path.write_bytes(original_build_info)

    completed = run_embedded()
    report_path = target / "data" / "logs" / "last-update.json"
    if completed.returncode != 0 or not report_path.is_file():
        raise RuntimeError(f"Embedded update failed: {completed.stdout}\n{completed.stderr}")
    update_report = json.loads(report_path.read_text(encoding="utf-8"))
    if json.loads(build_info_path.read_text(encoding="utf-8")).get("version") != "1.5.0":
        raise RuntimeError("Updated build information is incorrect")
    if not executable.is_file() or sha256(executable) == old_exe_hash:
        raise RuntimeError("Application was not updated")
    if (target / "TingTaoUpdater.exe").exists():
        raise RuntimeError("Legacy standalone updater was not removed")
    if config_path.read_bytes() != config_before or record.read_text(encoding="utf-8") != "升级前保留的转录记录":
        raise RuntimeError("User configuration or record changed")
    if audio_marker.read_text(encoding="utf-8") != '{"version":1,"keywords":["保留关键词"],"items":[]}':
        raise RuntimeError("Audio library data changed")
    if sha256(small_path) != small_before:
        raise RuntimeError("Existing small model changed")
    backup = Path(update_report["backup"])
    if not (backup / "TingTao.exe").is_file() or not (backup / "TingTaoUpdater.exe").is_file():
        raise RuntimeError("Replaced executable and removed legacy updater were not backed up")

    powershell = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target / "verify_package.ps1")],
        cwd=target, capture_output=True, text=True, timeout=900, check=False,
    )
    if powershell.returncode != 0 or "OK:" not in powershell.stdout:
        raise RuntimeError(f"Updated integrity manifest failed: {powershell.stdout}\n{powershell.stderr}")
    result_path = ACCEPTANCE / "updated-small.json"
    code = subprocess.run(
        [str(executable), "--self-test", str(AUDIO), "--model", "small", "--output", str(result_path)],
        cwd=target, env=offline_environment(), timeout=900, check=False,
    ).returncode
    result = load_success(result_path, code)
    if "small" not in result.get("model", "") or len(result.get("text", "").strip()) < 10:
        raise RuntimeError("Updated offline transcription failed")
    gui = subprocess.Popen([str(executable)], cwd=target, env=offline_environment())
    time.sleep(8)
    gui_started = gui.poll() is None
    if gui_started:
        subprocess.run(["taskkill", "/PID", str(gui.pid), "/T", "/F"], capture_output=True, timeout=30)
        gui.wait(timeout=15)
    if not gui_started:
        raise RuntimeError("Updated GUI exited during startup")

    report = {
        "verified_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "from_version": "1.4.0", "to_version": "1.5.0",
        "incremental_top_level_items": ["TingTao.exe", "TingTaoUpdate"],
        "embedded_updater_test": True, "standalone_updater_removed": True,
        "wrong_version_rejected_before_writes": True, "update_success": True,
        "backup_created": True, "configuration_preserved": True,
        "transcription_record_preserved": True, "audio_library_preserved": True,
        "small_model_sha256_preserved": True, "small_model_sha256": small_before,
        "updated_integrity_manifest_powershell_test": True,
        "updated_offline_small_transcription_test": True, "updated_gui_startup_test": True,
        "updated_files": update_report["updated_files"], "deleted_files": update_report["deleted_files"],
        "notes": "Actual 1.4.0-to-1.5.0 payload applied to a copied deployment by the 1.5.0 embedded engine. Later updates use the installed application's own one-click workflow.",
    }
    (DIST / "UPDATE_VERIFICATION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
