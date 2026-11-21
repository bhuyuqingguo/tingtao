from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from verify_package import assert_exports, load_success, offline_environment, run_metered


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "dist" / "Windows-x64-1.3.0" / "TingTao"
DIST_ROOT = ROOT / "dist" / "Windows-x64"
DIST = DIST_ROOT / "TingTao"
ARCHIVE = ROOT / "dist" / "TingTao-1.3.0-to-1.4.0-Windows-x64-Incremental.zip"
ACCEPTANCE = ROOT / "build-cache" / "update-acceptance-1.4.0"
AUDIO = ROOT / "assets" / "test-zh.wav"
VOICEPRINT_PREFIX = "payload/models/wespeaker-cnceleb-resnet34-lm/"


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
        names = archive.namelist()
        top_level = {Path(name).parts[0] for name in names if Path(name).parts}
        if top_level != {"TingTaoUpdater.exe", "TingTaoUpdate"}:
            raise RuntimeError(f"Incremental ZIP does not have exactly two top-level items: {top_level}")
        if archive.testzip():
            raise RuntimeError("Incremental package CRC validation failed")
        archive.extractall(incremental)
    package = incremental / "TingTaoUpdate" / "TingTao-1.3.0-to-1.4.0.ttupdate"
    updater = incremental / "TingTaoUpdater.exe"
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        for name in names:
            if name.startswith("payload/data/") or name == "payload/config.json":
                raise RuntimeError("Incremental package contains protected user data")
            if name.startswith("payload/models/") and not name.lower().startswith(VOICEPRINT_PREFIX):
                raise RuntimeError(f"Incremental package modifies a protected model: {name}")
        if not any(name.lower() == VOICEPRINT_PREFIX + "cnceleb_resnet34_lm.onnx" for name in names):
            raise RuntimeError("Incremental package does not install the voiceprint model")
        if archive.testzip():
            raise RuntimeError("Update container CRC validation failed")

    target = ACCEPTANCE / "TingTao"
    shutil.copytree(OLD, target)
    config_path = target / "config.json"
    config_path.write_text(json.dumps({
        "language": "zh", "beam_size": 3, "vad_filter": False,
        "output_directory": "", "acceptance_marker": "preserve-me",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    config_before = config_path.read_bytes()
    small_path = target / "models" / "faster-whisper-small" / "model.bin"
    small_before = sha256(small_path)
    expected_medium = sha256(DIST / "models" / "faster-whisper-medium" / "model.bin")
    library = target / "data" / "voiceprints.json"
    library.write_text('{"version": 1, "voices": {"验收说话人": [[1.0, 0.0]]}}', encoding="utf-8")
    library_before = library.read_bytes()
    record = target / "data" / "output" / "acceptance-record.txt"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("升级前保留的转录记录", encoding="utf-8")
    executable = target / "TingTao.exe"
    old_updater = target / "TingTaoUpdater.exe"
    old_exe_hash = sha256(executable)
    old_updater_hash = sha256(old_updater)

    def run_updater() -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(updater), "--headless", "--package", str(package), "--target", str(target)],
            cwd=incremental,
            env=offline_environment(),
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )

    build_info_path = target / "build-info.json"
    original_build_info = build_info_path.read_bytes()
    build_info_path.write_text(json.dumps({"application": "TingTao", "version": "9.9.9"}), encoding="utf-8")
    rejected = run_updater()
    if rejected.returncode == 0:
        raise RuntimeError("Wrong-version update was unexpectedly accepted")
    if (target / "data" / "update-backups").exists():
        raise RuntimeError("Wrong-version update created a backup before validation")
    if sha256(executable) != old_exe_hash or config_path.read_bytes() != config_before:
        raise RuntimeError("Wrong-version update modified the target")
    build_info_path.write_bytes(original_build_info)

    completed = run_updater()
    report_path = target / "data" / "logs" / "last-update.json"
    if completed.returncode != 0 or not report_path.is_file():
        raise RuntimeError(f"Packaged updater failed: exit={completed.returncode}; stdout={completed.stdout}; stderr={completed.stderr}")
    update_report = json.loads(report_path.read_text(encoding="utf-8"))
    if not update_report.get("success"):
        raise RuntimeError(f"Packaged updater did not report success: {update_report}")
    build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
    if build_info.get("version") != "1.4.0" or build_info.get("application") != "TingTao":
        raise RuntimeError(f"Updated build information is incorrect: {build_info}")
    if not executable.is_file() or sha256(executable) == old_exe_hash or not old_updater.is_file():
        raise RuntimeError("TingTao application update failed")
    if config_path.read_bytes() != config_before:
        raise RuntimeError("User configuration changed during update")
    if sha256(small_path) != small_before:
        raise RuntimeError("The existing small model changed during update")
    medium_path = target / "models" / "faster-whisper-medium" / "model.bin"
    if not medium_path.is_file() or sha256(medium_path) != expected_medium:
        raise RuntimeError("The medium model was not installed with the expected hash")
    if record.read_text(encoding="utf-8") != "升级前保留的转录记录":
        raise RuntimeError("A user transcription record changed during update")
    if library.read_bytes() != library_before:
        raise RuntimeError("The persistent voiceprint library changed during update")
    voiceprint_model = target / "models" / "wespeaker-cnceleb-resnet34-LM" / "cnceleb_resnet34_LM.onnx"
    if not voiceprint_model.is_file() or voiceprint_model.stat().st_size != 26530309:
        raise RuntimeError("The voiceprint model was not installed correctly")
    backup = Path(update_report["backup"])
    if not (backup / "TingTao.exe").is_file() or sha256(backup / "TingTao.exe") != old_exe_hash:
        raise RuntimeError("The replaced old executable was not backed up")
    if not (backup / "TingTaoUpdater.exe").is_file() or sha256(backup / "TingTaoUpdater.exe") != old_updater_hash:
        raise RuntimeError("The old updater was not backed up")

    powershell = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target / "verify_package.ps1")],
        cwd=target,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if powershell.returncode != 0 or "OK:" not in powershell.stdout:
        raise RuntimeError(f"Updated integrity manifest failed: {powershell.stdout}\n{powershell.stderr}")

    audio2 = ACCEPTANCE / "test-zh-2.wav"
    shutil.copy2(AUDIO, audio2)
    queue_path = ACCEPTANCE / "updated-queue.json"
    code, queue_seconds, queue_memory = run_metered(
        [str(executable), "--batch-test", str(AUDIO), str(audio2), "--model", "small", "--output", str(queue_path)], ACCEPTANCE
    )
    queue = load_success(queue_path, code)
    if queue.get("succeeded_count") != 2 or queue.get("failed_count") != 0 or len(queue.get("individual_exports", [])) != 8:
        raise RuntimeError(f"Updated small queue transcription failed: {queue}")
    assert_exports(ACCEPTANCE / "batch-queue-file-1", "file-1")
    assert_exports(ACCEPTANCE / "batch-queue-file-2", "file-2")
    assert_exports(ACCEPTANCE / "batch-queue-exports", "merged")

    merged_path = ACCEPTANCE / "updated-merged.json"
    code, merged_seconds, merged_memory = run_metered(
        [str(executable), "--batch-test", str(AUDIO), str(audio2), "--merge", "--model", "small", "--output", str(merged_path)], ACCEPTANCE
    )
    merged = load_success(merged_path, code)
    if merged.get("succeeded_count") != 2 or merged["summary"].get("batch_mode") != "merged":
        raise RuntimeError(f"Updated merged transcription failed: {merged}")
    if not math.isclose(merged["summary"]["duration"], queue["summary"]["duration"], abs_tol=0.01):
        raise RuntimeError("Updated merged timeline is not continuous")
    assert_exports(ACCEPTANCE / "batch-merged-exports", "merged")

    medium_result_path = ACCEPTANCE / "medium" / "self-test-result.json"
    medium_result_path.parent.mkdir()
    code, medium_seconds, medium_memory = run_metered(
        [str(executable), "--self-test", str(AUDIO), "--model", "medium", "--output", str(medium_result_path)], ACCEPTANCE
    )
    medium = load_success(medium_result_path, code)
    if "medium" not in medium.get("model", "") or len(medium.get("text", "").strip()) < 10:
        raise RuntimeError(f"Updated medium transcription failed: {medium}")
    assert_exports(medium_result_path.parent / "self-test-exports", "self-test")

    gui = subprocess.Popen([str(executable)], cwd=target, env=offline_environment())
    time.sleep(8)
    gui_started = gui.poll() is None
    if gui_started:
        subprocess.run(["taskkill", "/PID", str(gui.pid), "/T", "/F"], capture_output=True, timeout=30)
        try:
            gui.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gui.kill()
            gui.wait(timeout=5)
    if not gui_started:
        raise RuntimeError(f"Updated GUI exited during startup with code {gui.returncode}")

    report = {
        "verified_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "from_version": "1.3.0",
        "to_version": "1.4.0",
        "incremental_top_level_items": ["TingTaoUpdater.exe", "TingTaoUpdate"],
        "packaged_standalone_updater_test": True,
        "wrong_version_rejected_before_writes": True,
        "update_success": True,
        "backup_created": True,
        "configuration_preserved": True,
        "transcription_record_preserved": True,
        "small_model_sha256_preserved": True,
        "small_model_sha256": small_before,
        "medium_model_installed": True,
        "medium_model_sha256": expected_medium,
        "models_in_incremental_package": ["medium"],
        "updated_integrity_manifest_powershell_test": True,
        "updated_offline_queue_test": True,
        "updated_offline_merged_timeline_test": True,
        "updated_medium_model_test": True,
        "updated_txt_srt_vtt_json_export_test": True,
        "updated_gui_startup_test": True,
        "queue_seconds": round(queue_seconds, 2),
        "merged_seconds": round(merged_seconds, 2),
        "medium_seconds": round(medium_seconds, 2),
        "queue_memory": queue_memory,
        "merged_memory": merged_memory,
        "medium_memory": medium_memory,
        "updated_files": update_report["updated_files"],
        "deleted_files": update_report["deleted_files"],
        "notes": "Tested against a copied local TingTao 1.3.0 deployment using the actual incremental ZIP. Existing small, config and records were preserved; medium was added. No clean physical machine claim.",
    }
    (DIST / "UPDATE_VERIFICATION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    shutil.rmtree(ACCEPTANCE)


if __name__ == "__main__":
    main()
