from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import math
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "Windows-x64"
DIST = DIST_ROOT / "TingTao"
LAUNCHER = DIST_ROOT / "TingTao.exe"
ACCEPTANCE = ROOT / "build-cache" / "acceptance-1.6.1"
AUDIO = ROOT / "assets" / "test-zh.wav"

if os.name == "nt":
    _kernel32 = ctypes.windll.kernel32
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]


def offline_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
    })
    return environment


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class MemoryMonitor:
    """Observe PeakWorkingSetSize across the launcher and its descendant processes."""

    def __init__(self, root_pid: int):
        self.root_pid = root_pid
        self.stop_event = threading.Event()
        self.tracked: set[int] = {root_pid}
        self.names: dict[int, str] = {}
        self.peak_by_pid: dict[int, int] = {}
        self.thread = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def _snapshot() -> list[PROCESSENTRY32W]:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        invalid = ctypes.c_void_p(-1).value
        if handle == invalid:
            return []
        entries: list[PROCESSENTRY32W] = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            if kernel32.Process32FirstW(handle, ctypes.byref(entry)):
                entries.append(entry)
                while True:
                    entry = PROCESSENTRY32W()
                    entry.dwSize = ctypes.sizeof(entry)
                    if not kernel32.Process32NextW(handle, ctypes.byref(entry)):
                        break
                    entries.append(entry)
        finally:
            kernel32.CloseHandle(handle)
        return entries

    @staticmethod
    def _peak(pid: int) -> int | None:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if not ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return None
            return int(counters.PeakWorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            entries = self._snapshot()
            changed = True
            while changed:
                changed = False
                for entry in entries:
                    pid = int(entry.th32ProcessID)
                    if int(entry.th32ParentProcessID) in self.tracked and pid not in self.tracked:
                        self.tracked.add(pid)
                        changed = True
            for entry in entries:
                pid = int(entry.th32ProcessID)
                if pid in self.tracked:
                    self.names[pid] = entry.szExeFile
            for pid in tuple(self.tracked):
                peak = self._peak(pid)
                if peak is not None:
                    self.peak_by_pid[pid] = max(peak, self.peak_by_pid.get(pid, 0))
            self.stop_event.wait(0.05)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def report(self) -> dict:
        peak = max(self.peak_by_pid.values(), default=0)
        return {
            "observed_process_tree_peak_working_set_bytes": peak,
            "observed_process_tree_peak_working_set_mib": round(peak / 1024 / 1024, 1) if peak else None,
            "observed_processes": [
                {"pid": pid, "name": self.names.get(pid, ""), "peak_working_set_bytes": value}
                for pid, value in sorted(self.peak_by_pid.items())
            ],
            "measurement_scope": "Windows PeakWorkingSetSize, sampled across launcher and descendants; not dedicated-system RAM usage",
        }


def run_metered(command: list[str], cwd: Path) -> tuple[int, float, dict]:
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=offline_environment())
    with MemoryMonitor(process.pid) as monitor:
        try:
            returncode = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            raise
    return returncode, time.monotonic() - started, monitor.report()


def load_success(path: Path, returncode: int) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Packaged test did not create {path.name}; exit={returncode}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if returncode != 0 or not result.get("success"):
        raise RuntimeError(f"Packaged test failed: {result}")
    return result


def assert_exports(directory: Path, stem: str) -> None:
    expected = {f"{stem}.{suffix}" for suffix in ("txt", "srt", "vtt", "json")}
    actual = {path.name for path in directory.glob(f"{stem}.*") if path.stat().st_size > 0}
    if actual != expected:
        raise RuntimeError(f"Export verification failed in {directory}: {actual}")


def main() -> None:
    if not LAUNCHER.is_file() or not (DIST / "TingTao.exe").is_file():
        raise RuntimeError("Build the two-item portable package first")
    if (DIST / "TingTaoUpdater.exe").exists():
        raise RuntimeError("Standalone updater must not be present; updates are embedded in the application")
    for model in ("small", "medium"):
        if not (DIST / "models" / f"faster-whisper-{model}" / "model.bin").is_file():
            raise RuntimeError(f"Embedded {model} model is missing")
    if {path.name for path in DIST_ROOT.iterdir()} != {"TingTao.exe", "TingTao"}:
        raise RuntimeError("Windows build root must contain exactly TingTao.exe and TingTao")
    if not AUDIO.is_file():
        raise RuntimeError("Chinese test audio is missing")
    if ACCEPTANCE.exists():
        shutil.rmtree(ACCEPTANCE)
    ACCEPTANCE.mkdir(parents=True)
    portable = ACCEPTANCE / "portable"
    shutil.copytree(DIST_ROOT, portable)
    relocated_exe = portable / "TingTao.exe"
    audio2 = ACCEPTANCE / "test-zh-2.wav"
    shutil.copy2(AUDIO, audio2)

    single_path = ACCEPTANCE / "self-test-result.json"
    code, single_seconds, single_memory = run_metered(
        [str(relocated_exe), "--self-test", str(AUDIO), "--model", "small", "--output", str(single_path)], ACCEPTANCE
    )
    single = load_success(single_path, code)
    text = single.get("text", "")
    if len(text.strip()) < 10 or not single.get("segments") or "small" not in single.get("model", ""):
        raise RuntimeError(f"Small recognition result is invalid: {text!r}")
    assert_exports(ACCEPTANCE / "self-test-exports", "self-test")

    medium_path = ACCEPTANCE / "medium" / "self-test-result.json"
    medium_path.parent.mkdir()
    code, medium_seconds, medium_memory = run_metered(
        [str(relocated_exe), "--self-test", str(AUDIO), "--model", "medium", "--output", str(medium_path)], ACCEPTANCE
    )
    medium = load_success(medium_path, code)
    medium_text = medium.get("text", "")
    if len(medium_text.strip()) < 10 or not medium.get("segments") or "medium" not in medium.get("model", ""):
        raise RuntimeError(f"Medium recognition result is invalid: {medium_text!r}")
    assert_exports(medium_path.parent / "self-test-exports", "self-test")

    queue_path = ACCEPTANCE / "batch-queue-result.json"
    code, queue_seconds, queue_memory = run_metered(
        [str(relocated_exe), "--batch-test", str(AUDIO), str(audio2), "--output", str(queue_path)], ACCEPTANCE
    )
    queue = load_success(queue_path, code)
    if queue.get("mode") != "queue" or queue.get("succeeded_count") != 2 or queue.get("failed_count") != 0:
        raise RuntimeError(f"Two-file queue result is incorrect: {queue}")
    if len(queue.get("individual_exports", [])) != 8:
        raise RuntimeError("Queue mode did not export four formats for each source")
    assert_exports(ACCEPTANCE / "batch-queue-exports", "merged")
    assert_exports(ACCEPTANCE / "batch-queue-file-1", "file-1")
    assert_exports(ACCEPTANCE / "batch-queue-file-2", "file-2")
    for exported in queue["individual_exports"]:
        if not Path(exported).is_file() or Path(exported).stat().st_size == 0:
            raise RuntimeError(f"Queue export is missing or empty: {exported}")
    queue_summary = queue["summary"]
    if len(queue_summary.get("sources", [])) != 2 or queue_summary.get("batch_mode") != "queue":
        raise RuntimeError("Queue source metadata is missing")
    if {segment.get("source_index") for segment in queue_summary["segments"]} != {0, 1}:
        raise RuntimeError("Queue segments do not preserve both source indices")

    merged_path = ACCEPTANCE / "batch-merged-result.json"
    code, merged_seconds, merged_memory = run_metered(
        [str(relocated_exe), "--batch-test", str(AUDIO), str(audio2), "--merge", "--output", str(merged_path)], ACCEPTANCE
    )
    merged = load_success(merged_path, code)
    if merged.get("mode") != "merged" or merged.get("succeeded_count") != 2 or merged.get("failed_count") != 0:
        raise RuntimeError(f"Two-file merged result is incorrect: {merged}")
    assert_exports(ACCEPTANCE / "batch-merged-exports", "merged")
    merged_summary = merged["summary"]
    if merged_summary.get("batch_mode") != "merged" or len(merged_summary.get("sources", [])) != 2:
        raise RuntimeError("Merged source metadata is missing")
    if not math.isclose(merged_summary["duration"], queue_summary["duration"], abs_tol=0.01):
        raise RuntimeError("Merged timeline duration does not equal the sum of source durations")
    second_starts = [s["start"] for s in merged_summary["segments"] if s.get("source_index") == 1]
    if not second_starts or not math.isclose(min(second_starts), single["duration"], abs_tol=0.01):
        raise RuntimeError("Second source does not begin at the expected continuous timeline offset")
    merged_txt = (ACCEPTANCE / "batch-merged-exports" / "merged.txt").read_text(encoding="utf-8-sig")
    if "【test-zh.wav】" not in merged_txt or "【test-zh-2.wav】" not in merged_txt:
        raise RuntimeError("Merged TXT does not label both source files")

    gui = subprocess.Popen([str(relocated_exe)], cwd=portable, env=offline_environment())
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
        raise RuntimeError(f"Packaged GUI exited during startup with code {gui.returncode}")

    report = {
        "verified_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "application": "TingTao",
        "product_name_zh": "观海·听涛",
        "version": json.loads((DIST / "build-info.json").read_text(encoding="utf-8"))["version"],
        "top_level_items": ["TingTao.exe", "TingTao"],
        "outer_launcher_test": True,
        "standalone_updater_present": False,
        "embedded_updater_present": True,
        "relocated_copy_test": True,
        "gui_startup_test": True,
        "offline_inference_test": True,
        "small_model_cli_selection_test": True,
        "medium_model_cli_selection_test": True,
        "embedded_models": ["small", "medium"],
        "single_txt_srt_vtt_json_export_test": True,
        "two_file_queue_test": True,
        "queue_individual_exports": 8,
        "two_file_merged_timeline_test": True,
        "source_labels_test": True,
        "network_controls": "HF offline mode enabled; HTTP/HTTPS/ALL proxy forced to unroutable localhost port",
        "test_audio": "Two copies of locally synthesized Mandarin Chinese speech",
        "recognized_text_small": text,
        "recognized_text_medium": medium_text,
        "keyword_hits": {word: (word in text) for word in ("语音", "转录", "离线", "字幕")},
        "small": {"seconds": round(single_seconds, 2), "duration_seconds": single["duration"], "memory": single_memory},
        "medium": {"seconds": round(medium_seconds, 2), "duration_seconds": medium["duration"], "memory": medium_memory},
        "queue": {"seconds": round(queue_seconds, 2), "duration_seconds": queue_summary["duration"], "memory": queue_memory},
        "merged": {"seconds": round(merged_seconds, 2), "duration_seconds": merged_summary["duration"], "memory": merged_memory},
        "models": [single["model"], medium["model"]],
        "notes": "Tested through the outer launcher in a relocated portable directory. No claim of testing on a separate clean physical machine. Memory figures are local process working-set observations, not larger-model estimates.",
    }
    (DIST / "VERIFICATION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    shutil.rmtree(ACCEPTANCE)


if __name__ == "__main__":
    main()
