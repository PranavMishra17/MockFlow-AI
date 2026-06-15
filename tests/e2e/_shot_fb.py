"""Hi-dpi focused shots of the redesigned feedback hero + one evidence card."""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5099"
SHOTS = Path(__file__).parent / "_shots"
IID = "00000000-0000-0000-0000-0000000000a1"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 900, "height": 1300}, device_scale_factor=2)
        pg = ctx.new_page()
        pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
        pg.goto(BASE + "/feedback/" + IID, wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(2200)
        hero = pg.query_selector(".verdict-hero")
        if hero:
            hero.scroll_into_view_if_needed()
            pg.wait_for_timeout(300)
            hero.screenshot(path=str(SHOTS / "shot_fb_hero.png"))
        sc = pg.query_selector(".scorecard")
        if sc:
            sc.scroll_into_view_if_needed(); pg.wait_for_timeout(200)
            sc.screenshot(path=str(SHOTS / "shot_fb_scorecard.png"))
        card = pg.query_selector(".signal-card")
        if card:
            card.scroll_into_view_if_needed(); pg.wait_for_timeout(200)
            card.screenshot(path=str(SHOTS / "shot_fb_evidence.png"))
        b.close()
    print("done")


if __name__ == "__main__":
    main()
