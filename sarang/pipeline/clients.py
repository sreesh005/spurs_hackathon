"""Thin HTTP clients for ScorePlay and TwelveLabs.

Reads always go out. Writes go through `write()`, which only prints the
request when DRY_RUN is on.
"""

import json

import httpx

from .config import Settings


class Api:
    def __init__(self, base_url: str, headers: dict[str, str], dry_run: bool, name: str):
        self.name = name
        self.dry_run = dry_run
        self.http = httpx.Client(base_url=base_url, headers=headers, timeout=60)

    def get(self, path: str, **kw) -> httpx.Response:
        return self.http.get(path, **kw)

    def search(self, path: str, body: dict, **kw) -> httpx.Response:
        """POST that only reads (search endpoints). Not gated by DRY_RUN."""
        return self.http.post(path, json=body, **kw)

    def write(self, method: str, path: str, body: dict | None = None, **kw) -> httpx.Response | None:
        """A write. With DRY_RUN on it is printed, not sent, and returns None.
        Extra kwargs go to httpx (e.g. `params`, or `data` + `files` for multipart)."""
        if self.dry_run:
            query = f"?{httpx.QueryParams(kw['params'])}" if kw.get("params") else ""
            print(f"[DRY_RUN {self.name}] {method} {str(self.http.base_url).rstrip('/')}{path}{query}")
            if body is not None:
                print(json.dumps(body, indent=2, ensure_ascii=False))
            if kw.get("data"):
                print(json.dumps(kw["data"], indent=2, ensure_ascii=False))
            if kw.get("files"):
                print(f"  (multipart file: {', '.join(str(f[0]) for f in kw['files'].values())})")
            return None
        r = self.http.request(method, path, json=body, timeout=kw.pop("timeout", 120), **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{self.name} {method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r


def scoreplay(s: Settings) -> Api:
    return Api(s.scoreplay_base_url, {"X-ScorePlay-Api-Key": s.scoreplay_api_key}, s.dry_run, "scoreplay")


def twelvelabs(s: Settings) -> Api:
    return Api(s.twelvelabs_base_url, {"x-api-key": s.twelvelabs_api_key}, s.dry_run, "twelvelabs")
