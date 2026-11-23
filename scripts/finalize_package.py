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
INCREMENTAL = ROOT / "dist" / "TingTao-1.6.4-to-1.6.5-Windows-x64-Incremental.zip"
RELEASE_MANIFEST = ROOT / "dist" / "TingTao-1.6.5-release-manifest.json"


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
    for name in ("VERIFICATION.json", "SELF_UPDATE_VERIFICATION.json"):
        if not (DIST / name).is_file():
            raise RuntimeError(f"{name} is missing; run package and real self-update verification first")
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

    if not INCREMENTAL.is_file():
        raise RuntimeError("Tested 1.6.4-to-1.6.5 incremental package is missing")
    incremental_top = archive_top_level(INCREMENTAL)
    if incremental_top != {"TingTao.exe", "TingTaoUpdate"}:
        raise RuntimeError(f"Incremental package top-level rule failed: {incremental_top}")
    incremental_info = {
        "path": str(INCREMENTAL), "bytes": INCREMENTAL.stat().st_size,
        "sha256": write_hash_file(INCREMENTAL), "zip_crc_test": True,
        "top_level_items": sorted(incremental_top),
    }
    verification = json.loads((DIST / "VERIFICATION.json").read_text(encoding="utf-8"))
    release = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "product": "TingTao",
        "product_name_zh": "观海·听涛",
        "version": "1.6.5",
        "full_package": None,
        "incremental_package": incremental_info,
        "incremental_status": "Only the tested 1.6.4-to-1.6.5 incremental package is published. It passed copied-runtime self-update, restart and data preservation tests.",
        "real_copied_runtime_self_update_test": True,
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
        "kylin_status": "No Kylin binary generated or tested in this Windows incremental release",
        "final_integrity_powershell_test": True,
    }
    RELEASE_MANIFEST.write_text(json.dumps(release, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(release, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
