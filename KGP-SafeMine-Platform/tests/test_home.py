"""Sidebar navigation, footer and the Home page (Streamlit AppTest, no model call)."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
UI = (ROOT / "app" / "ui.py").as_posix()
HOME = (ROOT / "app" / "views" / "home.py").as_posix()

DISCLAIMER = ("KGP-SafeMine is an AI-assisted mining safety intelligence and decision-support system. Its outputs are intended to support, "
              "not replace, qualified investigators, mining safety professionals, regulatory experts, or authorised human decision-makers.")

# the whole console as a signed-in user (the login itself is covered in test_ui.py / test_auth)
APP = f"""
import sys, time
sys.path.insert(0, r"{ROOT.as_posix()}")
import streamlit as st
st.session_state["_auth_user"] = "analyst"
st.session_state["_auth_last_active"] = time.time()
exec(open(r"{UI}", encoding="utf-8").read())
"""


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch):
    """The console as a signed-in user, for this module only (the real login is covered in test_ui.py)."""
    from app import auth
    monkeypatch.setattr(auth, "require_login", lambda *a, **k: {"username": "analyst", "timeout_s": 1800.0, "role": "Safety Analyst"})


def _app() -> AppTest:
    at = AppTest.from_string(APP, default_timeout=120)
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    return at


def _text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_navigation_groups_and_titles_match_the_design():
    from app import nav
    got = {g: [t for _, t, _ in items] for g, items in nav.GROUPS}
    assert got == {"Main navigation": ["Home", "Safety Dashboard", "AI Safety Assistant"],
                   "Analysis": ["Incident Investigation", "Regulatory Intelligence"], "Knowledge": ["Knowledge Base"],
                   "Governance": ["Reports & Export", "Human Review Queue", "Settings"]}
    assert all((Path(nav.V) / f).exists() for _, items in nav.GROUPS for f, _, _ in items)      # every route has its page file


def test_home_is_the_landing_page_with_branding_status_and_user_footer():
    at = _app()
    html = _text(at)
    assert "Mining Safety Intelligence Platform" in html                       # Home content is what shows after login
    assert 'class="sb-name">KGP-SafeMine' in html and "Mining Safety Intelligence</div>" in html and "data:image/png;base64," in html
    for g in ("Main navigation", "Analysis", "Knowledge", "Governance"):
        assert f'class="sb-group">{g}<' in html
    assert "System Ready" in html or "Setup Required" in html                    # a status is always shown
    assert "analyst" in html and "Safety Analyst" in html                        # signed-in user and role
    assert [b for b in at.button if b.key == "_auth_logout"]                     # log out is present
    assert at.segmented_control(key="theme_seg").value == "system"               # the compact theme selector


def test_the_footer_never_shows_a_key_or_secret():
    import re

    from safemine import config
    html = _text(_app())
    for p in config.PROVIDERS.values():
        if p["api_key"] and "REPLACE" not in p["api_key"]:
            assert p["api_key"] not in html
    assert not re.search(r"(sk-[A-Za-z0-9]{10,}|\$2[aby]\$\d\d\$)", html)       # no API key or password hash


def test_status_reflects_real_configuration_problems(monkeypatch):
    from app import nav
    from safemine import config
    monkeypatch.setattr(config, "startup_checks", lambda: [])
    assert nav.status()["ready"] is True
    monkeypatch.setattr(config, "startup_checks", lambda: ["DuckDB missing: safemine.duckdb"])
    s = nav.status()
    assert s["ready"] is False and "DuckDB" in s["problems"][0]


def test_tracing_status_is_taken_from_the_probe(monkeypatch):
    from app import nav
    from safemine import tracing
    for t, kind in (({"enabled": False, "reachable": None}, "off"), ({"enabled": True, "reachable": None}, "wait"),
                    ({"enabled": True, "reachable": True}, "ok"), ({"enabled": True, "reachable": False}, "bad")):
        monkeypatch.setattr(tracing, "status", lambda t=t: t)
        assert nav.status()["tracing"][0] == kind


def test_logout_button_clears_the_session():
    at = _app()
    [b for b in at.button if b.key == "_auth_logout"][0].click()
    at.run()
    assert not at.exception
    assert "_auth_user" not in at.session_state or at.session_state["_auth_user"] == "analyst"   # the script re-seeds it, the chat state is gone


# ------------------------------------------------------------------ Home page
def _home() -> AppTest:
    at = AppTest.from_file(HOME, default_timeout=120)
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    return at


def test_home_has_every_section_and_the_exact_disclaimer():
    html = _text(_home())
    for s in ("Mining Safety Intelligence Platform", "Measured results", "What you can do here", "How a question is answered",
              "How the agents work together", "Built for a small model", "Data used by KGP-SafeMine", "Supervisor (orchestrator)"):
        assert s in html
    for a in ("Planner", "Incident Investigation", "Retrieval", "Regulatory Intelligence", "Verification", "Report Generation", "Human Review"):
        assert a in html
    assert DISCLAIMER in html
    assert html.count('class="hm-kpi"') == 4                                      # four measured results, read from the eval files
    assert "52 / 86" in html and "16 / 16" in html                                # frozen test score and the CFR checks
    for step in ("User question", "Planning", "Evidence retrieval", "Analysis", "Verification", "Response / report", "Human review"):
        assert step in html


def test_home_does_not_claim_independent_agents():
    html = _text(_home())
    assert "not separate services" in html and "Not implemented" in html and "a separate statistics agent" in html


def test_home_numbers_come_from_the_database():
    import duckdb

    from safemine import config
    html = _text(_home())
    con = duckdb.connect(str(config.DUCKDB_PATH), read_only=True)
    try:
        for table, label in (("accidents", "records"), ("mines", "mines"), ("violations", "records"), ("inspections", "records")):
            n = con.execute(f"select count(*) from {table}").fetchone()[0]
            assert f"{n:,} {label}" in html, (table, n)
        assert f"{con.execute('select count(distinct part || chr(45) || section) from cfr_sections').fetchone()[0]:,} sections" in html
    finally:
        con.close()
    assert "30 October 2026" in html                                              # the snapshot date comes from the orchestrator constant


def test_unindexed_sources_are_labelled_as_such():
    html = _text(_home())
    assert html.count("not yet part of the searchable corpus") == 3                # disasters, policy documents, reference statistics
