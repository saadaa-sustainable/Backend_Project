"""Screenshot a page of the running dashboard.

The Chrome extension connects to browsers on OTHER machines, whose
localhost is their own -- it cannot see this machine's dev server at
all. Playwright runs here, so it can.

Usage:
    ./.venv/bin/python scripts/shoot.py /user/analytics
    ./.venv/bin/python scripts/shoot.py /user/analytics --clip-text "Spend and orders"
    ./.venv/bin/python scripts/shoot.py /user/analytics --width 430 --out mobile.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path("exports/shots")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", nargs="?", default="/user/analytics")
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--wait", type=float, default=6.0,
                    help="seconds to let the client fetches settle")
    ap.add_argument("--clip-text", default=None,
                    help="screenshot only the section whose heading contains this")
    ap.add_argument("--full", action="store_true", help="full scrollable page")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = args.out or (args.path.strip("/").replace("/", "_") or "page") + ".png"
    dest = OUT_DIR / name

    errors: list[str] = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": args.width, "height": args.height},
                        device_scale_factor=2)
        pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text[:160]}")
              if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errors.append(f"[pageerror] {str(e)[:160]}"))
        pg.goto(args.base + args.path, wait_until="networkidle", timeout=90_000)
        pg.wait_for_timeout(int(args.wait * 1000))

        target = pg
        if args.clip_text:
            # Climb from the matching text to a block big enough to be
            # the section, so the shot is the widget and not the label.
            el = pg.locator(f"text={args.clip_text}").first
            if el.count():
                el.scroll_into_view_if_needed()
                pg.wait_for_timeout(600)
                box = el.evaluate(
                    """e => { let n = e; for (let i = 0; i < 6 && n.parentElement; i++) {
                         n = n.parentElement;
                         const r = n.getBoundingClientRect();
                         if (r.height > 120 && r.width > 400) break; }
                       const r = n.getBoundingClientRect();
                       return {x:r.x, y:r.y, width:r.width, height:r.height}; }"""
                )
                pg.screenshot(path=str(dest), clip=box)
                target = None
            else:
                print(f"  '{args.clip_text}' not found; shooting the viewport")
        if target is not None:
            pg.screenshot(path=str(dest), full_page=args.full)
        b.close()

    print(f"  saved {dest}  ({dest.stat().st_size // 1024} KB)")
    if errors:
        print(f"\n  {len(errors)} console errors/warnings:")
        for e in dict.fromkeys(errors):
            print("   ", e)
    else:
        print("  no console errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
