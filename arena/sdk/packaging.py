"""App packages: how an app travels through an app distribution peer (P5-F1, F2).

A package is one Python module's source and a manifest the publisher signs:
    {"manifest": {app_id, name, version, module, factory, source_hash, publisher, url?}, "publisher_sig": ..., "source": ...}
The source may be left out when the manifest names a download url. The same checks run at the store, at the installer
and on reload, all by code: source hash, publisher signature, trusted publishers, size, and the id and version wanted."""
from __future__ import annotations

import hashlib
import importlib.util
import sys

from ..crypto import Identity, verify
from ..peer.plugin import App, capabilities_of, is_uuid, version_ok

MANIFEST_KEYS = {"app_id", "name", "version", "module", "factory", "source_hash", "publisher", "url"}


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def package_app(publisher: Identity, *, app_id: str, name: str, version: str, module: str, factory: str, source: str,
                url: str | None = None) -> dict:
    """what an app developer hands to an app distribution peer"""
    manifest = {"app_id": app_id, "name": name, "version": version, "module": module, "factory": factory,
                "source_hash": source_hash(source), "publisher": publisher.pub, **({"url": url} if url else {})}
    return {"manifest": manifest, "publisher_sig": publisher.sign(manifest), "source": source}


def check_package(pkg: dict, settings, want_id: str | None = None, want_version: str | None = None, source: str | None = None) -> str | None:
    """None when the package may be offered to the owner; otherwise why not. `source` is the code fetched from the url"""
    if not isinstance(pkg, dict) or not isinstance(pkg.get("manifest"), dict):
        return "꾸러미 모양이 잘못됨"
    m = pkg["manifest"]
    if not set(m) <= MANIFEST_KEYS or not {"app_id", "name", "version", "module", "factory", "source_hash", "publisher"} <= set(m):
        return "목록표 항목이 잘못됨"
    if not is_uuid(m["app_id"]) or not str(m["module"]).isidentifier() or not str(m["factory"]).isidentifier():
        return "목록표의 app_id·module·factory가 잘못됨"
    if not verify(m["publisher"], m, pkg.get("publisher_sig", "")):
        return "배포자 서명이 맞지 않음"
    if settings.app_trusted_publishers and m["publisher"] not in settings.app_trusted_publishers:
        return "신뢰하는 배포자 목록에 없는 배포자"
    code = source if source is not None else pkg.get("source")
    if not isinstance(code, str):
        return "원본이 없음(내려받기 주소도 확인되지 않음)"
    if len(code.encode("utf-8")) > settings.app_max_source_bytes:
        return f"원본 크기가 상한({settings.app_max_source_bytes}바이트)을 넘음"
    if source_hash(code) != m["source_hash"]:
        return "원본 hash가 목록표의 source_hash와 다름"
    if want_id is not None and m["app_id"] != want_id:
        return f"app_id가 요구({want_id})와 다름"
    if want_version is not None and not version_ok(m["version"], want_version):
        return f"버전 {m['version']}이 요구 버전 {want_version}에 맞지 않음"
    return None


def load_app_file(path: str, module_name: str, factory: str, settings):
    """import one module file under its own name and build the app with factory(settings)"""
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod  # inspect.getsource (the app's code hash) finds the class through its module
    try:
        spec.loader.exec_module(mod)
        app = getattr(mod, factory)(settings)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    if not isinstance(app, App) or not capabilities_of(app):
        sys.modules.pop(module_name, None)
        raise ValueError(f"{path} did not produce an app (needs name, version, app_id and a capability)")
    return app
