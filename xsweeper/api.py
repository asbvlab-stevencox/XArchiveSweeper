"""Minimal X API v2 client for the two documented delete endpoints."""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests

API = "https://api.x.com/2"


@dataclass
class Result:
    status: int
    ok: bool
    remaining: int | None
    reset: int | None
    detail: str = ""


class XClient:
    def __init__(self, session: requests.Session | None = None, auth=None,
                 bearer: str | None = None):
        self.s = session or requests.Session()
        self.auth = auth
        self.headers = {"User-Agent": "XArchiveSweeper/0.1"}
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"

    @classmethod
    def from_env(cls) -> "XClient":
        """OAuth 2.0 user token (X_USER_ACCESS_TOKEN) or OAuth 1.0a user keys."""
        tok = os.environ.get("X_USER_ACCESS_TOKEN")
        if tok:
            return cls(bearer=tok)
        keys = [os.environ.get(k) for k in
                ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")]
        if all(keys):
            from requests_oauthlib import OAuth1
            return cls(auth=OAuth1(*keys))
        raise RuntimeError("No credentials. Run `xsweeper auth` or set OAuth 1.0a keys "
                           "in .env (see README).")

    def _call(self, method: str, url: str) -> Result:
        r = self.s.request(method, url, headers=self.headers, auth=self.auth, timeout=30)

        def h(k):
            v = r.headers.get(k)
            return int(v) if v and str(v).isdigit() else None
        ok = False
        detail = ""
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code == 200:
            data = body.get("data", {})
            ok = bool(data.get("deleted", data.get("retweeted") is False))
        if not ok:
            detail = str(body.get("detail") or body.get("title") or body.get("errors") or r.text)[:300]
        return Result(r.status_code, ok, h("x-rate-limit-remaining"), h("x-rate-limit-reset"), detail)

    def me(self) -> str:
        r = self.s.get(f"{API}/users/me", headers=self.headers, auth=self.auth, timeout=30)
        r.raise_for_status()
        return r.json()["data"]["id"]

    def delete_post(self, post_id: str) -> Result:
        return self._call("DELETE", f"{API}/tweets/{post_id}")

    def unretweet(self, user_id: str, source_id: str) -> Result:
        return self._call("DELETE", f"{API}/users/{user_id}/retweets/{source_id}")
