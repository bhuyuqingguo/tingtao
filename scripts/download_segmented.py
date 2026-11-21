from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import subprocess
import time
from pathlib import Path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_part(url: str, directory: Path, index: int, start: int, end: int) -> Path:
    expected_size = end - start + 1
    target = directory / f"part-{index:04d}"
    temporary = directory / f"part-{index:04d}.tmp"
    if target.is_file() and target.stat().st_size == expected_size:
        print(f"Part {index + 1} already complete", flush=True)
        return target
    if target.exists():
        target.unlink()
    if temporary.is_file() and temporary.stat().st_size > expected_size:
        temporary.unlink()
    for attempt in range(30):
        downloaded = temporary.stat().st_size if temporary.is_file() else 0
        if downloaded == expected_size:
            os.replace(temporary, target)
            print(f"Part {index + 1} complete ({expected_size / 1024 / 1024:.1f} MiB)", flush=True)
            return target
        tail = directory / f"part-{index:04d}.tail"
        tail.unlink(missing_ok=True)
        command = [
            "curl", "--ssl-no-revoke", "--silent", "--show-error", "--location", "--fail",
            "--connect-timeout", "30", "--speed-limit", "1024", "--speed-time", "120",
            "--range", f"{start + downloaded}-{end}", "--output", str(tail), url,
        ]
        completed = subprocess.run(command, check=False)
        if tail.is_file() and tail.stat().st_size > 0:
            with temporary.open("ab") as output, tail.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(block)
        tail.unlink(missing_ok=True)
        current = temporary.stat().st_size if temporary.is_file() else 0
        if current == expected_size:
            os.replace(temporary, target)
            print(f"Part {index + 1} complete ({expected_size / 1024 / 1024:.1f} MiB)", flush=True)
            return target
        if current > expected_size:
            raise RuntimeError(f"Part {index + 1} exceeded expected size")
        print(
            f"Part {index + 1}: {current / 1024 / 1024:.1f}/{expected_size / 1024 / 1024:.1f} MiB; "
            f"resume attempt {attempt + 2} (curl {completed.returncode})",
            flush=True,
        )
        time.sleep(2)
    raise RuntimeError(f"Part {index + 1} did not complete after repeated resumes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("size", type=int)
    parser.add_argument("sha256")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--parts", type=int, default=16)
    args = parser.parse_args()
    directory = args.output.parent / f"download-parts-{args.parts}"
    directory.mkdir(parents=True, exist_ok=True)
    if args.output.is_file() and args.output.stat().st_size == args.size and file_hash(args.output) == args.sha256:
        print("Download already complete and verified.")
        return
    args.output.unlink(missing_ok=True)
    boundaries = []
    for index in range(args.parts):
        start = args.size * index // args.parts
        end = args.size * (index + 1) // args.parts - 1
        boundaries.append((index, start, end))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(download_part, args.url, directory, *item) for item in boundaries]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    assembled = args.output.with_suffix(args.output.suffix + ".assembling")
    with assembled.open("wb") as output:
        for index, _start, _end in boundaries:
            part = directory / f"part-{index:04d}"
            with part.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(block)
    if assembled.stat().st_size != args.size:
        raise RuntimeError("Assembled file size mismatch")
    actual_hash = file_hash(assembled)
    if actual_hash != args.sha256:
        raise RuntimeError(f"SHA-256 mismatch: {actual_hash} != {args.sha256}")
    os.replace(assembled, args.output)
    for path in directory.glob("part-*"):
        path.unlink()
    directory.rmdir()
    print(f"Download verified: {args.output} ({args.size} bytes, SHA-256 {actual_hash})")


if __name__ == "__main__":
    main()
