"""KGP-SafeMine enterprise console (Streamlit). Run: streamlit run app/ui.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import streamlit as st  # noqa: E402

from app import auth, brand, lib, theme  # noqa: E402
from app import nav as nav_ui  # noqa: E402
from safemine import config, tracing  # noqa: E402

st.set_page_config(page_title="KGP-SafeMine", page_icon=brand.FAVICON, layout="wide")
_boot = auth.boot_begin()   # hand-over after a login: the full-screen curtain goes up before ANYTHING else is drawn (None on every other run)
lib.theme()
lib.preload()      # heavy imports and the search index load in the background while the login screen is showing
CFG = auth.require_login(nav_ui.url_paths())   # login page + st.script stop until authenticated: nothing below runs for anonymous visitors
theme.apply()                # light / dark / system colours for everything below (the login page keeps its own look)

pages = nav_ui.build_pages()      # registry in app/nav.py: Home is the landing page after login
for _k, _v in (("provider", "upgrad" if config.provider_ready("upgrad") else config.LLM_PROVIDER), ("sleep_on", config.LLM_SLEEP_ENABLED), ("sleep_s", float(config.LLM_SLEEP_SECONDS)),
                 ("temperature", float(config.TEMPERATURE)), ("trace_on", tracing.switched_on())):
    st.session_state[_k] = st.session_state.get(_k, _v)   # re-assign so widget-bound values survive page switches
config.set_provider(st.session_state["provider"])
config.TEMPERATURE = float(st.session_state["temperature"])
config.LLM_SLEEP_ENABLED = st.session_state.get("sleep_on", config.LLM_SLEEP_ENABLED)
config.LLM_SLEEP_SECONDS = st.session_state.get("sleep_s", config.LLM_SLEEP_SECONDS)
tracing.set_enabled(st.session_state["trace_on"])   # Settings toggle: Langfuse tracing on/off (saves the free-tier quota)

nav = st.navigation(pages, position="hidden")
nav_ui.css()
nav_ui.render_sidebar(pages, CFG)
nav.run()   # each page draws its own footer after its content (app/nav.py:_page_runner)
auth.boot_end(_boot)   # reached only by a COMPLETED run: the page behind the curtain is whole, so lift it. An interrupted run leaves the flag set and the next run raises the curtain again
