"""KeyStore (P6-K1): where a peer's private key is made and kept, swappable. The peer program makes its key itself.

- OsKeyStore: the operating system's key store through `keyring` (macOS Keychain, Windows Credential Manager, Linux
  Secret Service). The key never sits in a file of ours.
- FileKeyStore: a file readable only by its owner (0600), the alternative (servers, test machines).
- auto (the default): a key that already exists in a file stays there (the same peer after an upgrade); otherwise the
  OS key store when the machine has one, else a file. The choice is said (`where`), never silent.

Limit (written down as P6-K1 asks): hardware key areas mostly do not support ed25519 (the Secure Enclave only P-256),
so the key is loaded into memory when signing. The OS key store protects it at rest and from other users, not from
code running as the owner."""
from __future__ import annotations

import os
from typing import Protocol

from ..config import ConfigError
from ..crypto import Identity


class KeyStore(Protocol):
    kind: str

    def load(self, name: str) -> Identity | None: ...
    def save(self, name: str, identity: Identity) -> None: ...
    def remove(self, name: str) -> None: ...
    def where(self, name: str) -> str: ...


def load_or_create(store: KeyStore, name: str) -> Identity:
    """the key named `name`; made here, by this peer, when there is none yet"""
    me = store.load(name)
    if me is None:
        me = Identity.generate()
        store.save(name, me)
    return me


class FileKeyStore:
    kind = "file"

    def load(self, name):
        return Identity.load(name) if os.path.exists(name) else None

    def save(self, name, identity):
        identity.save(name)

    def remove(self, name):
        if os.path.exists(name):
            os.remove(name)

    def where(self, name):
        return f"파일 {name} (권한 0600)"


class OsKeyStore:
    """keys in the OS key store under (service, the key's name). `backend` is a keyring backend (tests pass a fake)"""
    kind = "os"

    def __init__(self, service: str, backend):
        self.service, self.backend = service, backend

    def _user(self, name: str) -> str:
        return os.path.abspath(name)  # one machine may hold many peers: the name is where the peer's home is

    def load(self, name):
        v = self.backend.get_password(self.service, self._user(name))
        return Identity.from_hex(v) if v else None

    def save(self, name, identity):
        self.backend.set_password(self.service, self._user(name), identity.private_hex())

    def remove(self, name):
        try:
            self.backend.delete_password(self.service, self._user(name))
        except Exception:  # noqa: BLE001  (keyring raises its own error when there is nothing to delete)
            pass

    def where(self, name):
        return f"OS 키 보관소 ({type(self.backend).__name__}, 서비스 {self.service}, 이름 {self._user(name)})"


class AutoKeyStore:
    """a key already in a file stays in the file; a new key goes to the OS key store when there is one"""
    kind = "auto"

    def __init__(self, file: FileKeyStore, os_store: OsKeyStore | None):
        self.file, self.os = file, os_store

    def _for(self, name: str):
        if self.os is None or os.path.exists(name):
            return self.file
        return self.os

    def load(self, name):
        return self._for(name).load(name)

    def save(self, name, identity):
        self._for(name).save(name, identity)

    def remove(self, name):
        self._for(name).remove(name)

    def where(self, name):
        return self._for(name).where(name) + ("" if self.os else " — 이 기기에는 OS 키 보관소가 없어 파일에 둔다")


def os_backend():
    """the machine's keyring backend, or None when there is no usable OS key store"""
    try:
        import keyring
    except ImportError:
        return None
    b = keyring.get_keyring()
    return b if getattr(b, "priority", 0) > 0 else None


def open_key_store(settings, backend=None) -> KeyStore:
    kind = settings.key_store
    if kind == "file":
        return FileKeyStore()
    b = backend if backend is not None else os_backend()
    if kind == "os":
        if b is None:
            raise ConfigError("ARENA_KEY_STORE=os but this machine has no OS key store (install keyring and a backend, or use file)")
        return OsKeyStore(settings.key_store_service, b)
    if kind == "auto":
        return AutoKeyStore(FileKeyStore(), OsKeyStore(settings.key_store_service, b) if b is not None else None)
    raise ConfigError(f"ARENA_KEY_STORE must be auto, os or file, not {kind!r}")
