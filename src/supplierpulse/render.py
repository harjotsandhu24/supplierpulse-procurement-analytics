"""Render genuine screenshots of the dashboard and the PDF decision brief.

Uses Playwright with the locally installed Microsoft Edge (no browser download needed):
    python -m supplierpulse.render
Screenshots are taken from the generated dashboard file itself, so they always show the
numbers the pipeline calculated.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings, load_settings

VIEWS = [
    ("overview", "01-procurement-overview.png"),
    ("performance", "02-supplier-performance.png"),
    ("decisions", "03-procurement-decisions.png"),
]


def _launch(p):
    try:
        return p.chromium.launch(channel="msedge")
    except Exception:  # noqa: BLE001 - fall back to a Playwright-managed Chromium if Edge is unavailable
        return p.chromium.launch()


def render_dashboard(settings: Settings) -> list[Path]:
    from playwright.sync_api import sync_playwright

    dash = settings.path("deliverables_dir") / "SupplierPulse_Dashboard.html"
    out_dir = settings.path("screenshots_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        for view, name in VIEWS:
            page.goto(dash.as_uri() + f"#{view}")
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_function(f"document.body.dataset.ready === '{view}'")
            page.wait_for_timeout(800)
            target = out_dir / name
            page.screenshot(path=str(target), full_page=True)
            written.append(target)
        # Focused crops used by the README / Notion
        page.goto(dash.as_uri() + "#performance")
        page.wait_for_function("document.body.dataset.ready === 'performance'")
        page.wait_for_timeout(800)
        crop = out_dir / "04-supplier-scorecard.png"
        page.locator("#performance .card").first.screenshot(path=str(crop))
        written.append(crop)
        page.goto(dash.as_uri() + "#overview")
        page.wait_for_function("document.body.dataset.ready === 'overview'")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        hero = out_dir / "00-hero-overview.png"
        page.screenshot(path=str(hero), clip={"x": 0, "y": 0, "width": 1440, "height": 900})
        written.append(hero)
        dep = out_dir / "06-category-dependency.png"
        page.locator("#overview .card").nth(1).screenshot(path=str(dep))
        written.append(dep)
        page.goto(dash.as_uri() + "#decisions")
        page.wait_for_function("document.body.dataset.ready === 'decisions'")
        page.wait_for_timeout(800)
        acts = out_dir / "07-action-list.png"
        page.locator("#decisions .card").first.screenshot(path=str(acts))
        written.append(acts)
        browser.close()
    return written


def render_brief(settings: Settings) -> list[Path]:
    from playwright.sync_api import sync_playwright

    src = settings.path("deliverables_dir") / "SupplierPulse_Decision_Brief.html"
    pdf = src.with_suffix(".pdf")
    png = settings.path("screenshots_dir") / "05-decision-brief.png"
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": 816, "height": 1056}, device_scale_factor=2)
        page.goto(src.as_uri())
        page.wait_for_function("document.body.dataset.ready === 'yes'")
        page.wait_for_timeout(500)
        page.pdf(path=str(pdf), format="Letter", print_background=True,
                 margin={"top": "0.35in", "bottom": "0.35in", "left": "0.4in", "right": "0.4in"})
        page.screenshot(path=str(png), full_page=True)
        browser.close()
    return [pdf, png]


def render_all(settings: Settings | None = None) -> list[Path]:
    settings = settings or load_settings()
    return render_dashboard(settings) + render_brief(settings)


if __name__ == "__main__":
    for path in render_all():
        print(path)
