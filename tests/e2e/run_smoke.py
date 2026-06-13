"""
Drive the smoke server in Chromium: visit each page in light + dark, capture
console errors/warnings and full-page screenshots.

Run the server first (python tests/e2e/smoke_server.py), then this script.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5099"
SHOTS = Path(__file__).parent / "_shots"
SHOTS.mkdir(exist_ok=True)

PAGES = [
    ("landing", "/"),
    ("dashboard", "/__testlogin"),  # logs in, redirects to /dashboard
    ("form", "/start"),
    ("past_calls", "/past-calls"),
    ("feedback", "/feedback/iv1"),
]

TOGGLE = "() => window.MockFlowHeader && window.MockFlowHeader.toggleTheme && window.MockFlowHeader.toggleTheme()"


def main():
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        logs = []
        page.on("console", lambda m: logs.append((m.type, m.text)) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: logs.append(("pageerror", str(e))))

        # wait for server
        for _ in range(30):
            try:
                page.goto(BASE + "/health", timeout=2000)
                break
            except Exception:
                time.sleep(0.5)

        for name, path in PAGES:
            logs.clear()
            try:
                page.goto(BASE + path, wait_until="networkidle", timeout=20000)
            except Exception as e:
                logs.append(("nav", str(e)))
            page.wait_for_timeout(1200)
            page.screenshot(path=str(SHOTS / f"{name}_light.png"), full_page=True)
            try:
                page.evaluate(TOGGLE)
                page.wait_for_timeout(500)
                page.screenshot(path=str(SHOTS / f"{name}_dark.png"), full_page=True)
                page.evaluate(TOGGLE)  # back to light
            except Exception as e:
                logs.append(("toggle", str(e)))
            results[name] = list(logs)

        browser.close()

    print("\n===== CONSOLE ERRORS / WARNINGS =====")
    total = 0
    for name, errs in results.items():
        print(f"\n--- {name} ---")
        if not errs:
            print("  (clean)")
        for t, msg in errs[:12]:
            total += 1
            print(f"  [{t}] {msg[:220]}")
    print(f"\nTOTAL issues: {total}")
    print("Screenshots in:", SHOTS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
