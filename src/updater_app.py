from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from offline_transcriber.update_common import read_update_package, safe_relative_path, sha256, validate_target


def wait_for_parent(pid: int, timeout: float = 60.0) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        import ctypes
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
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


def rebuild_integrity_manifest(target: Path) -> None:
    """Reflect the actual upgraded installation, including preserved user config."""
    files = sorted(
        path for path in target.rglob("*")
        if path.is_file()
        and path.name != "SHA256SUMS.txt"
        and (not path.relative_to(target).parts or path.relative_to(target).parts[0].lower() != "data")
    )
    content = "".join(f"{sha256(path)} *{path.relative_to(target).as_posix()}\n" for path in files)
    temporary = target / "SHA256SUMS.txt.tinglan-new"
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target / "SHA256SUMS.txt")


def apply_update(package: Path, target: Path, log=lambda message: None) -> dict:
    manifest = read_update_package(package)
    target = validate_target(manifest, target)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = target / "data" / "update-backups" / f"{manifest['from_version']}-to-{manifest['to_version']}-{timestamp}"
    backup.mkdir(parents=True, exist_ok=False)
    replaced: list[str] = []
    deleted: list[str] = []
    added: list[str] = []
    log(f"目标目录：{target}")
    log(f"版本：{manifest['from_version']} → {manifest['to_version']}")
    log(f"备份目录：{backup}")
    try:
        allow_medium = manifest.get("package_kind") == "application-with-model"
        allow_voiceprint = manifest.get("package_kind") == "application-with-voiceprint"
        with zipfile.ZipFile(package) as archive:
            for item in manifest["files"]:
                relative = safe_relative_path(
                    item["path"], allow_medium_model=allow_medium, allow_voiceprint_model=allow_voiceprint,
                )
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_file():
                    backup_file = backup / relative
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_file)
                else:
                    added.append(relative)
                temporary = destination.with_name(destination.name + ".tinglan-new")
                with archive.open(f"payload/{relative}") as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                if sha256(temporary) != item["sha256"]:
                    raise RuntimeError(f"写入后哈希校验失败：{relative}")
                os.replace(temporary, destination)
                replaced.append(relative)
                log(f"已更新：{relative}")
            for relative_value in manifest.get("deletes", []):
                relative = safe_relative_path(relative_value)
                destination = target / relative
                if destination.is_file():
                    backup_file = backup / relative
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_file)
                    destination.unlink()
                    deleted.append(relative)
                    log(f"已移除旧文件：{relative}")
        for item in manifest["files"]:
            if sha256(target / item["path"]) != item["sha256"]:
                raise RuntimeError(f"升级后校验失败：{item['path']}")
        integrity_path = target / "SHA256SUMS.txt"
        if integrity_path.is_file():
            backup_file = backup / "SHA256SUMS.txt"
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(integrity_path, backup_file)
        else:
            added.append("SHA256SUMS.txt")
        replaced.append("SHA256SUMS.txt")
        rebuild_integrity_manifest(target)
        log("已根据升级后的实际文件重建完整性清单。")
        report = {
            "success": True,
            "from_version": manifest["from_version"],
            "to_version": manifest["to_version"],
            "updated_files": len(replaced),
            "deleted_files": len(deleted),
            "backup": str(backup),
            "completed_at": datetime.now().astimezone().isoformat(),
        }
        log_directory = target / "data" / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        (log_directory / "last-update.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log("升级完成，全部文件校验通过。原有配置、记录和模型均已保留。")
        return report
    except Exception:
        log("升级失败，正在回滚……")
        for relative in replaced:
            backup_file = backup / relative
            destination = target / relative
            if backup_file.is_file():
                shutil.copy2(backup_file, destination)
            elif relative in added:
                destination.unlink(missing_ok=True)
        for relative in deleted:
            backup_file = backup / relative
            if backup_file.is_file():
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, destination)
        log("已回滚到升级前状态。")
        raise


def main_executable(target: Path) -> Path:
    return target / ("TingTao.exe" if os.name == "nt" else "TingTao")


def run_headless(args) -> int:
    try:
        wait_for_parent(args.parent_pid)
        report = apply_update(args.package, args.target, print)
        print(json.dumps(report, ensure_ascii=False))
        if args.restart:
            subprocess.Popen([str(main_executable(args.target))], cwd=args.target)
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        traceback.print_exc()
        return 1


def run_gui(args) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("观海·听涛 · 离线增量升级")
    root.geometry("620x500")
    root.minsize(560, 440)
    root.configure(bg="#F3F7F6")
    events = queue.Queue()
    package_var = tk.StringVar(value=str(args.package or ""))
    target_var = tk.StringVar(value=str(args.target or ""))
    status_var = tk.StringVar(value="请选择本地升级包和目标部署目录")

    outer = tk.Frame(root, bg="#F3F7F6", padx=28, pady=24)
    outer.pack(fill="both", expand=True)
    tk.Label(outer, text="观海·听涛", font=("Microsoft YaHei UI", 24, "bold"), fg="#173B4B", bg="#F3F7F6").pack(anchor="w")
    tk.Label(outer, text="离线增量升级 · 校验、备份、失败回滚", font=("Microsoft YaHei UI", 10), fg="#5F7378", bg="#F3F7F6").pack(anchor="w", pady=(2, 22))

    form = tk.Frame(outer, bg="#F3F7F6")
    form.pack(fill="x")
    tk.Label(form, text="升级包", font=("Microsoft YaHei UI", 10), fg="#28464F", bg="#F3F7F6").grid(row=0, column=0, sticky="w", pady=6)
    tk.Entry(form, textvariable=package_var, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="ew", ipady=6)
    tk.Label(form, text="部署目录", font=("Microsoft YaHei UI", 10), fg="#28464F", bg="#F3F7F6").grid(row=2, column=0, sticky="w", pady=(14, 6))
    tk.Entry(form, textvariable=target_var, font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, sticky="ew", ipady=6)
    form.columnconfigure(0, weight=1)

    buttons = tk.Frame(outer, bg="#F3F7F6")
    buttons.pack(fill="x", pady=12)
    progress = ttk.Progressbar(outer, mode="indeterminate")
    log_text = tk.Text(outer, height=12, font=("Consolas", 9), bg="#FFFFFF", fg="#28464F", relief="flat", padx=12, pady=10)
    status = tk.Label(outer, textvariable=status_var, font=("Microsoft YaHei UI", 9), fg="#5F7378", bg="#F3F7F6")

    def append(message):
        log_text.insert("end", message + "\n")
        log_text.see("end")

    def choose_package():
        value = filedialog.askopenfilename(title="选择观海·听涛离线升级包", filetypes=[("观海·听涛升级包", "*.ttupdate *.tlupdate"), ("所有文件", "*")])
        if value:
            package_var.set(value)

    def choose_target():
        value = filedialog.askdirectory(title="选择当前观海·听涛／析声部署目录")
        if value:
            target_var.set(value)

    tk.Button(buttons, text="选择升级包", command=choose_package, padx=12, pady=6).pack(side="left")
    tk.Button(buttons, text="选择部署目录", command=choose_target, padx=12, pady=6).pack(side="left", padx=8)

    def worker():
        try:
            wait_for_parent(args.parent_pid)
            report = apply_update(Path(package_var.get()), Path(target_var.get()), lambda msg: events.put(("log", msg)))
            events.put(("done", report))
        except Exception as exc:
            events.put(("error", str(exc)))

    def start():
        if not package_var.get() or not target_var.get():
            messagebox.showwarning("信息不完整", "请先选择升级包和部署目录。", parent=root)
            return
        start_button.configure(state="disabled")
        progress.pack(fill="x", pady=(2, 12))
        progress.start(12)
        status_var.set("正在校验并升级，请勿关闭目标目录……")
        threading.Thread(target=worker, daemon=True).start()

    start_button = tk.Button(buttons, text="开始升级", command=start, padx=18, pady=7, bg="#247B83", fg="white", relief="flat")
    start_button.pack(side="right")
    status.pack(anchor="w", pady=(4, 6))
    log_text.pack(fill="both", expand=True)

    def poll():
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "log":
                    append(payload)
                elif kind == "done":
                    progress.stop()
                    progress.pack_forget()
                    status_var.set(f"升级完成：{payload['from_version']} → {payload['to_version']}")
                    append("可以关闭此窗口。")
                    messagebox.showinfo("升级完成", "观海·听涛已完成增量升级，原有记录、配置和模型均已保留。", parent=root)
                    if args.restart:
                        subprocess.Popen([str(main_executable(Path(target_var.get())))], cwd=target_var.get())
                        root.after(800, root.destroy)
                elif kind == "error":
                    progress.stop()
                    progress.pack_forget()
                    start_button.configure(state="normal")
                    status_var.set("升级未完成")
                    append("错误：" + payload)
                    messagebox.showerror("升级失败", payload, parent=root)
        except queue.Empty:
            pass
        root.after(150, poll)

    root.after(150, poll)
    if args.package and args.target:
        root.after(350, start)
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="观海·听涛离线增量升级器")
    parser.add_argument("--package", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if args.headless:
        if not args.package or not args.target:
            parser.error("--headless requires --package and --target")
        return run_headless(args)
    return run_gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
