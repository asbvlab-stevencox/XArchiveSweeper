"""OAuth 2.0 Authorization Code with PKCE, using the user's own developer app."""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import urllib.parse
import webbrowser
from pathlib import Path

import requests

AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
SCOPES = "tweet.read tweet.write users.read offline.access"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect: str, state: str, challenge: str) -> str:
    q = dict(response_type="code", client_id=client_id, redirect_uri=redirect, scope=SCOPES,
             state=state, code_challenge=challenge, code_challenge_method="S256")
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def _token_request(data: dict) -> dict:
    cid = os.environ["X_CLIENT_ID"]
    secret = os.environ.get("X_CLIENT_SECRET")
    auth = (cid, secret) if secret else None
    if not secret:
        data["client_id"] = cid
    r = requests.post(TOKEN_URL, data=data, auth=auth, timeout=30)
    r.raise_for_status()
    return r.json()


def save_tokens(tok: dict, path: Path) -> None:
    path.write_text(json.dumps(tok))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def run_login(token_path: Path, port: int = 8765) -> None:
    cid = os.environ.get("X_CLIENT_ID")
    if not cid:
        raise SystemExit("Set X_CLIENT_ID (and X_CLIENT_SECRET for confidential apps) in .env")
    redirect = os.environ.get("X_REDIRECT_URI", f"http://127.0.0.1:{port}/callback")
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"XArchiveSweeper: you can close this tab.")

        def log_message(self, *a):
            pass

    url = authorize_url(cid, redirect, state, challenge)
    print("Open this URL and approve access:\n" + url)
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", port), H) as srv:
        while "code" not in got and "error" not in got:
            srv.handle_request()
    if got.get("state") != state or "code" not in got:
        raise SystemExit(f"Authorization failed: {got.get('error', 'state mismatch')}")
    tok = _token_request(dict(grant_type="authorization_code", code=got["code"],
                              redirect_uri=redirect, code_verifier=verifier))
    save_tokens(tok, token_path)
    print(f"Saved tokens to {token_path} (git-ignored). Do not share this file.")


def load_access_token(token_path: Path) -> str | None:
    """Return a fresh access token, refreshing via refresh_token if possible."""
    if not token_path.exists():
        return None
    tok = json.loads(token_path.read_text())
    if tok.get("refresh_token") and os.environ.get("X_CLIENT_ID"):
        try:
            new = _token_request(dict(grant_type="refresh_token",
                                      refresh_token=tok["refresh_token"]))
            save_tokens(new, token_path)
            tok = new
        except requests.RequestException:
            pass
    return tok.get("access_token")
