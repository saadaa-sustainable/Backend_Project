"""Read a Google Sheet tab through the project's own Sheets OAuth token.

WHY NOT A SERVICE ACCOUNT
-------------------------
`ingest_asset_sources.py` reads its graphics tab with GOOGLE_CREDS_JSON,
a service account. That path does not work for these sheets: the
service account is not a member of them, and the organisation does not
hand out keys that are. The Desktop OAuth client in `secrets/` IS a
member, because it signs in as the owner -- so it is what this uses.

The token is loaded by this script and never printed. Nothing here
echoes it, writes it elsewhere, or puts it in an error message.

Refreshed in place when it has expired, which is the whole point of
storing a refresh token; if the refresh itself fails the script says so
and tells you which command re-issues it, rather than failing with a
Google stack trace nobody can act on.

Usage:
    ./.venv/bin/python scripts/read_sheet.py <sheet_id> --tabs
    ./.venv/bin/python scripts/read_sheet.py <sheet_id> --gid 2100495217 --range C:AW
    ./.venv/bin/python scripts/read_sheet.py <sheet_id> --tab 'Stock' --range C:AW --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
TOKEN = SECRETS / "google_oauth_token_sheets-drive.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit("pip install google-api-python-client google-auth") from exc

    if not TOKEN.exists():
        raise SystemExit(
            f"No Sheets token at {TOKEN.relative_to(ROOT)}.\n"
            "Create one with:  ./.venv/bin/python scripts/google_oauth_login.py "
            "--scopes sheets,drive --label sheets-drive")

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001
                # Deliberately not re-raising Google's object: it can
                # carry the request body, and the request body is the
                # refresh token.
                raise SystemExit(
                    f"Sheets token refresh failed ({type(exc).__name__}). "
                    "Re-issue it:  ./.venv/bin/python scripts/google_oauth_login.py "
                    "--scopes sheets,drive --label sheets-drive") from None
            TOKEN.write_text(creds.to_json())
        else:
            raise SystemExit("Sheets token is invalid and has no refresh token; re-issue it.")
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def tab_for_gid(api, sheet_id: str, gid: int) -> str:
    """A gid identifies a tab; the values API wants its NAME.

    A URL carries the gid, so this is the lookup anyone pasting a link
    needs, and it is why --gid exists alongside --tab.
    """
    meta = api.spreadsheets().get(spreadsheetId=sheet_id,
                                  fields="sheets.properties").execute()
    for s in meta.get("sheets", []):
        p = s["properties"]
        if p.get("sheetId") == gid:
            return p["title"]
    have = ", ".join(f'{s["properties"]["title"]} (gid {s["properties"]["sheetId"]})'
                     for s in meta.get("sheets", []))
    raise SystemExit(f"No tab with gid {gid}. Tabs: {have}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sheet_id")
    ap.add_argument("--tab")
    ap.add_argument("--gid", type=int)
    ap.add_argument("--range", default="A:ZZ", dest="rng")
    ap.add_argument("--rows", type=int, default=12, help="Rows to preview.")
    ap.add_argument("--json", dest="json_out", type=Path,
                    help="Write every row here as JSON instead of previewing.")
    args = ap.parse_args()

    api = service()

    if not args.tab and args.gid is None:
        meta = api.spreadsheets().get(spreadsheetId=args.sheet_id,
                                      fields="properties.title,sheets.properties").execute()
        print(f"Spreadsheet: {meta['properties']['title']}\n")
        for s in meta.get("sheets", []):
            p = s["properties"]
            g = p.get("gridProperties", {})
            print(f"  gid {p['sheetId']:>12}  {p['title']}"
                  f"  ({g.get('rowCount','?')} rows x {g.get('columnCount','?')} cols)")
        return 0

    tab = args.tab or tab_for_gid(api, args.sheet_id, args.gid)
    rows = (api.spreadsheets().values()
            .get(spreadsheetId=args.sheet_id, range=f"'{tab}'!{args.rng}",
                 # Formatted, so a date reads as the sheet shows it rather
                 # than as a serial number nobody can check by eye.
                 valueRenderOption="FORMATTED_VALUE")
            .execute().get("values", []))

    if args.json_out:
        args.json_out.write_text(json.dumps({"tab": tab, "range": args.rng, "rows": rows}))
        print(f"{len(rows)} row(s) -> {args.json_out}")
        return 0

    print(f"Tab: {tab}   range {args.rng}   {len(rows)} row(s)\n")
    width = max((len(r) for r in rows[:args.rows]), default=0)
    for i, r in enumerate(rows[:args.rows]):
        cells = [(c or "")[:18] for c in r] + [""] * (width - len(r))
        print(f"{i:>3} | " + " | ".join(f"{c:<18}" for c in cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
