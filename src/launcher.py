from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    target = root / "TingTao" / "TingTao.exe" if os.name == "nt" else root / "TingTaoData" / "TingTao"
    if not target.is_file():
        message = f"观海·听涛资源目录不完整，找不到：{target}"
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "观海·听涛无法启动", 0x10)
        else:
            print(message, file=sys.stderr)
        return 1
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    arguments = [str(target), *sys.argv[1:]]
    if os.name == "nt":
        return subprocess.run(arguments, cwd=target.parent, check=False).returncode
    os.execv(str(target), arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
