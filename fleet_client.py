"""Tesla Fleet API client with OAuth token persistence.

Replaces the Owner-API/teslapy stack that Tesla shut down on 2026-06-12.

Auth model:
- Reads TESLA_FLEET_CLIENT_ID / TESLA_FLEET_CLIENT_SECRET from environment.
- Persists access_token + refresh_token in fleet-cache.json.
- Refresh tokens rotate on every use; the new refresh_token is written back.
- On 400 invalid_grant, raises AuthRequired so the caller can exit(2).
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

AUTH_BASE = "https://fleet-auth.prd.vn.cloud.tesla.com"
API_BASE = "https://fleet-api.prd.na.vn.cloud.tesla.com"
SCOPES = "openid offline_access energy_device_data"
REFRESH_LEEWAY_SECONDS = 300


class AuthRequired(Exception):
    """Refresh failed; caller must run --setup to re-authorize."""


@dataclass
class FleetConfig:
    client_id: str
    client_secret: str
    cache_file: str

    @classmethod
    def from_env(cls, cache_file: str) -> "FleetConfig":
        client_id = os.environ.get("TESLA_FLEET_CLIENT_ID")
        client_secret = os.environ.get("TESLA_FLEET_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError(
                "TESLA_FLEET_CLIENT_ID and TESLA_FLEET_CLIENT_SECRET must be set"
            )
        return cls(client_id=client_id, client_secret=client_secret, cache_file=cache_file)


class FleetClient:
    def __init__(self, config: FleetConfig, timeout: int = 30):
        self.config = config
        self.timeout = timeout
        self._token: dict = self._load_cache()

    def _load_cache(self) -> dict:
        if not os.path.exists(self.config.cache_file):
            raise AuthRequired(f"No cache file at {self.config.cache_file}; run --setup")
        with open(self.config.cache_file) as f:
            data = json.load(f)
        for key in ("access_token", "refresh_token", "expires_at"):
            if key not in data:
                raise AuthRequired(f"Cache missing field {key}; run --setup")
        return data

    def _save_cache(self):
        tmp = self.config.cache_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._token, f, indent=2)
        os.replace(tmp, self.config.cache_file)

    @property
    def expires_at(self) -> float:
        return float(self._token["expires_at"])

    def _refresh_if_needed(self):
        if time.time() < self.expires_at - REFRESH_LEEWAY_SECONDS:
            return
        logger.info(
            "Refreshing access token",
            extra={"operation": "token_refresh_start"},
        )
        resp = requests.post(
            f"{AUTH_BASE}/oauth2/v3/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "refresh_token": self._token["refresh_token"],
            },
            timeout=self.timeout,
        )
        if resp.status_code == 400:
            raise AuthRequired(f"Refresh token rejected: {resp.text}")
        resp.raise_for_status()
        body = resp.json()
        self._token = {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token", self._token["refresh_token"]),
            "expires_at": time.time() + body.get("expires_in", 28800),
            "token_type": body.get("token_type", "Bearer"),
            "scope": body.get("scope", SCOPES),
        }
        self._save_cache()

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        self._refresh_if_needed()
        resp = requests.get(
            f"{API_BASE}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token['access_token']}"},
            timeout=self.timeout,
        )
        if resp.status_code in (401, 403):
            raise AuthRequired(f"GET {path} returned {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        body = resp.json()
        return body.get("response", body)

    def products(self) -> list:
        return self._get("/api/1/products") or []

    def site_info(self, site_id) -> dict:
        return self._get(f"/api/1/energy_sites/{site_id}/site_info") or {}

    def calendar_history(self, site_id, *, kind: str, period: str,
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None,
                         time_zone: Optional[str] = None) -> dict:
        params = {"kind": kind, "period": period}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if time_zone:
            params["time_zone"] = time_zone
        return self._get(f"/api/1/energy_sites/{site_id}/calendar_history", params) or {}

    def emit_token_status(self, log):
        expires_at_iso = datetime.fromtimestamp(self.expires_at, tz=timezone.utc).isoformat()
        hours_remaining = max(0.0, (self.expires_at - time.time()) / 3600.0)
        log.info(
            "Token status",
            extra={
                "operation": "token_status",
                "token_expires_at": expires_at_iso,
                "token_hours_remaining": hours_remaining,
            },
        )


def run_setup(cache_file: str, redirect_uri: str):
    """One-time interactive OAuth flow. Writes fleet-cache.json."""
    import secrets
    import urllib.parse

    config = FleetConfig.from_env(cache_file)
    state = secrets.token_urlsafe(16)
    auth_params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "prompt": "login",
    }
    auth_url = "https://auth.tesla.com/oauth2/v3/authorize?" + urllib.parse.urlencode(auth_params)

    print()
    print("STEP 1: Open this URL in a browser and authorize:")
    print()
    print(auth_url)
    print()
    print("STEP 2: Tesla will redirect to your registered redirect URI.")
    print("That page will likely show 'Page Not Found' — that is expected.")
    print("Copy the FULL URL of that page (it has ?code=... in it) and paste below.")
    print()
    callback = input("Callback URL: ").strip()
    parsed = urllib.parse.urlparse(callback)
    qs = urllib.parse.parse_qs(parsed.query)
    if "code" not in qs:
        raise RuntimeError(f"No 'code' parameter in {callback}")
    if qs.get("state", [None])[0] != state:
        raise RuntimeError("State mismatch — possible CSRF; restart the flow")
    code = qs["code"][0]

    resp = requests.post(
        f"{AUTH_BASE}/oauth2/v3/token",
        data={
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    token = {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": time.time() + body.get("expires_in", 28800),
        "token_type": body.get("token_type", "Bearer"),
        "scope": body.get("scope", SCOPES),
    }
    os.makedirs(os.path.dirname(os.path.abspath(cache_file)) or ".", exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(token, f, indent=2)
    print(f"Wrote {cache_file}")
