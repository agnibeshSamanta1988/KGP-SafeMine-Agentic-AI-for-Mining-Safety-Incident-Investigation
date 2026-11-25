"""Navigation and sidebar of the KGP-SafeMine console.

`build_pages()` is the single registry of pages (group, title, icon, file); `st.navigation(..., position="hidden")` runs the router and
`render_sidebar()` draws our own sidebar from the same registry with `st.page_link`, so routes, session state and page behaviour are
Streamlit's own. The sidebar has three stacked parts: a fixed brand header, a navigation block that scrolls on its own, and a footer
anchored to the bottom (theme, live status, user, log out).
"""
from __future__ import annotations

import ast
import logging
import traceback
from html import escape
from pathlib import Path

import streamlit as st

from app import auth, brand, lib, theme
from safemine import config

log = logging.getLogger("safemine.ui")

V = str(Path(__file__).resolve().parent / "views") + "/"

# (group heading, [(file, title, material icon)]) -- the first page of the first group is the landing page
GROUPS = [
    ("Main navigation", [("home.py", "Home", "home"), ("dashboard.py", "Safety Dashboard", "dashboard"),
                         ("assistant.py", "AI Safety Assistant", "smart_toy")]),
    ("Analysis", [("investigation.py", "Incident Investigation", "search"), ("regulatory.py", "Regulatory Intelligence", "gavel")]),
    ("Knowledge", [("knowledge.py", "Knowledge Base", "menu_book")]),
    ("Governance", [("reports.py", "Reports & Export", "description"), ("review.py", "Human Review Queue", "fact_check"),
                    ("settings.py", "Settings", "settings")]),
]


def url_paths() -> list[str]:
    """URL path of every page except the landing page (Streamlit derives it from the file name)."""
    return [Path(f).stem for _, items in GROUPS for f, _, _ in items if f != "home.py"]


def _page_error(title: str, exc: Exception) -> None:
    """A page that raises must say so on the page, not leave the content area empty. The full traceback goes to the server log only."""
    log.error("page %r failed: %s", title, "".join(traceback.format_exception(exc)))
    st.error(f"**{title}** could not be displayed because of an unexpected error. Your login, your other pages and your chat are not affected. "
             "Select the page again; if it keeps failing, tell an administrator.")
    with st.expander("Technical details"):
        st.code(f"{type(exc).__name__}: {str(exc)[:300]}")


class _PageDone(Exception):
    """Internal: what `st.stop()` means inside a page, "this page has nothing more to draw". It is not Streamlit's own StopException: once
    Streamlit has been asked to stop it refuses every later st.* call, so the footer could not be drawn after it."""


class _StopToPageEnd(ast.NodeTransformer):
    """Turns the statement `st.stop()` of a page script into `raise __page_done__`, so a page that ends early (nothing to show, no data yet)
    still gets its footer. Plain source transformation: nothing is patched globally, so concurrent sessions cannot interfere."""

    def visit_Expr(self, node: ast.Expr):
        c = node.value
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "stop"
                and isinstance(c.func.value, ast.Name) and c.func.value.id == "st"):
            return ast.copy_location(ast.Raise(exc=ast.Name(id="__page_done__", ctx=ast.Load()), cause=None), node)
        return node


def _compile_page(path: str):
    tree = _StopToPageEnd().visit(ast.parse(Path(path).read_text(encoding="utf-8"), filename=path))
    return compile(ast.fix_missing_locations(tree), path, "exec")


def _page_runner(file: str, title: str):
    """The callable behind one page: runs the page's script, then draws the disclaimer footer as the LAST element of the PAGE.

    Why the footer is part of the page. The footer used to be drawn by the entry script after `nav.run()`. Streamlit clears the page content the
    moment another page is selected but keeps the entry script's elements until the new run replaces them, so for the time the new page needed
    to start, only the footer was on screen (a blank content area). It also never appeared on a page that ends with `st.stop()`. Drawn here, the
    footer belongs to the page: it leaves with the page's content and always comes after it, also when the page stops early. A page `st.stop()`
    ends the page (see _StopToPageEnd); Streamlit's other control-flow exceptions (st.rerun) are BaseExceptions and pass through untouched; only
    a genuine error is caught and reported on the page."""
    path = V + file

    def run() -> None:
        try:
            exec(_compile_page(path), {"__name__": "__main__", "__file__": path, "__page_done__": _PageDone})
        except _PageDone:
            pass                   # the page ended early on purpose (st.stop())
        except Exception as e:  # noqa: BLE001  a page bug is reported on the page
            _page_error(title, e)
        finally:
            lib.footer()
    run.__name__ = Path(file).stem   # Streamlit derives the URL path from it: /dashboard, /assistant ... (Home is the landing page)
    return run


def build_pages() -> dict[str, list]:
    pages = {g: [st.Page(_page_runner(f, t), title=t, icon=f":material/{i}:", default=(f == "home.py")) for f, t, i in items] for g, items in GROUPS}
    st.session_state["_sm_pages"] = {Path(p.url_path or "").name or "home": p for ps in pages.values() for p in ps}   # for in-page links (Home's quick-start row)
    return pages


# ------------------------------------------------------------------ live status (real checks only)
def status() -> dict:
    """What the footer shows, derived from the same checks as /health: configuration problems, active model, tracing reachability."""
    from safemine import tracing
    probs = config.startup_checks()
    t = tracing.status()
    if not t["enabled"]:
        tr = ("off", "Tracing off", "No Langfuse keys are configured, so questions are not traced to Langfuse (local history still works).")
    elif not t.get("switched_on", True):
        tr = ("off", "Tracing paused", "Tracing is switched off in Settings (saves the Langfuse free tier). Local history still works.")
    elif t["reachable"] is None:
        tr = ("wait", "Tracing: checking", "Checking whether the Langfuse server answers.")
    elif t["reachable"] and t.get("auth") is False:
        tr = ("bad", "Tracing: keys rejected", "Langfuse answers but rejects LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY: traces are NOT recorded. "
              "Copy both keys again from the Langfuse project settings into .env and restart.")
    elif t["reachable"]:
        tr = ("ok", "Tracing: Langfuse", f"Langfuse is reachable ({t.get('host', '')}); each question is recorded as a trace.")
    else:
        tr = ("bad", "Tracing: unreachable", "Langfuse is configured but not reachable: traces are NOT being recorded.")
    return {"problems": probs, "ready": not probs, "model": config.llm_label(), "model_ok": config.llm_configured(), "tracing": tr}


def _dot(kind: str) -> str:
    return f'<span class="sb-dot {kind}"></span>'


def _status_block(s: dict) -> None:
    ready_tip = "All configuration checks passed: data stores, indexes and the language-model key are in place." if s["ready"] \
        else "Setup needed: " + "; ".join(s["problems"])
    k, label, tip = s["tracing"]
    st.markdown(
        '<div class="sb-status">'
        f'<div class="sb-row" title="{escape(ready_tip, quote=True)}">{_dot("ok" if s["ready"] else "bad")}'
        f'<span class="sb-strong">{"System Ready" if s["ready"] else "Setup Required"}</span></div>'
        f'<div class="sb-row sb-sec2" title="Active language model (change it in Settings)">{_dot("ok" if s["model_ok"] else "bad")}'
        f'<span>Model · {escape(s["model"])}</span></div>'
        f'<div class="sb-row sb-sec2" title="{escape(tip, quote=True)}">{_dot(k)}<span>{escape(label)}</span></div>'
        '</div>', unsafe_allow_html=True)


def render_sidebar(pages: dict, cfg: dict) -> None:
    with st.sidebar:
        with st.container(key="sb_brand"):
            st.markdown(f'<div class="sb-brandrow">{brand.logo_img("sidebar")}<div class="sb-brandtxt"><div class="sb-name">KGP-SafeMine</div>'
                        '<div class="sb-tag">Mining Safety Intelligence</div></div></div>', unsafe_allow_html=True)
        with st.container(key="sb_nav"):
            for grp, items in pages.items():
                st.markdown(f'<div class="sb-group">{escape(grp)}</div>', unsafe_allow_html=True)
                for p in items:
                    st.page_link(p)
        with st.container(key="sb_footer"):
            theme.switcher()
            _status_block(status())
            auth.render_sidebar(cfg)


# ------------------------------------------------------------------ styling (the sidebar is navy in both themes)
SIDEBAR_CSS = """
<style>
[data-testid="stSidebar"] { min-width: 17rem; }
[data-testid="stSidebarHeader"] { padding: .5rem .75rem 0 0; min-height: 0; height: 0; overflow: visible; position: relative; z-index: 5; }
[data-testid="stSidebarContent"] { overflow-y: auto; }
[data-testid="stSidebarUserContent"] { padding: 0 !important; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stLayoutWrapper"] > .st-key-sb_nav) { gap: 0 !important; min-height: calc(100vh - 24px); }
[data-testid="stLayoutWrapper"]:has(> .st-key-sb_nav) { flex: 1 1 auto; }

/* 1. brand: fixed at the top, same size on every page */
[data-testid="stLayoutWrapper"]:has(> .st-key-sb_brand) { position: sticky; top: 0; z-index: 4; }
[data-testid="stLayoutWrapper"]:has(> .st-key-sb_footer) { position: sticky; bottom: 0; z-index: 4; }
.st-key-sb_brand { margin-top: -24px; flex: none; background: var(--sb-bg); padding: calc(1rem + 24px) 1rem .8rem 1rem; border-bottom: 1px solid var(--sb-border); }
.sb-brandrow { display: flex; align-items: center; gap: .75rem; }
.sb-brandrow img.sm-logo { width: 52px; height: auto; flex: none; filter: drop-shadow(0 3px 8px rgba(0,0,0,.35)); }
.sb-name { font-size: 1.1rem; font-weight: 800; letter-spacing: .01em; color: var(--sb-strong); line-height: 1.15; }
.sb-tag { font-size: .66rem; letter-spacing: .09em; text-transform: uppercase; color: var(--sb-accent) !important; font-weight: 700; margin-top: .15rem; }
.sb-name, .sb-tag { white-space: nowrap; }

/* 2. navigation: takes the free height and scrolls by itself */
.st-key-sb_nav { gap: 0; flex: 1 1 auto; padding: .4rem .6rem .6rem .6rem; }
.sb-group { font-size: .62rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--sb-muted) !important; padding: .85rem .6rem .25rem .6rem; }
.st-key-sb_nav [data-testid="stElementContainer"] { margin: 0; }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"] { position: relative; display: flex; align-items: center; gap: .65rem; min-height: 2.25rem; padding: .35rem .7rem;
    margin: 1px 0; border-radius: 8px; text-decoration: none; transition: background .15s ease, color .15s ease; }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"] p { font-size: .88rem; font-weight: 500; color: var(--sb-text) !important; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"] span[data-testid="stIconMaterial"], .st-key-sb_nav a[data-testid="stPageLink-NavLink"] [data-testid="stIconMaterial"] {
    font-size: 1.15rem !important; color: var(--sb-muted) !important; flex: none; width: 1.3rem; }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"]:hover { background: var(--sb-hover); }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"]:hover p { color: var(--sb-strong) !important; }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"][aria-current="page"] { background: var(--sb-active); }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"][aria-current="page"]::before { content: ""; position: absolute; left: 0; top: .35rem; bottom: .35rem; width: 3px; border-radius: 3px; background: var(--sb-accent); }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"][aria-current="page"] p { color: var(--sb-strong) !important; font-weight: 700; }
.st-key-sb_nav a[data-testid="stPageLink-NavLink"][aria-current="page"] [data-testid="stIconMaterial"] { color: var(--sb-accent) !important; }
.st-key-sb_nav a:focus-visible { outline: 2px solid var(--sb-accent); outline-offset: 1px; }

/* 3. footer: anchored to the bottom of the sidebar */
.st-key-sb_footer { gap: .3rem; flex: none; background: var(--sb-bg2); border-top: 1px solid var(--sb-border); padding: .5rem .9rem .8rem .9rem; }
.st-key-sb_footer .st-key-theme_row { margin: 0; }
.st-key-sb_footer > *, .st-key-sb_nav > *, .st-key-sb_brand > * { flex: 0 0 auto !important; }
.st-key-sb_footer [data-testid="stMarkdownContainer"], .st-key-sb_nav [data-testid="stMarkdownContainer"], .st-key-sb_brand [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
.sb-status { display: flex; flex-direction: column; gap: .2rem; padding: .15rem 0 .1rem 0; }
.sb-row { display: flex; align-items: center; gap: .5rem; font-size: .74rem; color: var(--sb-text); min-width: 0; }
.sb-row span:last-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sb-strong { font-weight: 700; color: var(--sb-strong); font-size: .78rem; }
.sb-sec2 { color: var(--sb-muted); font-size: .7rem; }
.sb-dot { width: .5rem; height: .5rem; border-radius: 50%; flex: none; background: #7A8798; }
.sb-dot.ok { background: #22C55E; box-shadow: 0 0 0 2px rgba(34,197,94,.22); } .sb-dot.bad { background: #EF4444; box-shadow: 0 0 0 2px rgba(239,68,68,.25); }
.sb-dot.wait { background: var(--sb-accent); } .sb-dot.off { background: #7A8798; }
.sb-user { display: flex; align-items: center; gap: .6rem; padding: .35rem 0 .1rem 0; min-width: 0; }
.sb-avatar { width: 1.9rem; height: 1.9rem; border-radius: 50%; background: var(--sb-accent); color: var(--on-amber) !important; font-weight: 800; font-size: .85rem; display: flex; align-items: center; justify-content: center; flex: none; }
.sb-uname { font-size: .82rem; font-weight: 700; color: var(--sb-strong); line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sb-role { font-size: .68rem; color: var(--sb-muted); line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] .st-key-_auth_logout button { background: transparent !important; border: 1px solid var(--sb-accent) !important; color: var(--sb-accent) !important; font-weight: 700; min-height: 2.1rem; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] .st-key-_auth_logout button:hover { background: var(--sb-accent) !important; color: var(--on-amber) !important; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] .st-key-_auth_logout button p, [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] .st-key-_auth_logout button span { color: inherit !important; }

.st-key-sb_footer .st-key-theme_row [data-testid="stHorizontalBlock"] { flex-direction: row !important; flex-wrap: nowrap !important; align-items: center; gap: .25rem; }
.st-key-sb_footer .st-key-theme_row [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; flex: 1 1 0 !important; }
/* narrow screens: Streamlit turns the sidebar into an overlay; keep the same structure, a little tighter */
@media (max-width: 640px) { .st-key-sb_brand { padding: .8rem .9rem .6rem .9rem; } .sb-group { padding-top: .6rem; } }
@media (max-height: 640px) { .sb-sec2 { display: none; } }
</style>
"""


def css() -> None:
    st.markdown(SIDEBAR_CSS, unsafe_allow_html=True)
