"""Installing an app an event names but this peer does not have (P5-F4 ~ F7). Used by the built-in event router.

The router asks the distribution peers configured in ARENA_APP_STORE_URLS. Every check is code: the package (source hash,
publisher signature, trusted publishers, size, id and version), then the owner's yes, then after loading the app's id,
version and (when the event pins it) its code hash. Accepted packages are kept in the router's own folder and checked
and loaded again after a restart. Installed code runs inside this peer's process without isolation."""
from __future__ import annotations

import json
import os
import shutil

import httpx

from ..crypto import pen_name
from ..sdk.packaging import check_package, load_app_file
from .plugin import app_fingerprint


class AppInstaller:
    def __init__(self, settings, fetch_url=None):
        self.s = settings
        self.fetch_url = fetch_url or self._http_get  # replaceable (tests, other transports)

    async def _http_get(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=self.s.http_timeout_sec) as hc:
            r = await hc.get(url)
            r.raise_for_status()
            return r.text

    def _root(self, ctx) -> str:
        return os.path.join(ctx.data_dir, "installed")

    def _dir(self, ctx, m) -> str:
        return os.path.join(self._root(ctx), m["app_id"], m["version"])

    @staticmethod
    def _module_name(m) -> str:
        return f"arena_installed_{m['app_id'].replace('-', '')}_{m['version'].replace('.', '_')}"

    async def ensure(self, ctx, refs: list, notice: dict) -> list:
        """try to install each app ref; returns the apps installed"""
        out = []
        for ref in refs:
            app = await self._one(ctx, ref, notice)
            if app is not None:
                out.append(app)
        return out

    async def store_urls(self, ctx) -> list[str]:
        """the configured app distribution peers, or (ARENA_APP_STORE_DISCOVER) those found on the broker by role (P6-A4)"""
        urls = list(self.s.app_store_urls)
        if not urls and self.s.app_store_discover:
            for broker in ctx.brokers.values():
                try:
                    found = await broker.find("앱 배포", role="앱 배포", identity=ctx.identity)
                except Exception:
                    continue
                urls += [p["url"] for p in found.get("peers", []) if p.get("url") and p["url"] not in urls]
        return urls

    async def _fetch(self, ctx, ref) -> tuple[dict | None, str | None, str]:
        why = "설정되거나 찾은 앱 배포 peer가 없음"
        for url in await self.store_urls(ctx):
            try:
                r = await ctx.call(url, {"op": "app_get", "app_id": ref["id"], "version": ref["version"]})
            except Exception as e:
                why = f"{url}: {type(e).__name__}"
                continue
            if not r.get("ok"):
                why = f"{url}: {r.get('error')}"
                continue
            pkg = r["package"]
            source = pkg.get("source")
            if source is None and pkg.get("manifest", {}).get("url"):
                try:
                    source = await self.fetch_url(pkg["manifest"]["url"])
                except Exception as e:
                    why = f"{pkg['manifest']['url']}: 내려받기 실패 {type(e).__name__}"
                    continue
            bad = check_package(pkg, self.s, ref["id"], ref["version"], source=source)
            if bad:
                why = f"{url}: {bad}"
                continue
            return pkg, source, ""
        return None, None, why

    async def _one(self, ctx, ref, notice):
        label = f"앱 {ref.get('name', '')}({ref['id']})"
        pkg, source, why = await self._fetch(ctx, ref)
        if pkg is None:
            ctx.log.emit("apps", ctx.pen, f"{label} 설치 못 함: {why}")
            return None
        m = pkg["manifest"]
        publisher = pen_name(m["publisher"], self.s.pen_name_prefix, self.s.pen_name_len)
        question = (f"이벤트 '{notice.get('title', '')}'({notice.get('notice_id')})가 앱 '{m['name']}' {m['version']}을 요구합니다. "
                    f"배포자 {publisher}, 코드 해시 {m['source_hash'][:12]}. 설치하면 이 코드가 내 peer 안에서 격리 없이 실행됩니다. 설치할까요?")
        answer = await ctx.owner.ask(question, f"앱 목록표: {json.dumps(m, ensure_ascii=False)}")
        if not answer.yes:
            ctx.log.emit("apps", ctx.pen, f"{label} 설치 안 함(소유자): {answer.why}")
            return None
        app = self._save_and_load(ctx, dict(pkg, source=source), ref)
        if app is None:
            return None
        await ctx.install_app(app)
        ctx.log.emit("apps", ctx.pen, f"{label} {m['version']} 설치(배포자 {publisher})")
        return app

    def _save_and_load(self, ctx, pkg, ref=None):
        """write the package, import it, check id, version and the pinned code hash; remove it again on any mismatch"""
        m = pkg["manifest"]
        d = self._dir(ctx, m)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as fh:
            json.dump(pkg, fh, ensure_ascii=False)
        path = os.path.join(d, f"{m['module']}.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(pkg["source"])
        why = None
        try:
            app = load_app_file(path, self._module_name(m), m["factory"], self.s)
        except Exception as e:
            app, why = None, f"불러오기 실패: {type(e).__name__}: {e}"
        if app is not None and (app.app_id != m["app_id"] or app.version != m["version"]):
            why = "불러온 앱의 app_id·버전이 목록표와 다름"
        elif app is not None and ref and ref.get("hash") and app_fingerprint(app) != ref["hash"]:
            why = "앱 코드가 이벤트가 지정한 코드 해시와 다름"
        if why:
            shutil.rmtree(d, ignore_errors=True)
            ctx.log.emit("apps", ctx.pen, f"앱 {m['name']} {m['version']} 설치 취소: {why}")
            return None
        return app

    async def reload(self, ctx) -> int:
        """after a restart: check every kept package again and load the ones that still pass"""
        n, root = 0, self._root(ctx)
        for app_id in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            for version in sorted(os.listdir(os.path.join(root, app_id))):
                f = os.path.join(root, app_id, version, "package.json")
                try:
                    with open(f, encoding="utf-8") as fh:
                        pkg = json.load(fh)
                except (OSError, ValueError):
                    continue
                bad = check_package(pkg, self.s, app_id, version)
                if bad:
                    ctx.log.emit("apps", ctx.pen, f"보관한 앱 {app_id} {version}을 불러오지 않음: {bad}")
                    continue
                if ctx.app_by_id(app_id) is not None:
                    continue
                app = self._save_and_load(ctx, pkg)
                if app is not None:
                    await ctx.install_app(app)
                    n += 1
        return n
