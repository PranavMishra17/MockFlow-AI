"""Hi-dpi shots of the redesigned dashboard player card + radar block."""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5099"
SHOTS = Path(__file__).parent / "_shots"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1080, "height": 1400}, device_scale_factor=2)
        pg = ctx.new_page()
        pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(1800)
        for sel, name in [(".pp-playercard", "shot_dash_playercard"),
                          (".pp-radar", "shot_dash_radar"),
                          (".pp-stability", "shot_dash_stability"),
                          (".pp-bestlines", "shot_dash_bestlines")]:
            el = pg.query_selector(sel)
            if el:
                el.scroll_into_view_if_needed()
                pg.wait_for_timeout(250)
                el.screenshot(path=str(SHOTS / (name + ".png")))
        b.close()
    print("done")


if __name__ == "__main__":
    main()
