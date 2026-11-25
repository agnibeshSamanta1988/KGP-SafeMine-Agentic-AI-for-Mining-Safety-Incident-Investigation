"""Light / Dark / System theme: preference handling, palette, CSS, charts, and every page rendering in each mode."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
VIEWS = (ROOT / "app" / "views").as_posix()


def script(body: str) -> str:
    return f"import sys\nsys.path.insert(0, r'{ROOT.as_posix()}')\nimport streamlit as st\nfrom app import theme\n{body}\n"


def run(body: str, **session) -> AppTest:
    at = AppTest.from_string(script(body), default_timeout=60)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [str(e.value)[:200] for e in at.exception]
    return at


def test_default_is_system_and_follows_the_device():
    at = run("st.write(theme.preference(), theme.effective())")
    assert at.markdown[0].value.startswith("system ")


def test_explicit_choices_override_the_device():
    for mode in ("light", "dark"):
        at = run("st.write(theme.effective())", _theme_pref=mode)
        assert at.markdown[0].value == mode


def test_the_url_parameter_sets_the_theme_and_survives_a_refresh():
    at = AppTest.from_string(script("st.write(theme.preference())"), default_timeout=60)
    at.query_params["theme"] = "dark"
    at.run()
    assert at.markdown[0].value == "dark"
    at2 = AppTest.from_string(script("st.write(theme.preference())"), default_timeout=60)
    at2.query_params["theme"] = "nonsense"          # an unknown value falls back to system
    at2.run()
    assert at2.markdown[0].value == "system"


def test_css_carries_the_palette_of_the_effective_mode():
    from app import theme
    for mode in ("light", "dark"):
        at = run("st.session_state['_x'] = theme.css()", _theme_pref=mode)
        css = at.session_state["_x"]
        assert f"--bg:{theme.PALETTES[mode]['bg']}" in css and f"color-scheme: {mode}" in css
    assert theme.PALETTES["light"].keys() == theme.PALETTES["dark"].keys()                 # no colour missing in either mode


def test_native_widgets_are_only_inverted_when_the_mode_differs_from_streamlits_own():
    from app import theme
    at = run("st.session_state['_x'] = theme.css()", _theme_pref="dark")                  # test run: Streamlit's own theme is light
    assert "invert(" in at.session_state["_x"]
    at = run("st.session_state['_x'] = theme.css()", _theme_pref="light")
    assert "invert(" not in at.session_state["_x"]


def test_chart_helper_makes_dark_charts_readable():
    import altair as alt
    import pandas as pd
    at = run("""
import altair as alt, pandas as pd
c = alt.Chart(pd.DataFrame({'a': [1, 2], 'b': [3, 4]})).mark_bar().encode(x='a:O', y='b:Q')
st.session_state['_cfg'] = theme.style_chart(c).to_dict()['config']
st.session_state['_navy'] = theme.K.navy
""", _theme_pref="dark")
    cfg = at.session_state["_cfg"]
    assert cfg["background"] == "transparent" and cfg["axis"]["labelColor"] == theme_palette("dark")["muted"]
    assert at.session_state["_navy"] == "#7FB0F0"                                         # the brand navy would vanish on a dark background
    at = run("st.session_state['_navy'] = theme.K.navy", _theme_pref="light")
    assert at.session_state["_navy"] == "#0B2545"


def theme_palette(mode):
    from app import theme
    return theme.PALETTES[mode]


def test_switcher_selection_changes_the_choice_and_keeps_state():
    at = run("theme.switcher()\nst.write(theme.preference())\nst.session_state.setdefault('keep', 'chat-history')")
    assert at.markdown[-1].value == "system"
    for mode in ("dark", "light", "system"):
        at.segmented_control(key="theme_seg").set_value(mode)
        at.run()
        assert not at.exception and at.markdown[-1].value == mode
        assert at.session_state["keep"] == "chat-history"                 # switching never touches application state


def test_new_visitors_follow_the_device_and_a_remembered_choice_is_a_separate_setting():
    """Match Device is the default; a stored manual choice (cookie) beats the device; a link parameter beats the cookie."""
    from app import theme
    at = run("st.write(theme.preference())")
    assert at.markdown[0].value == "system"
    for stored, expect in (("dark", "dark"), ("light", "light"), ("system", "system"), ("bogus", "system")):
        at = AppTest.from_string(script("st.context.__class__.cookies = property(lambda s: {'sm_theme': %r})\nst.write(theme.preference())" % stored), default_timeout=60)
        at.run()
        assert at.markdown[0].value == expect, stored
    assert theme.COOKIE == "sm_theme"


def test_match_device_follows_the_device_while_light_and_dark_ignore_it(monkeypatch):
    from app import theme
    cases = [("light", "light", "light"), ("light", "dark", "light"), ("dark", "light", "dark"), ("dark", "dark", "dark"),
             ("system", "light", "light"), ("system", "dark", "dark")]            # (choice, device, shown)
    for choice, device, shown in cases:
        monkeypatch.setattr(theme, "native", lambda d=device: d)
        monkeypatch.setitem(__import__("streamlit").session_state, "_theme_pref", choice)
        assert theme.effective() == shown, (choice, device)
    monkeypatch.setitem(__import__("streamlit").session_state, "_theme_pref", "system")      # the device changes while Match Device is on
    monkeypatch.setattr(theme, "native", lambda: "light")
    assert theme.effective() == "light"
    monkeypatch.setattr(theme, "native", lambda: "dark")
    assert theme.effective() == "dark"
    monkeypatch.setattr(theme, "native", lambda: "light")
    assert theme.effective() == "light"


def test_both_palettes_define_every_token_and_the_sidebar_uses_them():
    from app import nav, theme
    assert theme.PALETTES["light"].keys() == theme.PALETTES["dark"].keys()
    for t in ("sb_bg", "sb_bg2", "sb_text", "header_bg", "hero_from", "amber", "ok_bg", "bad_fg", "input", "surface"):
        assert t in theme.PALETTES["light"]
    import re
    sidebar_hex = re.findall(r"#[0-9A-Fa-f]{6}", nav.SIDEBAR_CSS)
    assert set(sidebar_hex) <= {"#22C55E", "#EF4444", "#7A8798"}                  # only the status-dot colours are fixed; the rest are theme variables


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("page", ["home", "dashboard", "knowledge", "review", "settings", "reports", "regulatory", "investigation", "assistant"])
def test_every_page_renders_in_each_theme(page, mode):
    at = AppTest.from_file(f"{VIEWS}/{page}.py", default_timeout=120)
    for k, v in (("provider", "upgrad"), ("sleep_on", True), ("sleep_s", 2.0), ("temperature", 0.1), ("_theme_pref", mode)):
        at.session_state[k] = v
    at.run()
    assert not at.exception, (page, mode, [str(e.value)[:150] for e in at.exception])


def test_statistics_charts_render_in_both_themes():
    from app import stats_view
    d = {"metric": "count_by", "args": {"group_by": "classification", "year_from": 2015}, "total_matching_records": 12,
         "rows": [{"key": "Powered Haulage", "n": 6}, {"key": "Machinery", "n": 4}, {"key": "Electrical", "n": 2}], "source": "t", "note": ""}
    t = {"metric": "yearly_trend", "args": {}, "total_matching_records": 40, "rows": [{"year": y, "n": 5 + y % 3} for y in range(2015, 2025)], "source": "t"}
    for mode in ("light", "dark"):
        at = AppTest.from_string(script(f"from app import stats_view\nstats_view.render_stats({{'trace': [{{'kind': 'tool', 'tool': 'accident_stats', 'data': {d!r}}}, "
                                        f"{{'kind': 'tool', 'tool': 'accident_stats', 'data': {t!r}}}]}})"), default_timeout=60)
        at.session_state["_theme_pref"] = mode
        at.run()
        assert not at.exception, (mode, [str(e.value)[:200] for e in at.exception])
