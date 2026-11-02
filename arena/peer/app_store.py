"""The app distribution peer's role (P5-F3). Optional: anyone may run one, there may be many, and each peer decides
whether to use one. It keeps app packages whose publisher signature checks, and serves them by app id over A2A."""
from __future__ import annotations

import json
import os

from ..sdk.packaging import check_package
from .plugin import BaseApp, version_ok


def _vkey(v: str):
    return tuple(int(x) for x in v.split(".") if x.isdigit())


class AppStoreRole(BaseApp):
    name, version, app_id = "platform.app_store", "1.0", "0a8f6a52-37c1-4b7e-9e2d-5c1f3b7a9d64"

    def __init__(self, settings, folder: str | None = None):
        self.s, self.folder = settings, folder or settings.app_store_dir
        os.makedirs(self.folder, exist_ok=True)

    def offers(self):
        return ["앱 배포"]

    def ops(self):
        return {"app_get": self._get, "app_list": self._list, "app_publish": self._publish}

    # ---- storage: <folder>/<app_id>/<version>.json ----
    def _path(self, app_id, version):
        return os.path.join(self.folder, app_id, f"{version}.json")

    def _all(self) -> list[dict]:
        out = []
        for app_id in sorted(os.listdir(self.folder)):
            d = os.path.join(self.folder, app_id)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    out.append(json.load(fh))
        return out

    # ---- ops ----
    async def _publish(self, ctx, msg, head):
        pkg = msg.get("package")
        if not isinstance(pkg, dict) or not isinstance(pkg.get("manifest"), dict):
            return {"ok": False, "error": "꾸러미 모양이 잘못됨"}
        # a link-only package: the code is checked by whoever downloads it; everything else is checked here
        bad = self._check_link_only(pkg) if pkg.get("source") is None else check_package(pkg, self.s)
        if bad:
            return {"ok": False, "error": bad}
        m = pkg["manifest"]
        path = self._path(m["app_id"], m["version"])
        if os.path.exists(path):
            return {"ok": False, "error": f"{m['name']} {m['version']}은 이미 있다"}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pkg, fh, ensure_ascii=False)
        return {"ok": True, "app_id": m["app_id"], "version": m["version"]}

    def _check_link_only(self, pkg) -> str | None:
        """a package without source must name a url; everything but the source hash is checked here"""
        from ..crypto import verify
        m = pkg["manifest"]
        if not m.get("url"):
            return "원본도 내려받기 주소도 없음"
        if not verify(m.get("publisher", ""), m, pkg.get("publisher_sig", "")):
            return "배포자 서명이 맞지 않음"
        if self.s.app_trusted_publishers and m["publisher"] not in self.s.app_trusted_publishers:
            return "신뢰하는 배포자 목록에 없는 배포자"
        return None

    async def _get(self, ctx, msg, head):
        want, version = msg.get("app_id"), msg.get("version")
        found = [p for p in self._all() if p["manifest"]["app_id"] == want and (not version or version_ok(p["manifest"]["version"], version))]
        if not found:
            return {"ok": False, "error": f"앱 {want}이 없다"}
        best = max(found, key=lambda p: _vkey(p["manifest"]["version"]))
        return {"ok": True, "package": best}

    async def _list(self, ctx, msg, head):
        return {"ok": True, "apps": [{k: p["manifest"][k] for k in ("app_id", "name", "version", "publisher")} for p in self._all()]}
