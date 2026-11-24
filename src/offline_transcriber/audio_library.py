from __future__ import annotations

import base64
import copy
import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

# Legacy-only reader: existing 1.6.x vaults are migrated to Bafen after unlock.
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .bafen_core import BafenCore, BafenError
from .meeting import clean_markers
from .paths import APP_ROOT, DATA_ROOT
from .record_naming import sanitize_record_name


class VaultLockedError(RuntimeError):
    pass


class InvalidVaultPasswordError(ValueError):
    pass


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


class AudioLibrary:
    """Local catalogue protected by Guanhai Bafen BFQ; legacy AES is read-only."""

    def __init__(self, root: str | Path | None = None, core: BafenCore | None = None):
        self.root = Path(root) if root else DATA_ROOT / "audio-library"
        self.files_root = self.root / "files"
        self.session_root = self.root / ".session"
        self.index_path = self.root / "index.json"
        self.encrypted_index_path = self.root / "index.bfq"
        self.legacy_index_path = self.root / "index.ttenc"
        self.vault_path = self.root / "vault.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(exist_ok=True)
        core_name = "guanhai-core.exe" if os.name == "nt" else "guanhai-core"
        self.bafen = core or BafenCore(APP_ROOT / "core" / core_name)
        self._password: str | None = None
        self._key: bytes | None = None  # Only for reading pre-Bafen vaults.
        self._mutex = threading.RLock()

    @property
    def encryption_enabled(self) -> bool:
        return self.vault_path.is_file()

    @property
    def encryption_format(self) -> str:
        if not self.encryption_enabled:
            return "none"
        try:
            vault = json.loads(self.vault_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("音频库加密配置已损坏") from exc
        return "legacy-aes" if vault.get("format") is None else str(vault.get("format"))

    @property
    def unlocked(self) -> bool:
        if not self.encryption_enabled:
            return True
        return self._key is not None if self.encryption_format == "legacy-aes" else self._password is not None

    def _require_access(self) -> None:
        if not self.unlocked:
            raise VaultLockedError("音频库已加密锁定，请先输入密码解锁")

    @staticmethod
    def _derive_legacy(password: str, salt: bytes) -> bytes:
        if len(password) < 8:
            raise ValueError("加密密码至少需要 8 个字符")
        return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))

    @staticmethod
    def _seal_legacy(key: bytes, payload: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(key).encrypt(nonce, payload, b"TingTao.AudioLibrary.v1")

    @staticmethod
    def _open_legacy(key: bytes, payload: bytes) -> bytes:
        if len(payload) < 29:
            raise InvalidVaultPasswordError("旧版加密数据不完整")
        try:
            return AESGCM(key).decrypt(payload[:12], payload[12:], b"TingTao.AudioLibrary.v1")
        except Exception as exc:
            raise InvalidVaultPasswordError("密码错误或旧版加密数据已损坏") from exc

    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < 8:
            raise ValueError("加密密码至少需要 8 个字符")

    def _pack(self, source: Path, password: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise RuntimeError(f"目标八分文件已存在：{destination.name}")
        try:
            self.bafen.pack(source, password, destination)
        except BafenError as exc:
            raise RuntimeError(f"观海·八分封装失败：{exc}") from exc
        if not destination.is_file():
            raise RuntimeError("观海·八分未生成目标文件")

    def _unpack(self, source: Path, password: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise RuntimeError(f"恢复目标已存在：{destination.name}")
        try:
            self.bafen.unpack(source, password, destination)
        except BafenError as exc:
            destination.unlink(missing_ok=True)
            raise InvalidVaultPasswordError("密码错误或观海·八分包已损坏") from exc
        if not destination.is_file():
            raise InvalidVaultPasswordError("观海·八分未返回有效内容")

    def _read_bfq(self, source: Path, password: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix=".bafen-read-", dir=self.root) as directory:
            target = Path(directory) / "payload.bin"
            self._unpack(source, password, target)
            return target.read_bytes()

    def _write_bfq(self, payload: bytes, password: str, destination: Path) -> None:
        with tempfile.TemporaryDirectory(prefix=".bafen-write-", dir=self.root) as directory:
            temporary = Path(directory)
            source = temporary / "payload.json"
            packed = temporary / "payload.bfq"
            source.write_bytes(payload)
            self._pack(source, password, packed)
            os.replace(packed, destination)

    def unlock(self, password: str) -> None:
        with self._mutex:
            if not self.encryption_enabled:
                self._password = None
                self._key = None
                return
            if self.encryption_format == "legacy-aes":
                try:
                    vault = json.loads(self.vault_path.read_text(encoding="utf-8"))
                    key = self._derive_legacy(password, _unb64(vault["salt"]))
                    if self._open_legacy(key, _unb64(vault["check"])) != b"tingtao-vault-check":
                        raise InvalidVaultPasswordError("密码错误")
                    self._key = key
                    self._load()
                    self._migrate_legacy(password)
                    return
                except InvalidVaultPasswordError:
                    self._key = None
                    raise
                except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._key = None
                    raise InvalidVaultPasswordError("密码错误或旧版音频库加密配置已损坏") from exc
            if self.encryption_format != "guanhai-bafen-bfq":
                raise InvalidVaultPasswordError("无法识别音频库加密格式")
            self._password = password
            try:
                self._load()
            except (InvalidVaultPasswordError, RuntimeError, OSError, ValueError) as exc:
                self._password = None
                if isinstance(exc, InvalidVaultPasswordError):
                    raise
                raise InvalidVaultPasswordError("密码错误或音频库加密配置已损坏") from exc

    def lock(self) -> None:
        self._password = None
        self._key = None
        if self.session_root.exists():
            shutil.rmtree(self.session_root, ignore_errors=True)

    def _load(self) -> dict:
        with self._mutex:
            self._require_access()
            try:
                if self.encryption_enabled:
                    if self.encryption_format == "legacy-aes":
                        if self._key is None or not self.legacy_index_path.is_file():
                            return {"version": 1, "keywords": [], "items": []}
                        payload = self._open_legacy(self._key, self.legacy_index_path.read_bytes())
                    else:
                        if self._password is None or not self.encrypted_index_path.is_file():
                            return {"version": 1, "keywords": [], "items": []}
                        payload = self._read_bfq(self.encrypted_index_path, self._password)
                    data = json.loads(payload.decode("utf-8"))
                elif self.index_path.is_file():
                    data = json.loads(self.index_path.read_text(encoding="utf-8"))
                else:
                    data = {"version": 1, "keywords": [], "items": []}
                if not isinstance(data.get("items"), list) or not isinstance(data.get("keywords"), list):
                    raise ValueError("音频库索引结构无效")
                return data
            except InvalidVaultPasswordError:
                raise
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("音频库索引无法读取，可能已损坏") from exc

    def _save(self, data: dict) -> None:
        with self._mutex:
            self._require_access()
            if self.encryption_enabled:
                if self.encryption_format != "guanhai-bafen-bfq" or self._password is None:
                    raise VaultLockedError("请先完成旧音频库迁移")
                self._write_bfq(json.dumps(data, ensure_ascii=False).encode("utf-8"), self._password, self.encrypted_index_path)
                self.index_path.unlink(missing_ok=True)
            else:
                temporary = self.root / ".index.tmp"
                temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self.index_path)
                self.encrypted_index_path.unlink(missing_ok=True)

    def items(self) -> list[dict]:
        return sorted(self._load()["items"], key=lambda item: item.get("created_at", ""), reverse=True)

    def keywords(self) -> list[str]:
        return sorted({str(value) for value in self._load()["keywords"]}, key=str.casefold)

    def add_keyword(self, value: str) -> str:
        keyword = " ".join(value.strip().split())
        if not keyword or len(keyword) > 40:
            raise ValueError("关键词须为 1–40 个字符")
        data = self._load()
        if keyword.casefold() not in {str(item).casefold() for item in data["keywords"]}:
            data["keywords"].append(keyword)
            self._save(data)
        return keyword

    def remove_keyword(self, value: str) -> None:
        data = self._load()
        data["keywords"] = [item for item in data["keywords"] if str(item).casefold() != value.casefold()]
        for item in data["items"]:
            item["keywords"] = [word for word in item.get("keywords", []) if word.casefold() != value.casefold()]
        self._save(data)

    def add(self, source: str | Path, name: str | None = None, keywords: list[str] | None = None) -> dict:
        with self._mutex:
            self._require_access()
            source = Path(source).resolve()
            if not source.is_file() or source.stat().st_size == 0:
                raise ValueError("音频文件不存在或为空")
            title = sanitize_record_name(name or source.stem, max_length=80)
            if not title:
                raise ValueError("请输入有效的音频名称")
            item_id = uuid.uuid4().hex
            encrypted = self.encryption_enabled
            destination = self.files_root / f"{item_id}.{'bfq' if encrypted else source.suffix.lower().lstrip('.')}"
            item = {
                "id": item_id, "name": title, "original_name": source.name,
                "extension": source.suffix.lower() or ".wav", "created_at": datetime.now().astimezone().isoformat(),
                "bytes": source.stat().st_size, "encrypted": encrypted,
                "file": destination.name, "keywords": list(dict.fromkeys(keywords or [])),
            }
            try:
                if encrypted:
                    if self._password is None:
                        raise VaultLockedError("音频库未解锁")
                    self._pack(source, self._password, destination)
                else:
                    shutil.copy2(source, destination)
                data = self._load()
                data["items"].append(item)
                self._save(data)
                return dict(item)
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    def _get(self, item_id: str) -> tuple[dict, dict]:
        data = self._load()
        for item in data["items"]:
            if item.get("id") == item_id:
                return item, data
        raise ValueError("音频记录不存在")

    def rename(self, item_id: str, name: str) -> None:
        title = sanitize_record_name(name, max_length=80)
        if not title:
            raise ValueError("请输入有效的音频名称")
        item, data = self._get(item_id)
        item["name"] = title
        self._save(data)

    def set_keywords(self, item_id: str, keywords: list[str]) -> None:
        cleaned = list(dict.fromkeys(" ".join(word.strip().split()) for word in keywords if word.strip()))
        if any(len(word) > 40 for word in cleaned):
            raise ValueError("单个关键词不能超过 40 个字符")
        item, data = self._get(item_id)
        item["keywords"] = cleaned
        self._save(data)

    def set_meeting(self, item_id: str, topic: str, markers: list[dict]) -> None:
        item, data = self._get(item_id)
        item["meeting_topic"] = " ".join(topic.split())[:120]
        item["markers"] = clean_markers(markers)
        self._save(data)

    def meeting_markdown(self, item_id: str) -> str:
        item, _data = self._get(item_id)
        from .meeting import marker_text
        lines = [f"# {item.get('meeting_topic') or item['name']} · 会中打点", ""]
        lines.extend(f"- {marker_text(marker)}" for marker in item.get("markers", []))
        if len(lines) == 2:
            lines.append("- 本次录音未设置打点。")
        lines.extend(["", "时间点可用于回到原音复核；内容由记录者填写，不是自动生成的事实结论。"])
        return "\n".join(lines) + "\n"

    def meeting_for_source(self, source: str | Path) -> dict | None:
        source = Path(source)
        for item in self._load()["items"]:
            if item.get("file") == source.name or item.get("id") == source.stem:
                return {"source": item["name"], "topic": item.get("meeting_topic", ""), "markers": item.get("markers", [])}
        return None

    def delete(self, item_id: str) -> None:
        item, data = self._get(item_id)
        data["items"].remove(item)
        self._save(data)
        (self.files_root / item["file"]).unlink(missing_ok=True)
        for path in self.session_root.glob(f"{item_id}.*") if self.session_root.exists() else []:
            path.unlink(missing_ok=True)

    def materialize(self, item_id: str) -> Path:
        with self._mutex:
            item, _data = self._get(item_id)
            stored = self.files_root / item["file"]
            if not stored.is_file():
                raise FileNotFoundError("音频库中的文件已丢失")
            if not item.get("encrypted"):
                return stored
            self.session_root.mkdir(exist_ok=True)
            target = self.session_root / f"{item_id}{item.get('extension', '.wav')}"
            with tempfile.TemporaryDirectory(prefix=".restore-", dir=self.session_root) as directory:
                restored = Path(directory) / f"audio{item.get('extension', '.wav')}"
                if self.encryption_format == "legacy-aes":
                    if self._key is None:
                        raise VaultLockedError("请先解锁音频库")
                    restored.write_bytes(self._open_legacy(self._key, stored.read_bytes()))
                else:
                    if self._password is None:
                        raise VaultLockedError("请先解锁音频库")
                    self._unpack(stored, self._password, restored)
                target.unlink(missing_ok=True)
                os.replace(restored, target)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            return target

    def export(self, item_id: str, destination: str | Path) -> Path:
        item, _data = self._get(item_id)
        source = self.materialize(item_id)
        destination = Path(destination)
        if not destination.suffix:
            destination = destination.with_suffix(item.get("extension", ".wav"))
        shutil.copy2(source, destination)
        return destination

    def _write_vault(self) -> None:
        vault = {"format": "guanhai-bafen-bfq", "version": 2, "core_version": "0.3.0"}
        temporary = self.root / ".vault.tmp"
        temporary.write_text(json.dumps(vault, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.vault_path)

    def enable_encryption(self, password: str) -> None:
        with self._mutex:
            self._check_password(password)
            if self.encryption_enabled:
                raise ValueError("音频库已经启用加密")
            data = self._load()
            created: list[Path] = []
            try:
                for item in data["items"]:
                    source = self.files_root / item["file"]
                    target = self.files_root / f"{item['id']}.bfq"
                    self._pack(source, password, target)
                    created.append(target)
                    item.update(encrypted=True, file=target.name)
                self._write_bfq(json.dumps(data, ensure_ascii=False).encode("utf-8"), password, self.encrypted_index_path)
                self._write_vault()
            except Exception:
                for path in created:
                    path.unlink(missing_ok=True)
                self.encrypted_index_path.unlink(missing_ok=True)
                raise
            self._password = password
            self.index_path.unlink(missing_ok=True)
            for item in data["items"]:
                plain = self.files_root / f"{item['id']}{item.get('extension', '.wav')}"
                if plain.name != item["file"]:
                    plain.unlink(missing_ok=True)

    def _migrate_legacy(self, password: str) -> None:
        """Commit a complete BFQ copy before removing any legacy ciphertext."""
        if self._key is None:
            raise VaultLockedError("旧音频库尚未解锁")
        original = self._load()
        data = copy.deepcopy(original)
        staging = Path(tempfile.mkdtemp(prefix=".bafen-migration-", dir=self.root))
        try:
            for item in data["items"]:
                packed = staging / f"{item['id']}.bfq"
                if item.get("encrypted"):
                    plain = staging / f"{item['id']}{item.get('extension', '.wav')}"
                    plain.write_bytes(self._open_legacy(self._key, (self.files_root / item["file"]).read_bytes()))
                    self._pack(plain, password, packed)
                    plain.unlink(missing_ok=True)
                else:
                    self._pack(self.files_root / item["file"], password, packed)
                item.update(encrypted=True, file=packed.name)
            index = staging / "index.bfq"
            self._write_bfq(json.dumps(data, ensure_ascii=False).encode("utf-8"), password, index)
            for item in data["items"]:
                os.replace(staging / item["file"], self.files_root / item["file"])
            os.replace(index, self.encrypted_index_path)
            self._write_vault()
            # Once the BFQ vault is committed, cleanup must never roll the session back
            # to a legacy-only in-memory state. Retryable residue contains ciphertext only.
            self._password = password
            self._key = None
            self.index_path.unlink(missing_ok=True)
            self.legacy_index_path.unlink(missing_ok=True)
            for path in self.files_root.glob("*.ttenc"):
                path.unlink(missing_ok=True)
        except Exception:
            if self.encryption_format == "guanhai-bafen-bfq":
                self._password = password
                self._key = None
            else:
                self._password = None
                # The old index and ciphertext remain authoritative before vault commit.
                for item in data["items"]:
                    (self.files_root / item["file"]).unlink(missing_ok=True)
                self.encrypted_index_path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def disable_encryption(self, password: str) -> None:
        with self._mutex:
            self.unlock(password)
            if not self.encryption_enabled:
                return
            data = self._load()
            for item in data["items"]:
                if item.get("encrypted"):
                    source = self.materialize(item["id"])
                    target = self.files_root / f"{item['id']}{item.get('extension', '.wav')}"
                    shutil.copyfile(source, target)
                    item.update(encrypted=False, file=target.name)
            temporary = self.root / ".index-plain.tmp"
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.index_path)
            self.vault_path.unlink(missing_ok=True)
            self._password = None
            self._key = None
            self.encrypted_index_path.unlink(missing_ok=True)
            self.legacy_index_path.unlink(missing_ok=True)
            for path in self.files_root.glob("*.ttenc"):
                path.unlink(missing_ok=True)
            for path in self.files_root.glob("*.bfq"):
                path.unlink(missing_ok=True)
            if self.session_root.exists():
                shutil.rmtree(self.session_root, ignore_errors=True)
