from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _self_test(audio: str, output: str | None, model_name: str, speaker: bool = False) -> int:
    from .paths import DATA_ROOT, ensure_data_directories
    from .transcriber import OfflineTranscriber

    ensure_data_directories()
    destination = Path(output) if output else DATA_ROOT / "self-test-result.json"
    try:
        from .formatters import export_all
        result = OfflineTranscriber(model_name=model_name, speaker_enabled=speaker).transcribe(audio, language="zh")
        exports = export_all(result, destination.parent / "self-test-exports", "self-test")
        payload = {"success": True, "exports": [path.name for path in exports], **result.to_dict()}
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        payload = {"success": False, "error": str(exc), "error_type": type(exc).__name__}
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1


def _batch_test(audios: list[str], output: str | None, mode: str, model_name: str) -> int:
    from .batch import transcribe_batch
    from .formatters import export_all
    from .paths import DATA_ROOT, ensure_data_directories
    from .transcriber import OfflineTranscriber

    ensure_data_directories()
    destination = Path(output) if output else DATA_ROOT / f"batch-{mode}-result.json"
    try:
        transcriber = OfflineTranscriber(model_name=model_name)
        summary = transcribe_batch(transcriber, audios, mode=mode, language="zh")
        export_dir = destination.parent / f"batch-{mode}-exports"
        exports = export_all(summary.merged_result, export_dir, "merged")
        individual = []
        if mode == "queue":
            for index, result in enumerate(summary.results, start=1):
                folder = destination.parent / f"batch-queue-file-{index}"
                individual.extend(str(path) for path in export_all(result, folder, f"file-{index}"))
        payload = {
            "success": True,
            "mode": mode,
            "model_name": model_name,
            "succeeded_count": summary.succeeded_count,
            "failed_count": summary.failed_count,
            "exports": [path.name for path in exports],
            "individual_exports": individual,
            "summary": summary.merged_result.to_dict(),
        }
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if not summary.failures else 2
    except Exception as exc:
        payload = {"success": False, "error": str(exc), "error_type": type(exc).__name__}
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1


def main() -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"

    parser = argparse.ArgumentParser(description="观海·听涛 · 完全离线语音转录")
    parser.add_argument("--self-test", metavar="AUDIO", help="不启动界面，转录指定文件并写入测试结果")
    parser.add_argument("--batch-test", nargs="+", metavar="AUDIO", help="按队列或合并模式转录多个文件")
    parser.add_argument("--merge", action="store_true", help="配合 --batch-test，合并为连续时间轴的一份文稿")
    parser.add_argument("--model", choices=("small", "medium"), default="small", help="选择本地识别模型，默认 small")
    parser.add_argument("--speaker", action="store_true", help="启用离线说话人分离与声纹库匹配")
    parser.add_argument("--output", help="测试结果 JSON 路径")
    parser.add_argument("--version", action="store_true")
    args, _unknown = parser.parse_known_args()
    if args.version:
        from . import __version__
        print(__version__)
        return 0
    if args.batch_test:
        return _batch_test(args.batch_test, args.output, "merged" if args.merge else "queue", args.model)
    if args.self_test:
        return _self_test(args.self_test, args.output, args.model, args.speaker)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from . import __version__
    from .main_window import MainWindow, LOGO_PATH

    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"TingTao.{__version__}")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("观海·听涛 · 本地语音转录")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("GuanHaiTingTao")
    if LOGO_PATH.is_file():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
