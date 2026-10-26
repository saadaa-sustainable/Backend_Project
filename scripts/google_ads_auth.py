"""Shared Google Ads API auth: developer token + OAuth + version probe.

Four things have to line up before a single row comes back, and three of
them fail with errors that do not name the real cause. Keeping them in
one place means a caller gets a usable session or a sentence saying what
is missing, rather than a 401 to interpret.

  1. developer token   env GOOGLE_ADS_API
  2. OAuth token with  secrets/google_oauth_token_*.json carrying the
     the `adwords` scope   `adwords` scope -- sheets/drive is NOT enough
  3. customer id       env GOOGLE_ADS_CUSTOMER_ID, default 6770669478
  4. login customer id env GOOGLE_ADS_LOGIN_CUSTOMER_ID, default
                       6989532543 (Saadaa MCC) -- required because the
                       account sits under a manager

Verified 2026-10-21: API v24, two accessible accounts (6770669478
SAADAA, an ad account; 6989532543 Saadaa MCC, a manager). The developer
token returns real rows, so it is Basic access, not Test.

Nothing here prints a secret. This repo is PUBLIC.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SECRETS = ROOT / "secrets"
ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"

DEFAULT_CUSTOMER_ID = "6770669478"        # SAADAA, the only ad account
DEFAULT_LOGIN_CUSTOMER_ID = "6989532543"  # Saadaa MCC

#: Newest first. Google retires about one version a year, and a retired
#: one answers 404 on every path -- which reads as a wrong URL rather
#: than an expired version, so probe instead of hardcoding.
API_VERSIONS = [f"v{n}" for n in range(24, 15, -1)]


class GoogleAdsAuthError(RuntimeError):
    """Raised with a message that names the missing piece."""


@dataclass(frozen=True)
class AdsSession:
    headers: dict[str, str]
    version: str
    customer_id: str

    def search_stream(self, query: str, *, timeout: float = 180.0) -> list[dict]:
        """Run GAQL and return every row.

        `searchStream` rather than `search`: it returns the whole result
        set as a list of batches with no page token to follow, which for
        a daily pull of a few thousand rows is one request instead of a
        loop that can half-fail.
        """
        url = (f"https://googleads.googleapis.com/{self.version}"
               f"/customers/{self.customer_id}/googleAds:searchStream")
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=self.headers, json={"query": query})
        if r.status_code != 200:
            raise GoogleAdsAuthError(_explain(r))
        out: list[dict] = []
        for batch in r.json():
            out.extend(batch.get("results", []))
        return out


def _token_file() -> Path:
    for p in sorted(glob.glob(str(SECRETS / "google_oauth_token_*.json")),
                    key=os.path.getmtime, reverse=True):
        try:
            if ADWORDS_SCOPE in (json.load(open(p)).get("scopes") or []):
                return Path(p)
        except (OSError, ValueError):
            continue
    raise GoogleAdsAuthError(
        "No OAuth token carries the `adwords` scope. Mint one with:\n"
        "   ./.venv/bin/python scripts/google_oauth_login.py --scopes ads")


def _bearer(path: Path) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(path))
    if not creds.valid:
        creds.refresh(Request())
        path.write_text(creds.to_json())   # keep the refreshed access token
    return creds.token


def connect(*, customer_id: str | None = None,
            login_customer_id: str | None = None,
            api_version: str | None = None) -> AdsSession:
    """A ready-to-query session, or GoogleAdsAuthError naming what is missing."""
    dev_token = os.getenv("GOOGLE_ADS_API") or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not dev_token:
        raise GoogleAdsAuthError("GOOGLE_ADS_API is not set in .env")

    cid = (customer_id or os.getenv("GOOGLE_ADS_CUSTOMER_ID")
           or DEFAULT_CUSTOMER_ID).replace("-", "")
    login = (login_customer_id or os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
             or DEFAULT_LOGIN_CUSTOMER_ID).replace("-", "")

    headers = {"Authorization": f"Bearer {_bearer(_token_file())}",
               "developer-token": dev_token,
               "login-customer-id": login}

    if api_version:
        return AdsSession(headers, api_version, cid)

    with httpx.Client(timeout=60.0) as client:
        for v in API_VERSIONS:
            r = client.get(
                f"https://googleads.googleapis.com/{v}/customers:listAccessibleCustomers",
                headers=headers)
            if r.status_code == 404:
                continue
            if r.status_code != 200:
                raise GoogleAdsAuthError(_explain(r))
            if not r.json().get("resourceNames"):
                raise GoogleAdsAuthError(
                    "The token can see NO accounts. That is the signature of a "
                    "TEST-ACCESS developer token: it authenticates and then "
                    "returns nothing for a real account. Basic Access is a "
                    "separate application and review.")
            return AdsSession(headers, v, cid)
    raise GoogleAdsAuthError(
        f"Every API version 404'd ({API_VERSIONS[0]}..{API_VERSIONS[-1]}).")


def _explain(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:400]}
    msg = (body.get("error", {}) or {}).get("message", "") if isinstance(body, dict) else ""
    hint = {
        401: "the OAuth token is invalid or lacks the `adwords` scope.",
        403: "usually the developer token: not approved, wrong tier, or not "
             "permitted for this customer.",
        400: "often a malformed customer id, or login-customer-id set to an "
             "account that does not manage this one.",
    }.get(r.status_code, "")
    if "DEVELOPER_TOKEN_NOT_APPROVED" in json.dumps(body):
        hint = ("TEST ACCESS developer token -- authenticates, returns nothing "
                "for a production account.")
    return f"HTTP {r.status_code}: {msg or json.dumps(body)[:300]}" + (
        f"\n   -> {hint}" if hint else "")
