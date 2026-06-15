#!/usr/bin/env python3
"""One-shot OAuth bootstrap for Tesla Fleet API.

Mints a fresh access_token + refresh_token pair and writes them to a
fleet-cache.json that tesla_solar_download.py can read.

Why this exists separately from `tesla_solar_download.py --setup`:
- It runs a localhost HTTP listener on 127.0.0.1:8585 to capture the OAuth
  ?code= callback automatically — no copy-paste of a redirect URL by the user.
- Tesla rejects the `https://my.home-assistant.io/redirect/oauth` redirect for
  fresh authorize calls outside HA's flow even though it's listed as
  registered in the developer portal. Using a localhost redirect we control
  end-to-end avoids that ambiguity.
- PKCE is required by Tesla even with confidential clients.

Usage:
    export TESLA_FLEET_CLIENT_ID=...
    export TESLA_FLEET_CLIENT_SECRET=...
    python3 scripts/tesla_oauth_bootstrap.py --cache-file /path/to/fleet-cache.json

In the developer portal, the redirect `http://localhost:8585/callback` must
be in the app's Allowed Redirect URI(s) list.
"""

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser

import requests

AUTHORIZE_URL = "https://auth.tesla.com/oauth2/v3/authorize"
TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
SCOPES = "openid offline_access energy_device_data"
DEFAULT_REDIRECT = "http://localhost:8585/callback"
DEFAULT_PORT = 8585


def _build_auth_url(client_id, redirect_uri, state, code_challenge):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _make_handler(result):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(u.query)
            result.update({k: v[0] for k, v in qs.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if "code" in result:
                self.wfile.write(b"OK - captured code. You can close this tab.")
            else:
                self.wfile.write(b"Error: " + self.path.encode("utf-8"))

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Tesla Fleet API OAuth bootstrap")
    parser.add_argument("--cache-file", required=True,
                        help="Output path for fleet-cache.json")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT,
                        help=f"Registered redirect URI (default: {DEFAULT_REDIRECT})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Local port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser; print URL only")
    args = parser.parse_args()

    client_id = os.environ.get("TESLA_FLEET_CLIENT_ID")
    client_secret = os.environ.get("TESLA_FLEET_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: TESLA_FLEET_CLIENT_ID and TESLA_FLEET_CLIENT_SECRET must be set",
              file=sys.stderr)
        sys.exit(1)

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    state = secrets.token_urlsafe(16)

    auth_url = _build_auth_url(client_id, args.redirect_uri, state, challenge)

    print(f"Listening on http://127.0.0.1:{args.port}{urllib.parse.urlparse(args.redirect_uri).path}")
    print(f"Auth URL:\n  {auth_url}\n")
    sys.stdout.flush()

    if not args.no_browser:
        webbrowser.open(auth_url)

    result = {}
    srv = http.server.HTTPServer(("127.0.0.1", args.port), _make_handler(result))
    while "code" not in result:
        srv.handle_request()

    if result.get("state") != state:
        print(f"STATE MISMATCH expected={state} got={result.get('state')}",
              file=sys.stderr)
        sys.exit(1)

    print("Got code, exchanging for tokens ...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": result["code"],
            "redirect_uri": args.redirect_uri,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Token exchange failed: HTTP {resp.status_code}\n{resp.text}",
              file=sys.stderr)
        sys.exit(1)

    body = resp.json()
    token = {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": time.time() + body.get("expires_in", 28800),
        "token_type": body.get("token_type", "Bearer"),
        "scope": body.get("scope") or SCOPES,
    }

    cache_dir = os.path.dirname(os.path.abspath(args.cache_file)) or "."
    os.makedirs(cache_dir, exist_ok=True)
    tmp = args.cache_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(token, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, args.cache_file)
    print(f"Wrote {args.cache_file} (mode 600)")
    print(f"  access_token expires in: {body.get('expires_in', 28800)}s")
    print(f"  refresh_token rotated:   {body['refresh_token'][:12]}...")


if __name__ == "__main__":
    main()
