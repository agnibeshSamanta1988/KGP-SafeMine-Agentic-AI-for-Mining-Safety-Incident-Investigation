"""Page switching: the footer belongs to the page (after its content, also when the page stops), and a failing page reports itself."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
FOOTER = "decision support over public MSHA data and 30 CFR"


def _run_page(tmp_path, monkeypatch, body: str, name: str = "demo") -> AppTest:
    from app import nav
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
    monkeypatch.setattr(nav, "V", str(tmp_path) + "/")          # restored automatically after the test
    script = (f"import sys\nsys.path.insert(0, r'{ROOT}')\n"
              f"from app import nav\n"
              f"nav._page_runner('{name}.py', 'Demo page')()\n")
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    return at


def _texts(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_the_footer_comes_after_the_page_content(tmp_path, monkeypatch):
    at = _run_page(tmp_path, monkeypatch, "import streamlit as st\nst.markdown('PAGE-CONTENT-ONE')\nst.markdown('PAGE-CONTENT-TWO')\n")
    assert not at.exception
    t = _texts(at)
    assert t.index("PAGE-CONTENT-TWO") < next(i for i, x in enumerate(t) if FOOTER in x)       # content first, footer last
    assert sum(FOOTER in x for x in t) == 1                                                     # exactly one footer


def test_a_page_that_stops_early_still_gets_its_footer_after_its_message(tmp_path, monkeypatch):
    """dashboard.py and reports.py end with st.stop() when there is nothing to show: the footer used to disappear on those pages."""
    at = _run_page(tmp_path, monkeypatch, "import streamlit as st\nst.info('Nothing to show yet.')\nst.stop()\nst.markdown('NEVER-REACHED')\n")
    assert not at.exception
    assert any("Nothing to show yet." in i.value for i in at.info)
    t = _texts(at)
    assert "NEVER-REACHED" not in t and sum(FOOTER in x for x in t) == 1


def test_a_page_that_raises_reports_itself_instead_of_leaving_a_blank_area(tmp_path, monkeypatch):
    at = _run_page(tmp_path, monkeypatch, "import streamlit as st\nst.markdown('BEFORE-THE-ERROR')\nraise ValueError('boom for the test')\n")
    assert not at.exception                                                                     # handled, not an uncaught Streamlit exception
    assert any("could not be displayed" in e.value and "Demo page" in e.value for e in at.error)
    assert any("ValueError" in c.value for c in at.code)                                        # short technical detail for the administrator
    t = _texts(at)
    assert "BEFORE-THE-ERROR" in t and sum(FOOTER in x for x in t) == 1                         # what was drawn stays; the footer still follows


def test_every_registered_page_has_a_runner_a_unique_url_and_exists():
    from app import nav
    stems = [Path(f).stem for _, items in nav.GROUPS for f, _, _ in items]
    assert len(stems) == len(set(stems)) == 9                                                   # Home + eight pages, no two share a route
    assert all((Path(nav.V) / f"{s}.py").exists() for s in stems)
    runners = [nav._page_runner(f, t) for _, items in nav.GROUPS for f, t, _ in items]
    assert [r.__name__ for r in runners] == stems                                               # URL path = file name: /dashboard, /assistant ...


def test_the_entry_script_no_longer_draws_the_footer_itself():
    src = (ROOT / "app" / "ui.py").read_text(encoding="utf-8")
    assert "lib.footer()" not in src      # it is drawn by each page, so it can never stand alone while the page content is cleared


def test_the_real_pages_that_use_st_stop_are_translated_not_left_to_block_the_footer():
    """dashboard.py and reports.py call st.stop(); after Streamlit's own stop nothing more can be drawn, so the runner turns it into a page end."""
    from app import nav
    for f in ("dashboard.py", "reports.py"):
        src = (Path(nav.V) / f).read_text(encoding="utf-8")
        assert "st.stop()" in src                                                               # the page does use it ...
        assert "st.stop" not in " ".join(c for c in nav._compile_page(nav.V + f).co_names if c == "stop")   # ... and the compiled page no longer calls it


def test_home_quick_start_row_uses_real_page_links_not_the_plain_fallback():
    """With callable pages a file path no longer resolves; Home must link to the registered pages (icon, no underline) instead of the markdown fallback."""
    script = (f"import sys\nsys.path.insert(0, r'{ROOT}')\nimport streamlit as st\nfrom app import nav\n"
              "pages = nav.build_pages()\nst.navigation(pages, position='hidden').run()\n")
    at = AppTest.from_string(script, default_timeout=90)
    at.run()
    assert not at.exception
    assert not any("](/assistant)" in m.value for m in at.markdown)
