"""Focused hi-dpi shot of the dashboard radar, hovering one axis to show the
interactive tooltip. Throwaway helper for the moat redesign."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5099"
SHOTS = Path(__file__).parent / "_shots"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1180, "height": 1400}, device_scale_factor=2)
        pg = ctx.new_page()
        pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(1800)
        radar = pg.query_selector(".pp-radar") or pg.query_selector(".radar-svg")
        if radar:
            radar.scroll_into_view_if_needed()
            pg.wait_for_timeout(400)
            radar.screenshot(path=str(SHOTS / "shot_radar_plain.png"))
            # hover an axis hotspot to surface the tooltip
            hs = pg.query_selector('.radar-hotspot[data-axis="3"]')
            if hs:
                hs.hover()
                pg.wait_for_timeout(350)
                radar.screenshot(path=str(SHOTS / "shot_radar_hover.png"))
                print("hover shot ok")
        # also the stat band
        band = pg.query_selector(".pp-statband")
        if band:
            band.scroll_into_view_if_needed()
            pg.wait_for_timeout(200)
            band.screenshot(path=str(SHOTS / "shot_statband.png"))
        b.close()
    print("done")


if __name__ == "__main__":
    main()
