"""Capture the three 'John Doe' example cards on their real surfaces:
  - compare:   /compare with no ids  -> .ex-compare
  - feedback:  a bogus interview id  -> .ex-dossier (on the error state)
  - dashboard: the empty state       -> .ex-persona (forced via the renderer)
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5099"
SHOTS = Path(__file__).parent / "_shots"


def main():
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 820, "height": 1500}, device_scale_factor=2)
        pg = ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append((m.type, m.text)) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errs.append(("pageerror", str(e))))

        # 1) compare example (no ids)
        pg.goto(BASE + "/__testlogin", wait_until="networkidle", timeout=20000)
        pg.goto(BASE + "/compare", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(1200)
        out["compare_example"] = pg.eval_on_selector_all(".ex-compare", "e=>e.length")
        el = pg.query_selector(".ex-compare")
        if el:
            el.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
            el.screenshot(path=str(SHOTS / "shot_ex_compare.png"))

        # 2) feedback example (bogus id -> interview-not-found error state)
        pg.goto(BASE + "/feedback/not-a-real-uuid", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(1500)
        out["feedback_example"] = pg.eval_on_selector_all(".ex-dossier", "e=>e.length")
        el = pg.query_selector(".ex-dossier")
        if el:
            el.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
            el.screenshot(path=str(SHOTS / "shot_ex_feedback.png"))

        # 3) dashboard empty state — drive the real renderer into the empty slot
        pg.goto(BASE + "/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(800)
        # standalone render check: the personality sample renderer
        ok = pg.evaluate("""() => {
            if (!window.MockFlowExamples) return 'no-examples';
            const d = document.createElement('div');
            d.id = '__exPersona';
            d.style.cssText = 'max-width:600px;margin:24px auto;padding:16px;';
            d.innerHTML = window.MockFlowExamples.renderSamplePersonality();
            document.body.insertBefore(d, document.body.firstChild);
            window.scrollTo(0,0);
            return d.querySelector('.ex-persona') ? 'ok' : 'no-render';
        }""")
        out["dashboard_example_render"] = ok
        pg.wait_for_timeout(500)
        el = pg.query_selector("#__exPersona .ex-persona")
        if el:
            el.screenshot(path=str(SHOTS / "shot_ex_personality.png"))

        b.close()
    print("EXAMPLES:", out)
    print("CONSOLE:", errs[:10] if errs else "(clean)")


if __name__ == "__main__":
    main()
