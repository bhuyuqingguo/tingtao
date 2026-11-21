from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "Windows-x64"
DIST = DIST_ROOT / "TingTao"
LAUNCHER = DIST_ROOT / "TingTao.exe"
ARCHIVE = ROOT / "dist" / "TingTao-1.4.0-Windows-x64-Offline.zip"
UPDATE_ARCHIVE = ROOT / "dist" / "TingTao-1.3.0-to-1.4.0-Windows-x64-Incremental.zip"
RELEASE_MANIFEST = ROOT / "dist" / "TingTao-1.4.0-release-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def excluded_data(path: Path) -> bool:
    relative = path.relative_to(DIST)
    return bool(relative.parts and relative.parts[0] == "data")


def write_hash_file(path: Path) -> str:
    archive_hash = sha256(path)
    path.with_name(path.name + ".sha256.txt").write_text(f"{archive_hash} *{path.name}\n", encoding="ascii")
    return archive_hash


def archive_top_level(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as package:
        bad = package.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed for {path.name}: {bad}")
        return {Path(name).parts[0] for name in package.namelist() if Path(name).parts}


def main() -> None:
    for name in ("VERIFICATION.json", "UPDATE_VERIFICATION.json"):
        if not (DIST / name).is_file():
            raise RuntimeError(f"{name} is missing; run both package verification passes first")
    if not UPDATE_ARCHIVE.is_file():
        raise RuntimeError("Incremental update ZIP is missing")
    if {path.name for path in DIST_ROOT.iterdir()} != {"TingTao.exe", "TingTao"}:
        raise RuntimeError("Windows build root must contain exactly TingTao.exe and TingTao")

    (DIST / "LAUNCHER_SHA256.txt").write_text(sha256(LAUNCHER), encoding="ascii")
    files = sorted(
        path for path in DIST.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt" and not excluded_data(path)
    )
    manifest = "".join(f"{sha256(path)} *{path.relative_to(DIST).as_posix()}\n" for path in files)
    (DIST / "SHA256SUMS.txt").write_text(manifest, encoding="utf-8")
    powershell = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(DIST / "verify_package.ps1")],
        cwd=DIST,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if powershell.returncode != 0 or "OK:" not in powershell.stdout:
        raise RuntimeError(f"Final package integrity check failed: {powershell.stdout}\n{powershell.stderr}")

    all_files = sorted(path for path in DIST.rglob("*") if path.is_file() and not excluded_data(path))
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
        package.write(LAUNCHER, arcname="TingTao.exe")
        for path in all_files:
            package.write(path, arcname=(Path("TingTao") / path.relative_to(DIST)).as_posix())

    full_top = archive_top_level(ARCHIVE)
    update_top = archive_top_level(UPDATE_ARCHIVE)
    if full_top != {"TingTao.exe", "TingTao"}:
        raise RuntimeError(f"Full package top-level rule failed: {full_top}")
    if update_top != {"TingTaoUpdater.exe", "TingTaoUpdate"}:
        raise RuntimeError(f"Incremental package top-level rule failed: {update_top}")

    full_info = {
        "path": str(ARCHIVE),
        "bytes": ARCHIVE.stat().st_size,
        "sha256": write_hash_file(ARCHIVE),
        "file_count": len(all_files) + 1,
        "zip_crc_test": True,
        "top_level_items": sorted(full_top),
    }
    update_info = {
        "path": str(UPDATE_ARCHIVE),
        "bytes": UPDATE_ARCHIVE.stat().st_size,
        "sha256": write_hash_file(UPDATE_ARCHIVE),
        "zip_crc_test": True,
        "top_level_items": sorted(update_top),
    }
    verification = json.loads((DIST / "VERIFICATION.json").read_text(encoding="utf-8"))
    release = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "product": "TingTao",
        "product_name_zh": "观海·听涛",
        "version": "1.4.0",
        "full_package": full_info,
        "incremental_package": update_info,
        "embedded_models": [
            {
                "name": f"Systran/faster-whisper-{name}",
                "model_bin_bytes": (DIST / "models" / f"faster-whisper-{name}" / "model.bin").stat().st_size,
                "model_bin_sha256": sha256(DIST / "models" / f"faster-whisper-{name}" / "model.bin"),
                "compute": "CPU int8",
            }
            for name in ("small", "medium")
        ],
        "local_short_audio_benchmark": {
            name: {
                "seconds": verification[name]["seconds"],
                "peak_working_set_mib": verification[name]["memory"]["observed_process_tree_peak_working_set_mib"],
                "scope": "16.758-second local Mandarin sample on this Windows host; not a general performance guarantee",
            }
            for name in ("small", "medium")
        },
        "larger_model_planning_estimates_not_measured": {
            "large-v3": {"model_gb": 3.09, "peak_ram_gb": [6, 10], "relative_cpu_time_vs_small": [4, 8]},
        },
        "kylin_status": "Build scripts only; no Kylin binary generated or tested on this Windows host",
        "final_integrity_powershell_test": True,
    }
    RELEASE_MANIFEST.write_text(json.dumps(release, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(release, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
