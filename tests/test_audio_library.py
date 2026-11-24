from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from offline_transcriber.audio_library import AudioLibrary, InvalidVaultPasswordError, VaultLockedError


class AudioLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "原始录音.wav"
        self.source.write_bytes(b"RIFF-test-audio-content")
        self.library = AudioLibrary(self.root / "library")

    def tearDown(self):
        self.temporary.cleanup()

    def test_catalogue_names_keywords_and_export(self):
        item = self.library.add(self.source, "项目讨论会")
        self.library.add_keyword("项目 Alpha")
        self.library.set_keywords(item["id"], ["项目 Alpha", "周会"])
        self.library.rename(item["id"], "周一项目讨论会")
        entries = self.library.items()
        self.assertEqual(entries[0]["name"], "周一项目讨论会")
        self.assertEqual(entries[0]["keywords"], ["项目 Alpha", "周会"])
        self.assertEqual(self.library.materialize(item["id"]).read_bytes(), self.source.read_bytes())
        exported = self.library.export(item["id"], self.root / "exported.wav")
        self.assertEqual(exported.read_bytes(), self.source.read_bytes())
        self.library.delete(item["id"])
        self.assertEqual(self.library.items(), [])

    def test_encryption_protects_audio_metadata_and_keywords(self):
        item = self.library.add(self.source, "保密会议", ["机密关键词"])
        self.library.add_keyword("项目密语")
        self.library.enable_encryption("correct horse battery")
        self.assertTrue(item["id"])
        self.assertFalse(self.library.index_path.exists())
        self.assertTrue(self.library.encrypted_index_path.exists())
        self.assertNotIn("保密会议".encode("utf-8"), self.library.encrypted_index_path.read_bytes())
        encrypted_files = list(self.library.files_root.glob("*.bfq"))
        self.assertEqual(len(encrypted_files), 1)
        self.assertNotEqual(encrypted_files[0].read_bytes(), self.source.read_bytes())
        self.assertFalse(list(self.library.files_root.glob("*.wav")))
        self.assertEqual(self.library.materialize(item["id"]).read_bytes(), self.source.read_bytes())

    def test_lock_wrong_password_reload_and_disable(self):
        item = self.library.add(self.source, "内部访谈")
        self.library.enable_encryption("a secure password")
        self.library.lock()
        self.assertFalse(list(self.library.session_root.glob("*")))
        with self.assertRaises(VaultLockedError):
            self.library.items()
        with self.assertRaises(InvalidVaultPasswordError):
            self.library.unlock("wrong password")
        reopened = AudioLibrary(self.root / "library")
        reopened.unlock("a secure password")
        self.assertEqual(reopened.items()[0]["name"], "内部访谈")
        self.assertEqual(reopened.materialize(item["id"]).read_bytes(), self.source.read_bytes())
        reopened.disable_encryption("a secure password")
        self.assertFalse(reopened.vault_path.exists())
        self.assertTrue(reopened.index_path.exists())
        self.assertEqual(json.loads(reopened.index_path.read_text(encoding="utf-8"))["items"][0]["name"], "内部访谈")
        self.assertFalse(list(reopened.files_root.glob("*.bfq")))

    def test_new_audio_is_encrypted_and_tampering_is_detected(self):
        self.library.enable_encryption("a secure password")
        item = self.library.add(self.source, "新录音")
        stored = self.library.files_root / item["file"]
        stored.write_bytes(b"damaged")
        with self.assertRaises(InvalidVaultPasswordError):
            self.library.materialize(item["id"])

    def test_legacy_aes_vault_is_migrated_only_after_correct_unlock(self):
        import os
        from offline_transcriber.audio_library import _b64

        password = "legacy secure password"
        salt = os.urandom(16)
        key = self.library._derive_legacy(password, salt)
        item = {
            "id": "legacy-item", "name": "旧版保密会议", "original_name": self.source.name,
            "extension": ".wav", "created_at": "before-bafen", "bytes": self.source.stat().st_size,
            "encrypted": True, "file": "legacy-item.ttenc", "keywords": ["历史关键词"],
        }
        (self.library.files_root / item["file"]).write_bytes(self.library._seal_legacy(key, self.source.read_bytes()))
        data = {"version": 1, "keywords": ["历史关键词"], "items": [item]}
        self.library.legacy_index_path.write_bytes(self.library._seal_legacy(key, json.dumps(data, ensure_ascii=False).encode("utf-8")))
        self.library.vault_path.write_text(json.dumps({
            "version": 1, "kdf": "scrypt", "salt": _b64(salt),
            "check": _b64(self.library._seal_legacy(key, b"tingtao-vault-check")),
        }), encoding="utf-8")
        with self.assertRaises(InvalidVaultPasswordError):
            self.library.unlock("wrong password")
        self.assertTrue(self.library.legacy_index_path.exists())
        self.library.unlock(password)
        self.assertEqual(self.library.encryption_format, "guanhai-bafen-bfq")
        self.assertEqual(self.library.items()[0]["name"], "旧版保密会议")
        self.assertEqual(self.library.materialize(item["id"]).read_bytes(), self.source.read_bytes())
        self.assertFalse(self.library.legacy_index_path.exists())
        self.assertFalse(list(self.library.files_root.glob("*.ttenc")))
        self.assertNotIn(password, self.library.vault_path.read_text(encoding="utf-8"))

    def test_interrupted_legacy_migration_keeps_old_vault_retryable(self):
        import os
        from unittest.mock import patch
        from offline_transcriber.audio_library import _b64
        from offline_transcriber.bafen_core import BafenError

        password = "legacy secure password"
        salt = os.urandom(16)
        key = self.library._derive_legacy(password, salt)
        item = {"id": "legacy-item", "name": "旧版会议", "original_name": self.source.name,
                "extension": ".wav", "created_at": "before-bafen", "bytes": self.source.stat().st_size,
                "encrypted": True, "file": "legacy-item.ttenc", "keywords": []}
        (self.library.files_root / item["file"]).write_bytes(self.library._seal_legacy(key, self.source.read_bytes()))
        data = {"version": 1, "keywords": [], "items": [item]}
        self.library.legacy_index_path.write_bytes(self.library._seal_legacy(key, json.dumps(data).encode()))
        self.library.vault_path.write_text(json.dumps({"version": 1, "salt": _b64(salt),
            "check": _b64(self.library._seal_legacy(key, b"tingtao-vault-check"))}), encoding="utf-8")
        real_pack = self.library.bafen.pack

        def fail_at_index(source, secret, output=None, **kwargs):
            if Path(output).name == "payload.bfq":
                raise BafenError("模拟迁移中断")
            return real_pack(source, secret, output, **kwargs)

        with patch.object(self.library.bafen, "pack", side_effect=fail_at_index):
            with self.assertRaisesRegex(RuntimeError, "模拟迁移中断"):
                self.library.unlock(password)
        self.assertEqual(self.library.encryption_format, "legacy-aes")
        self.assertTrue(self.library.legacy_index_path.is_file())
        self.assertTrue((self.library.files_root / "legacy-item.ttenc").is_file())
        self.assertFalse(list(self.library.files_root.glob("*.bfq")))
        self.library.unlock(password)
        self.assertEqual(self.library.materialize("legacy-item").read_bytes(), self.source.read_bytes())

    def test_password_length_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "8"):
            self.library.enable_encryption("short")


if __name__ == "__main__":
    unittest.main()
