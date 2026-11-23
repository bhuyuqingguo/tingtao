from __future__ import annotations

import base64
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .paths import DATA_ROOT
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
    """Local audio catalogue. AES-256-GCM protects content and metadata when enabled."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else DATA_ROOT / "audio-library"
        self.files_root = self.root / "files"
        self.session_root = self.root / ".session"
        self.index_path = self.root / "index.json"
        self.encrypted_index_path = self.root / "index.ttenc"
        self.vault_path = self.root / "vault.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(exist_ok=True)
        self._key: bytes | None = None

    @property
    def encryption_enabled(self) -> bool:
        return self.vault_path.is_file()

    @property
    def unlocked(self) -> bool:
        return not self.encryption_enabled or self._key is not None

    def _require_access(self) -> None:
        if not self.unlocked:
            raise VaultLockedError("音频库已加密锁定，请先输入密码解锁")

    @staticmethod
    def _derive(password: str, salt: bytes) -> bytes:
        if len(password) < 8:
            raise ValueError("加密密码至少需要 8 个字符")
        return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))

    @staticmethod
    def _seal(key: bytes, payload: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(key).encrypt(nonce, payload, b"TingTao.AudioLibrary.v1")

    @staticmethod
    def _open(key: bytes, payload: bytes) -> bytes:
        if len(payload) < 29:
            raise InvalidVaultPasswordError("加密数据不完整")
        try:
            return AESGCM(key).decrypt(payload[:12], payload[12:], b"TingTao.AudioLibrary.v1")
        except Exception as exc:
            raise InvalidVaultPasswordError("密码错误或加密数据已损坏") from exc

    def _new_verifier(self, key: bytes) -> dict:
        return {"version": 1, "kdf": "scrypt", "salt": _b64(os.urandom(16)), "check": _b64(self._seal(key, b"tingtao-vault-check"))}

    def unlock(self, password: str) -> None:
        if not self.encryption_enabled:
            self._key = None
            return
        try:
            vault = json.loads(self.vault_path.read_text(encoding="utf-8"))
            key = self._derive(password, _unb64(vault["salt"]))
            if self._open(key, _unb64(vault["check"])) != b"tingtao-vault-check":
                raise InvalidVaultPasswordError("密码错误")
            self._key = key
            self._load()
        except InvalidVaultPasswordError:
            self._key = None
            raise
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._key = None
            raise InvalidVaultPasswordError("密码错误或音频库加密配置已损坏") from exc

    def lock(self) -> None:
        self._key = None
        if self.session_root.exists():
            shutil.rmtree(self.session_root, ignore_errors=True)

    def _load(self) -> dict:
        self._require_access()
        try:
            if self.encryption_enabled:
                if self._key is None or not self.encrypted_index_path.is_file():
                    return {"version": 1, "keywords": [], "items": []}
                payload = self._open(self._key, self.encrypted_index_path.read_bytes())
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
        self._require_access()
        temporary = self.root / ".index.tmp"
        if self.encryption_enabled:
            if self._key is None:
                raise VaultLockedError("音频库未解锁")
            temporary.write_bytes(self._seal(self._key, json.dumps(data, ensure_ascii=False).encode("utf-8")))
            os.replace(temporary, self.encrypted_index_path)
            self.index_path.unlink(missing_ok=True)
        else:
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
        self._require_access()
        source = Path(source).resolve()
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError("音频文件不存在或为空")
        title = sanitize_record_name(name or source.stem, max_length=80)
        if not title:
            raise ValueError("请输入有效的音频名称")
        item_id = uuid.uuid4().hex
        encrypted = self.encryption_enabled
        destination = self.files_root / f"{item_id}.{'ttenc' if encrypted else source.suffix.lower().lstrip('.')}"
        item = {
            "id": item_id, "name": title, "original_name": source.name,
            "extension": source.suffix.lower() or ".wav", "created_at": datetime.now().astimezone().isoformat(),
            "bytes": source.stat().st_size, "encrypted": encrypted,
            "file": destination.name, "keywords": list(dict.fromkeys(keywords or [])),
        }
        try:
            if encrypted:
                if self._key is None:
                    raise VaultLockedError("音频库未解锁")
                destination.write_bytes(self._seal(self._key, source.read_bytes()))
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

    def delete(self, item_id: str) -> None:
        item, data = self._get(item_id)
        data["items"].remove(item)
        self._save(data)
        (self.files_root / item["file"]).unlink(missing_ok=True)
        for path in self.session_root.glob(f"{item_id}.*") if self.session_root.exists() else []:
            path.unlink(missing_ok=True)

    def materialize(self, item_id: str) -> Path:
        item, _data = self._get(item_id)
        stored = self.files_root / item["file"]
        if not stored.is_file():
            raise FileNotFoundError("音频库中的文件已丢失")
        if not item.get("encrypted"):
            return stored
        if self._key is None:
            raise VaultLockedError("请先解锁音频库")
        self.session_root.mkdir(exist_ok=True)
        target = self.session_root / f"{item_id}{item.get('extension', '.wav')}"
        target.write_bytes(self._open(self._key, stored.read_bytes()))
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

    def enable_encryption(self, password: str) -> None:
        if self.encryption_enabled:
            raise ValueError("音频库已经启用加密")
        salt = os.urandom(16)
        key = self._derive(password, salt)
        data = self._load()
        for item in data["items"]:
            source = self.files_root / item["file"]
            target = self.files_root / f"{item['id']}.ttenc"
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(self._seal(key, source.read_bytes()))
            os.replace(temporary, target)
            item.update(encrypted=True, file=target.name)
        # Keep the old plaintext index usable until both encrypted structures are durable.
        index_temporary = self.root / ".index-encrypted.tmp"
        index_temporary.write_bytes(self._seal(key, json.dumps(data, ensure_ascii=False).encode("utf-8")))
        os.replace(index_temporary, self.encrypted_index_path)
        vault = {"version": 1, "kdf": "scrypt", "salt": _b64(salt), "check": _b64(self._seal(key, b"tingtao-vault-check"))}
        vault_temporary = self.root / ".vault.tmp"
        vault_temporary.write_text(json.dumps(vault, indent=2), encoding="utf-8")
        os.replace(vault_temporary, self.vault_path)
        self._key = key
        self.index_path.unlink(missing_ok=True)
        for item in data["items"]:
            plain = self.files_root / f"{item['id']}{item.get('extension', '.wav')}"
            if plain.name != item["file"]:
                plain.unlink(missing_ok=True)

    def disable_encryption(self, password: str) -> None:
        self.unlock(password)
        if self._key is None:
            return
        data = self._load()
        key = self._key
        for item in data["items"]:
            if item.get("encrypted"):
                source = self.files_root / item["file"]
                target = self.files_root / f"{item['id']}{item.get('extension', '.wav')}"
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(self._open(key, source.read_bytes()))
                os.replace(temporary, target)
                item.update(encrypted=False, file=target.name)
        # Preserve the encrypted index until the complete plaintext index is ready.
        index_temporary = self.root / ".index-plain.tmp"
        index_temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(index_temporary, self.index_path)
        self.vault_path.unlink(missing_ok=True)
        self._key = None
        self.encrypted_index_path.unlink(missing_ok=True)
        for path in self.files_root.glob("*.ttenc"):
            path.unlink(missing_ok=True)
