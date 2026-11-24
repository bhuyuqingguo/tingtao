"""Dependency-free Python adapter for the Guanhai Bafen local core."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class BafenError(RuntimeError):
    pass


@dataclass(frozen=True)
class BafenResult:
    filename: str
    original_size: int
    output: Path


ProgressCallback = Callable[[int, int, int], None]


class BafenCore:
    def __init__(self, executable: str | Path | None = None):
        configured = executable or os.environ.get("GUANHAI_CORE")
        self.executable = Path(configured) if configured else Path(shutil.which("guanhai-core") or "guanhai-core")

    def execute(
        self,
        operation: str,
        input: str | Path,
        password: str,
        *,
        output: str | Path | None = None,
        new_password: str | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> BafenResult:
        if operation not in {"pack", "unpack", "migrate", "recover"}:
            raise ValueError("不支持的操作")
        if self.executable.parent != Path(".") and not self.executable.is_file():
            raise BafenError(f"未找到观海·八分核心程序：{self.executable}")
        request = {
            "operation": operation,
            "input": str(Path(input).resolve()),
            "password": password,
            "newPassword": new_password,
            "output": str(Path(output).resolve()) if output else None,
        }
        with tempfile.TemporaryDirectory(prefix="guanhai-bafen-") as temporary:
            cancel_path = Path(temporary) / "cancel.requested"
            command = [str(self.executable), "request", "--cancel-file", str(cancel_path)]
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                )
            except OSError as exc:
                raise BafenError(f"无法启动观海·八分核心程序：{exc}") from exc
            done = threading.Event()

            def watch_cancellation() -> None:
                while not done.wait(0.05):
                    if cancel_event and cancel_event.is_set():
                        cancel_path.touch()
                        return

            watcher = threading.Thread(target=watch_cancellation, daemon=True)
            watcher.start()
            result = None
            error_message = None
            try:
                assert process.stdin and process.stdout
                try:
                    process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise BafenError("核心程序返回了无法识别的信息") from exc
                    event_type = event.get("type")
                    if event_type == "started" and on_progress:
                        on_progress(0, int(event.get("total", 0)), 0)
                    elif event_type == "progress" and on_progress:
                        on_progress(int(event["processed"]), int(event["total"]), int(event["percent"]))
                    elif event_type == "result":
                        result = event
                    elif event_type == "error":
                        error_message = str(event.get("message", "操作未完成"))
                stderr = process.stderr.read() if process.stderr else ""
                return_code = process.wait()
            finally:
                done.set()
                watcher.join(timeout=0.2)
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
            if error_message:
                raise BafenError(error_message)
            if return_code != 0:
                raise BafenError(stderr.strip() or "操作未完成")
            if not result:
                raise BafenError("核心程序未返回处理结果")
            return BafenResult(
                filename=str(result["filename"]),
                original_size=int(result["originalSize"]),
                output=Path(str(result["output"])),
            )

    def pack(self, input: str | Path, password: str, output: str | Path | None = None, **kwargs) -> BafenResult:
        return self.execute("pack", input, password, output=output, **kwargs)

    def unpack(self, input: str | Path, password: str, output: str | Path | None = None, **kwargs) -> BafenResult:
        return self.execute("unpack", input, password, output=output, **kwargs)

    def migrate(self, input: str | Path, old_password: str, new_password: str, output: str | Path | None = None, **kwargs) -> BafenResult:
        return self.execute("migrate", input, old_password, output=output, new_password=new_password, **kwargs)

    def recover(self, input: str | Path, password: str, output: str | Path | None = None, **kwargs) -> BafenResult:
        return self.execute("recover", input, password, output=output, **kwargs)
