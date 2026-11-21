from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from offline_transcriber.config import AppConfig, ConfigStore
from offline_transcriber.model_catalog import MODEL_SPECS, model_directory, normalize_model_name
from offline_transcriber.update_common import read_update_package
from updater_app import apply_update


class ModelTests(unittest.TestCase):
    def test_model_names_and_config_round_trip(self):
        self.assertEqual(normalize_model_name("MEDIUM"), "medium")
        self.assertEqual(model_directory("small").name, MODEL_SPECS["small"].directory_name)
        with self.assertRaises(ValueError):
            normalize_model_name("large-v3")
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.json")
            store.save(AppConfig(model_name="medium"))
            self.assertEqual(store.load().model_name, "medium")
            store.path.write_text(json.dumps({"model_name": "unknown"}), encoding="utf-8")
            self.assertEqual(store.load().model_name, "small")

    def make_package(self, root: Path, path: str, kind: str = "application-with-model", deletes=None) -> Path:
        payload = b"medium-model-data"
        package = root / "model-update.ttupdate"
        manifest = {
            "format": "tinglan-offline-update-v1",
            "package_kind": kind,
            "product": "TingTao",
            "from_version": "1.2.0",
            "to_version": "1.3.0",
            "files": [{
                "path": path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "from_sha256": None,
            }],
            "deletes": deletes or [],
        }
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("update-manifest.json", json.dumps(manifest))
            archive.writestr(f"payload/{path}", payload)
        return package

    def test_medium_model_package_preserves_small(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            small = target / "models" / "faster-whisper-small" / "model.bin"
            small.parent.mkdir(parents=True)
            small.write_bytes(b"original-small")
            (target / "build-info.json").write_text(json.dumps({"application": "TingTao", "version": "1.2.0"}), encoding="utf-8")
            package = self.make_package(root, "models/faster-whisper-medium/model.bin")
            report = apply_update(package, target)
            self.assertTrue(report["success"])
            self.assertEqual(small.read_bytes(), b"original-small")
            self.assertEqual((target / "models" / "faster-whisper-medium" / "model.bin").read_bytes(), b"medium-model-data")

    def test_ordinary_package_cannot_add_medium(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self.make_package(root, "models/faster-whisper-medium/model.bin", kind="application")
            with self.assertRaises(ValueError):
                read_update_package(package)

    def test_model_package_cannot_replace_small_or_delete_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                read_update_package(self.make_package(root, "models/faster-whisper-small/model.bin"))
            with self.assertRaises(ValueError):
                read_update_package(self.make_package(
                    root, "models/faster-whisper-medium/model.bin",
                    deletes=["models/faster-whisper-medium/model.bin"],
                ))


if __name__ == "__main__":
    unittest.main()
