from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from offline_transcriber.update_common import read_update_package, safe_relative_path, validate_target
from updater_app import apply_update, rebuild_integrity_manifest


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UpdateTests(unittest.TestCase):
    def make_target(self, root: Path) -> Path:
        target = root / "target"
        (target / "data" / "output").mkdir(parents=True)
        (target / "models" / "small").mkdir(parents=True)
        (target / "build-info.json").write_text(json.dumps({"application": "LocalTranscriber", "version": "1.0.0"}), encoding="utf-8")
        (target / "program.bin").write_bytes(b"old-program")
        (target / "LocalTranscriber.exe").write_bytes(b"old-executable")
        (target / "config.json").write_text('{"language":"en","custom":true}', encoding="utf-8")
        (target / "models" / "small" / "model.bin").write_bytes(b"model-data")
        (target / "data" / "output" / "record.txt").write_text("保留的记录", encoding="utf-8")
        (target / "SHA256SUMS.txt").write_text("old-manifest\n", encoding="utf-8")
        return target

    def make_package(self, root: Path, path: str = "program.bin", payload: bytes = b"new-program", **overrides) -> Path:
        package = root / "update.tlupdate"
        manifest = {
            "format": "tinglan-offline-update-v1",
            "package_kind": "application",
            "product": "TingLan",
            "from_version": "1.0.0",
            "to_version": "1.1.0",
            "files": [{
                "path": path,
                "size": len(payload),
                "sha256": digest(payload),
                "from_sha256": digest(b"old-program") if path == "program.bin" else None,
            }],
            "deletes": ["LocalTranscriber.exe"],
        }
        manifest.update(overrides)
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("update-manifest.json", json.dumps(manifest, ensure_ascii=False))
            archive.writestr(f"payload/{path}", payload)
        return package

    def test_valid_package_and_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            package = self.make_package(root)
            manifest = read_update_package(package)
            self.assertEqual(validate_target(manifest, target), target.resolve())
            self.assertEqual(manifest["total_payload_bytes"], len(b"new-program"))

    def test_invalid_and_protected_paths(self):
        for path in ("../outside", "/absolute", "C:/outside", "data/output/a.txt", "MODELS/model.bin", "CONFIG.JSON", "a\\b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_relative_path(path)

    def test_protected_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self.make_package(root, path="models/small/model.bin")
            with self.assertRaises(ValueError):
                read_update_package(package)

    def test_wrong_version_changes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            build_info = target / "build-info.json"
            build_info.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
            before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError, "版本不匹配"):
                apply_update(self.make_package(root), target)
            after = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_update_preserves_user_data_and_rebuilds_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            report = apply_update(self.make_package(root), target)
            self.assertTrue(report["success"])
            self.assertEqual((target / "program.bin").read_bytes(), b"new-program")
            self.assertFalse((target / "LocalTranscriber.exe").exists())
            self.assertEqual((target / "config.json").read_text(encoding="utf-8"), '{"language":"en","custom":true}')
            self.assertEqual((target / "models" / "small" / "model.bin").read_bytes(), b"model-data")
            self.assertEqual((target / "data" / "output" / "record.txt").read_text(encoding="utf-8"), "保留的记录")
            manifest = (target / "SHA256SUMS.txt").read_text(encoding="utf-8")
            self.assertIn("config.json", manifest)
            self.assertNotIn("data/output/record.txt", manifest)
            for line in manifest.splitlines():
                expected, relative = line.split(" *", 1)
                self.assertEqual(digest((target / relative).read_bytes()), expected)

    def test_failure_rolls_back_program_and_deletions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
            with patch("updater_app.rebuild_integrity_manifest", side_effect=OSError("simulated write failure")):
                with self.assertRaisesRegex(OSError, "simulated"):
                    apply_update(self.make_package(root), target)
            after = {
                path.relative_to(target): path.read_bytes()
                for path in target.rglob("*") if path.is_file() and "update-backups" not in path.parts
            }
            self.assertEqual(before, after)

    def test_integrity_manifest_excludes_data_and_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_target(Path(directory))
            rebuild_integrity_manifest(target)
            lines = (target / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines)
            self.assertFalse(any("data/" in line or "SHA256SUMS.txt" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
