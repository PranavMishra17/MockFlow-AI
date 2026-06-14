"""
Focused Wing D verification: render the rebuilt feedback reveal, the personality
dashboard, and the compare/landing surfaces against the smoke server, assert the
key DOM is present, and capture console errors + screenshots.

Usage: start `python tests/e2e/smoke_server.py` first, then run this with a page
arg: feedback | dashboard | landing | compare  (default: feedback).
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5099"
SHOTS = Path(__file__).parent / "_shots"
PAGE = sys.argv[1] if len(sys.argv) > 1 else "feedback"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1180, "height": 1500})
        pg = ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append((m.type, m.text)) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
        for _ in range(40):
            try:
                pg.goto(BASE + "/health", timeout=2000)
                break
            except Exception:
                time.sleep(0.5)

        def cnt(sel):
            return pg.eval_on_selector_all(sel, "els => els.length")

        def txt(sel):
            return pg.eval_on_selector(sel, "e => e.textContent.trim()") if cnt(sel) else None

        res = {}
        if PAGE == "feedback":
            iid = "00000000-0000-0000-0000-0000000000a1"  # valid UUID; stubs ignore it
            pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
            pg.goto(BASE + "/feedback/" + iid, wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(1500)
            res = {
                "hero": cnt(".verdict-hero"), "reco": txt(".vh-reco"),
                "caret": cnt(".spectrum-caret"), "current_seg": cnt(".spectrum-seg.is-current"),
                "level": txt(".vh-level"), "gap": cnt(".vh-gap"),
                "next_rep_cta": cnt(".next-rep-cta"),
                "signals": cnt(".signal-card"), "stars": cnt(".signal-star"),
                "evidence": cnt(".signal-evidence"), "differentiators": cnt(".differentiators"),
                "vs_last": cnt(".vs-last"), "ga_line": cnt(".ga-line"),
                "delivery_chips": cnt(".delivery-chip"),
            }
        elif PAGE == "dashboard":
            pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(1800)
            res = {
                "statband_tiles": cnt(".pp-stat"), "radar_svg": cnt(".radar-svg"),
                "radar_axes": cnt(".radar-axis-label"), "you_polygon": cnt(".radar-you"),
                "target_polygon": cnt(".radar-target"), "reco_spark": cnt(".reco-spark"),
                "stability": cnt(".stab-grid"), "best_lines": cnt(".bl-card"),
                "next_action": cnt(".pp-next"),
            }
        elif PAGE == "compare":
            ids = "00000000-0000-0000-0000-0000000000b2,00000000-0000-0000-0000-0000000000a1"
            pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
            pg.goto(BASE + "/compare?ids=" + ids, wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(1500)
            res = {
                "compare_radar": cnt(".radar-svg"), "delta_rows": cnt(".cmp-row"),
                "deltas_up": cnt(".cmp-delta.up"), "chips": cnt(".cmp-chip"),
                "improved": cnt(".cmp-improved"), "lagged": cnt(".cmp-lags"),
            }
        elif PAGE == "landing":
            pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
            pg.goto(BASE + "/", wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(1600)
            res = {
                "persona": cnt(".lp-persona"),
                "real_radar": cnt("#lpStatsReal .radar-svg"),
                "real_chips": cnt("#lpStatsReal .lp-chip"),
                "real_reco": (pg.eval_on_selector("#lpStatsReal .lp-reco", "e=>e.textContent.trim()") if cnt("#lpStatsReal .lp-reco") else None),
                "cta": cnt(".lp-persona-cta"),
                "sample_display": (pg.eval_on_selector(".lp-stats.signed-out-only", "e=>getComputedStyle(e).display") if cnt(".lp-stats.signed-out-only") else "n/a"),
            }
            try:
                pg.locator(".lp-persona").scroll_into_view_if_needed()
                pg.wait_for_timeout(300)
                pg.locator(".lp-persona").screenshot(path=str(SHOTS / "wingd_landing_persona.png"))
            except Exception:
                pass
        elif PAGE == "landing_out":
            # signed-OUT: the illustrative sample + the "coming next" prep section
            pg.goto(BASE + "/", wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(1500)
            res = {
                "sample_radar": cnt("#lpSampleRadar .radar-svg"),
                "sample_reco": (pg.eval_on_selector(".lp-stats.signed-out-only .lp-reco", "e=>e.textContent.trim()") if cnt(".lp-stats.signed-out-only .lp-reco") else None),
                "prep": cnt(".lp-prep"), "prep_chips": cnt(".lp-prep__chip"),
                "prep_brief_items": cnt(".lp-prep__brief li"),
            }
            try:
                pg.locator(".lp-persona").scroll_into_view_if_needed()
                pg.wait_for_timeout(200)
                pg.locator(".lp-persona").screenshot(path=str(SHOTS / "wingd_sample_persona.png"))
                pg.locator(".lp-prep").scroll_into_view_if_needed()
                pg.wait_for_timeout(200)
                pg.locator(".lp-prep").screenshot(path=str(SHOTS / "wingd_prep.png"))
            except Exception:
                pass

        pg.evaluate("document.querySelectorAll('.sig-reveal').forEach(e=>e.classList.add('is-in'))")
        pg.wait_for_timeout(200)
        diag = pg.evaluate("""() => {
            const pick = s => { const e = document.querySelector(s); return e ? {h: e.offsetHeight, top: Math.round(e.getBoundingClientRect().top), disp: getComputedStyle(e).display} : null; };
            return { scrollH: document.body.scrollHeight, statsContent: pick('#statsContent'),
                     pp_next: pick('.pp-next'), bl_rail: pick('.bl-rail'), stab: pick('.stab-grid'),
                     lp_persona: pick('.lp-persona'), compare: pick('.compare-view') };
        }""")
        pg.screenshot(path=str(SHOTS / f"wingd_{PAGE}.png"), full_page=True)
        b.close()

    print(f"== {PAGE} ==")
    for k, v in res.items():
        print(f"  {k}: {v}")
    print("DIAG:", diag)
    print("CONSOLE:", errs[:12] if errs else "(clean)")


if __name__ == "__main__":
    main()
