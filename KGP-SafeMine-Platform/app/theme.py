"""Light / Dark / System theme for the console.

Streamlit cannot change its own theme from Python, so the console carries its own: one palette per mode, exposed as CSS variables, plus
rules that restyle Streamlit's native widgets from those variables. "System" follows the operating system (Streamlit reports it to the app
as `st.context.theme`, and reruns the app when it changes). The choice is kept in the session and in the URL (`?theme=dark`), so a refresh
keeps it. Charts and tables read the same palette (`K`, `style_chart`).
"""
from __future__ import annotations

import streamlit as st

MODES = ("light", "dark", "system")
COOKIE = "sm_theme"                    # browser cookie holding the manual choice (never the detected device appearance)

PALETTES: dict[str, dict[str, str]] = {
    "light": {"bg": "#F6F8FB", "surface": "#FFFFFF", "surface2": "#EEF2F8", "border": "#E2E8F0", "text": "#1B2A3D", "muted": "#5B6B80",
              "subtle": "#7A8798", "input": "#FFFFFF", "note_bg": "#FFF8E1", "note_text": "#4A3B00", "shadow": "rgba(11,37,69,.05)",
              "brand": "#0B2545", "ok_bg": "#DCFCE7", "ok_fg": "#166534", "warn_bg": "#FEF3C7", "warn_fg": "#92400E",
              "bad_bg": "#FEE2E2", "bad_fg": "#991B1B", "info_bg": "#DBEAFE", "info_fg": "#1E40AF", "grid": "#E5EAF1", "code": "#EEF2F8",
              "header_bg": "rgba(246,248,251,.85)", "hero_from": "#0B2545", "hero_to": "#13315C", "on_hero": "#FFFFFF", "amber": "#F2A900", "on_amber": "#0B2545",
              "sb_bg": "#0B2545", "sb_bg2": "#13315C", "sb_text": "#C9D6EA", "sb_strong": "#FFFFFF", "sb_muted": "#8FA6C8", "sb_border": "rgba(255,255,255,.14)",
              "sb_hover": "rgba(255,255,255,.08)", "sb_active": "rgba(242,169,0,.16)", "sb_accent": "#F2A900"},
    "dark": {"bg": "#0D1626", "surface": "#15233A", "surface2": "#1E3050", "border": "#2B3C58", "text": "#E5ECF7", "muted": "#A5B4CB",
             "subtle": "#8393AD", "input": "#1A2A44", "note_bg": "#2C2510", "note_text": "#F4DC94", "shadow": "rgba(0,0,0,.35)",
             "brand": "#9CC4F5", "ok_bg": "#12351F", "ok_fg": "#86EFAC", "warn_bg": "#3B2D0C", "warn_fg": "#FCD34D",
             "bad_bg": "#3D1515", "bad_fg": "#FCA5A5", "info_bg": "#14305A", "info_fg": "#93C5FD", "grid": "#26364F", "code": "#1E3050",
             "header_bg": "rgba(13,22,38,.85)", "hero_from": "#17335E", "hero_to": "#1F4A80", "on_hero": "#FFFFFF", "amber": "#F2A900", "on_amber": "#0B2545",
             "sb_bg": "#111F36", "sb_bg2": "#16294A", "sb_text": "#C9D6EA", "sb_strong": "#FFFFFF", "sb_muted": "#8FA6C8", "sb_border": "rgba(255,255,255,.12)",
             "sb_hover": "rgba(255,255,255,.07)", "sb_active": "rgba(242,169,0,.18)", "sb_accent": "#F2A900"},
}
CHART = {  # mark colours: the brand navy would vanish on a dark background
    "light": {"navy": "#0B2545", "amber": "#F2A900", "grey": "#B8C2CF", "blue": "#3E5C8A",
              "series": ["#0B2545", "#F2A900", "#3E5C8A", "#7A8798", "#D9822B", "#2F7D6D", "#9AA7B8"], "ramp": ["#FFF3CF", "#0B2545"]},
    "dark": {"navy": "#7FB0F0", "amber": "#F2A900", "grey": "#4F617D", "blue": "#A9C3E8",
             "series": ["#7FB0F0", "#F2A900", "#A9C3E8", "#98A6BC", "#E0914A", "#4DB6A0", "#6C7C95"], "ramp": ["#2A2410", "#F2A900"]},
}


def native() -> str:
    """The theme Streamlit itself is showing right now (follows the OS unless the user picked one in Streamlit's own menu)."""
    try:
        t = st.context.theme.get("type")
    except Exception:  # noqa: BLE001  not running inside a Streamlit page
        t = None
    return t if t in ("light", "dark") else "light"


def preference() -> str:
    pref = st.session_state.get("_theme_pref")
    if pref not in MODES:
        pref = None
        try:
            pref = st.query_params.get("theme")                   # an explicit link wins ...
        except Exception:  # noqa: BLE001
            pass
        if pref not in MODES:
            try:
                pref = st.context.cookies.get(COOKIE)              # ... then the choice remembered in this browser ...
            except Exception:  # noqa: BLE001
                pref = None
        pref = pref if pref in MODES else "system"                 # ... and new visitors follow their device
        st.session_state["_theme_pref"] = pref
    return pref


def device() -> str:
    """The device's appearance right now. The browser reports it live (see `_bridge`); until it has, Streamlit's own reading is used."""
    v = st.session_state.get("theme_dev")
    return v if v in ("light", "dark") else native()


def effective() -> str:
    p = preference()
    return device() if p == "system" else p


def set_preference(mode: str) -> None:
    st.session_state["_theme_pref"] = mode
    try:
        st.query_params["theme"] = mode
    except Exception:  # noqa: BLE001
        pass


class _Chart:
    """Chart colours of the current theme, read when used (never cached at import)."""

    def _c(self) -> dict:
        return CHART[effective()]

    navy = property(lambda s: s._c()["navy"])
    amber = property(lambda s: s._c()["amber"])
    grey = property(lambda s: s._c()["grey"])
    blue = property(lambda s: s._c()["blue"])
    series = property(lambda s: s._c()["series"])
    ramp = property(lambda s: s._c()["ramp"])
    text = property(lambda s: PALETTES[effective()]["text"])
    muted = property(lambda s: PALETTES[effective()]["muted"])


K = _Chart()


def style_chart(chart):
    """Make an Altair chart readable in the current theme: transparent background, theme-coloured axes, legends and grid."""
    p = PALETTES[effective()]
    return (chart.configure(background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelColor=p["muted"], titleColor=p["muted"], gridColor=p["grid"], domainColor=p["border"], tickColor=p["border"])
            .configure_legend(labelColor=p["text"], titleColor=p["muted"])
            .configure_title(color=p["text"]))


def show(chart, **kw):
    """st.altair_chart with the theme applied (Streamlit's own chart theme is switched off: it would follow Streamlit's theme, not ours)."""
    st.altair_chart(style_chart(chart), theme=None, **kw)


def css() -> str:
    mode, nat = effective(), native()          # native widgets follow Streamlit's own theme: invert them when ours differs
    p = PALETTES[mode]
    v = "\n".join(f"--{k.replace('_', '-')}:{val};" for k, val in p.items())
    invert = "[data-testid='stDataFrame'], [data-testid='stTable'] { filter: invert(.92) hue-rotate(180deg); }" if mode != nat else ""
    return f"""<style>
:root {{ {v} color-scheme: {mode}; }}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: var(--bg) !important; }}
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{ background: var(--bg) !important; }}
[data-testid="stHeader"] {{ background: var(--header-bg) !important; backdrop-filter: blur(6px); }}
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, var(--sb-bg) 0%, var(--sb-bg2) 100%) !important; border-right: 1px solid var(--sb-border); }}
/* text colour: only inside markdown, widget labels and checkbox/radio/toggle labels, never inside buttons or tags; :where() = zero specificity, so every
   component's own colour (KPI value, pill, hero, primary button ...) still wins */
:where([data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] :is(p, li, h1, h2, h3, h4, h5, h6, strong, em, td, th, span):not(button *):not([data-testid="stSidebar"] *)) {{ color: var(--text); }}
:where([data-testid="stAppViewContainer"] [data-testid="stWidgetLabel"] :is(p, span, label):not([data-testid="stSidebar"] *)) {{ color: var(--text); }}
:where([data-testid="stAppViewContainer"] :is([data-testid="stCheckbox"], [data-testid="stRadio"], [data-testid="stToggle"]) :is(p, span, label):not([data-testid="stSidebar"] *)) {{ color: var(--text); }}
[data-testid="stAppViewContainer"] .stButton > button[kind="primary"] *, [data-testid="stAppViewContainer"] .stFormSubmitButton > button[kind="primaryFormSubmit"] * {{ color: var(--bg) !important; }}
[data-testid="stAppViewContainer"] [data-testid="stCaptionContainer"], [data-testid="stAppViewContainer"] [data-testid="stCaptionContainer"] p, [data-testid="stAppViewContainer"] small {{ color: var(--muted) !important; }}
.sm-hero, .hm-sup {{ background: linear-gradient(100deg, var(--hero-from), var(--hero-to)) !important; border-left-color: var(--amber) !important; }}
[data-testid="stAppViewContainer"] .sm-hero h2, [data-testid="stAppViewContainer"] .sm-hero h2 *, [data-testid="stAppViewContainer"] .sm-hero p, [data-testid="stAppViewContainer"] .sm-hero p * {{ color: var(--on-hero) !important; }}
[data-testid="stAppViewContainer"] .sm-kpi .v, [data-testid="stAppViewContainer"] .sm-card h4, [data-testid="stAppViewContainer"] .sm-chip {{ color: var(--brand); }}
[data-testid="stAppViewContainer"] .sm-kpi .l, [data-testid="stAppViewContainer"] .sm-card p {{ color: var(--muted); }}
[data-testid="stAppViewContainer"] .sm-kpi .s, [data-testid="stAppViewContainer"] .sm-sec, [data-testid="stAppViewContainer"] .sm-foot {{ color: var(--subtle); }}
[data-testid="stAppViewContainer"] .sm-note, [data-testid="stAppViewContainer"] .sm-note b {{ color: var(--note-text); }}
[data-testid="stAppViewContainer"] [data-baseweb="input"], [data-testid="stAppViewContainer"] [data-baseweb="base-input"], [data-testid="stAppViewContainer"] [data-baseweb="input"] > div,
[data-testid="stAppViewContainer"] [data-baseweb="textarea"], [data-testid="stAppViewContainer"] [data-baseweb="textarea"] > div, [data-testid="stAppViewContainer"] [data-baseweb="select"] > div,
[data-testid="stAppViewContainer"] [data-baseweb="select"] > div > div, [data-testid="stAppViewContainer"] [data-testid="stNumberInputContainer"], [data-testid="stAppViewContainer"] [data-testid="stChatInput"],
[data-testid="stAppViewContainer"] [data-testid="stChatInput"] > div {{ background: var(--input) !important; border-color: var(--border) !important; }}
[data-testid="stAppViewContainer"] [data-testid$="RootElement"], [data-testid="stAppViewContainer"] [data-testid="stSelectbox"] [role="group"], [data-testid="stAppViewContainer"] [data-testid="stMultiSelect"] [role="group"],
[data-testid="stAppViewContainer"] [data-testid="stDateInput"] [role="group"], [data-testid="stAppViewContainer"] [data-testid="stNumberInput"] [role="group"] {{ background: var(--input) !important; border-color: var(--border) !important; }}
[data-testid="stAppViewContainer"] input, [data-testid="stAppViewContainer"] textarea {{ background: transparent !important; }}
[data-testid="stToolbar"], [data-testid="stToolbar"] button, [data-testid="stToolbar"] span, [data-testid="stToolbar"] svg {{ color: var(--muted) !important; fill: var(--muted); }}
[data-testid="stAppViewContainer"] input, [data-testid="stAppViewContainer"] textarea {{ color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; }}
[data-testid="stAppViewContainer"] input::placeholder, [data-testid="stAppViewContainer"] textarea::placeholder {{ color: var(--subtle) !important; -webkit-text-fill-color: var(--subtle) !important; }}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] ul, [data-baseweb="menu"] {{ background: var(--surface) !important; }}
[data-baseweb="popover"] li, [data-baseweb="popover"] [role="option"], [data-baseweb="menu"] li {{ color: var(--text) !important; background: var(--surface) !important; }}
[data-baseweb="popover"] li:hover, [data-baseweb="popover"] [role="option"]:hover, [data-baseweb="popover"] [aria-selected="true"] {{ background: var(--surface2) !important; }}
[data-testid="stAppViewContainer"] [data-baseweb="tag"] {{ background: var(--surface2) !important; }}
[data-testid="stAppViewContainer"] :is(button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"], [data-testid="stDownloadButton"] button:not([data-testid$="primary"])) {{
    background: var(--surface) !important; color: var(--text) !important; border: 1px solid var(--border) !important; }}
[data-testid="stAppViewContainer"] :is(button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"]) :is(p, span) {{ color: var(--text) !important; }}
[data-testid="stAppViewContainer"] :is(button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"]):hover {{ background: var(--surface2) !important; border-color: var(--amber) !important; }}
[data-testid="stAppViewContainer"] :is(button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"]) {{ background: var(--brand) !important; color: var(--bg) !important; border: 0 !important; }}
[data-testid="stAppViewContainer"] :is(button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"]) :is(p, span) {{ color: var(--bg) !important; }}
[data-testid="stAppViewContainer"] button[data-testid="stBaseButton-tertiary"] :is(p, span) {{ color: var(--muted) !important; }}
.sm-kpi, .sm-card, [data-testid="stChatMessage"], [data-testid="stExpander"], [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] {{ background: var(--surface); border-color: var(--border); box-shadow: 0 1px 2px var(--shadow); }}
[data-testid="stExpander"] details, [data-testid="stExpander"] summary {{ background: var(--surface) !important; }}
[data-testid="stExpander"] summary:hover {{ background: var(--surface2) !important; }}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {{ color: var(--text) !important; }}
.sm-note {{ background: var(--note-bg); }}
.sm-chip, .stTabs [aria-selected="true"] {{ background: var(--surface2); }}
.stTabs [aria-selected="true"], .stTabs [aria-selected="true"] p {{ color: var(--brand) !important; }}
.stTabs [data-baseweb="tab"] p {{ color: var(--muted); }}
.stTabs [data-baseweb="tab-list"], .sm-foot {{ border-color: var(--border); }}
.sm-pill.ok {{ background: var(--ok-bg); color: var(--ok-fg); }} .sm-pill.warn {{ background: var(--warn-bg); color: var(--warn-fg); }}
.sm-pill.bad {{ background: var(--bad-bg); color: var(--bad-fg); }} .sm-pill.info {{ background: var(--info-bg); color: var(--info-fg); }}
[data-testid="stAppViewContainer"] [data-testid="stAlert"], [data-testid="stAppViewContainer"] [data-testid="stAlertContainer"] {{ background: var(--surface2) !important; border: 1px solid var(--border); }}
[data-testid="stAppViewContainer"] [data-testid="stAlert"] p, [data-testid="stAppViewContainer"] [data-testid="stAlert"] span {{ color: var(--text) !important; }}
[data-testid="stAppViewContainer"] code, [data-testid="stAppViewContainer"] pre {{ background: var(--code) !important; color: var(--text) !important; }}
[data-testid="stAppViewContainer"] [data-testid="stFileUploaderDropzone"] {{ background: var(--surface) !important; border-color: var(--border) !important; }}
[data-testid="stAppViewContainer"] [data-testid="stProgress"] p {{ color: var(--muted) !important; }}
[data-testid="stAppViewContainer"] hr {{ border-color: var(--border) !important; }}
{invert}
/* theme selector (sidebar footer): compact segmented control */
.st-key-theme_row {{ margin: 0; }}
.st-key-theme_row [data-testid="stWidgetLabel"] p, .st-key-theme_row .sb-themecap {{ color: var(--sb-muted) !important; font-size: .68rem; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; margin: 0; }}
.st-key-theme_seg {{ width: 100%; }}
.st-key-theme_seg [data-testid="stButtonGroup"] {{ width: 100%; flex-wrap: nowrap; gap: 2px; background: rgba(255,255,255,.06); border-radius: 9px; padding: 2px; }}
.st-key-theme_seg button {{ flex: 1 1 auto; min-width: max-content; min-height: 1.8rem; padding: .1rem .15rem; border: 0 !important; background: transparent !important; color: var(--sb-text) !important; border-radius: 7px; box-shadow: none !important; }}
.st-key-theme_seg button p, .st-key-theme_seg button span {{ color: inherit !important; font-size: .66rem !important; white-space: nowrap; overflow: visible !important; text-overflow: clip !important; letter-spacing: -.01em; }}
.st-key-theme_seg button:hover {{ background: var(--sb-hover) !important; }}
.st-key-theme_seg button[aria-checked="true"], .st-key-theme_seg button[aria-pressed="true"], .st-key-theme_seg button[data-testid="stBaseButton-segmented_controlActive"] {{ background: var(--sb-active) !important; color: var(--sb-accent) !important; box-shadow: inset 0 0 0 1px rgba(242,169,0,.55) !important; font-weight: 700; }}
.st-key-theme_seg button:focus-visible {{ outline: 2px solid var(--sb-accent); outline-offset: 1px; }}
.st-key-theme_row [data-testid="stElementContainer"]:has(iframe), .st-key-theme_dev {{ display: none !important; }}
</style>"""


def apply() -> None:
    """Inject the theme. Call once per run, after login, before any page content."""
    st.markdown(css(), unsafe_allow_html=True)


LABELS = {"light": ("Light", ":material/light_mode:", "Always light, whatever your device is set to."),
          "dark": ("Dark", ":material/dark_mode:", "Always dark, whatever your device is set to."),
          "system": ("Match Device", ":material/desktop_windows:", "Follows your device's appearance (light or dark) and changes with it.")}


def _on_pick() -> None:
    v = st.session_state.get("theme_seg")
    if v in MODES:                      # clicking the active segment deselects it: ignore, one option is always selected
        set_preference(v)


def _bridge(pref: str) -> None:
    """Zero-height script frame (same origin as the app): remembers the manual choice in a cookie so a new session or browser restart keeps it,
    and puts explanatory tooltips on the three segments. It never stores or sends anything else."""
    tips = {m: LABELS[m][2] for m in MODES}
    import json
    st.iframe(f"""<html><body><script>
(function () {{
  var pref = {json.dumps(pref)}, tips = {json.dumps([tips[m] for m in MODES])}, p = window.parent;
  try {{ p.document.cookie = "{COOKIE}=" + pref + "; path=/; max-age=31536000; SameSite=Lax"; }} catch (e) {{}}
  function tip() {{ try {{ var b = p.document.querySelectorAll(".st-key-theme_seg button[aria-checked]"); for (var i = 0; i < b.length && i < 3; i++) {{ b[i].title = tips[i]; }} }} catch (e) {{}} }}
  tip(); try {{ new MutationObserver(tip).observe(p.document.body, {{childList: true, subtree: true}}); }} catch (e) {{}}
  if (pref !== "system") return;
  /* Match Device: tell the app the device's appearance now and whenever it changes (the app re-draws; nothing reloads, so no state is lost) */
  var mq = p.matchMedia("(prefers-color-scheme: dark)");
  function report() {{
    try {{
      var v = mq.matches ? "dark" : "light", inp = p.document.querySelector(".st-key-theme_dev input");
      if (!inp || inp.value === v) return;
      Object.getOwnPropertyDescriptor(p.HTMLInputElement.prototype, "value").set.call(inp, v);
      inp.dispatchEvent(new Event("input", {{bubbles: true}}));
      inp.dispatchEvent(new KeyboardEvent("keydown", {{key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true}}));
      inp.dispatchEvent(new FocusEvent("focusout", {{bubbles: true}}));
    }} catch (e) {{}}
  }}
  if (mq.addEventListener) mq.addEventListener("change", report); else if (mq.addListener) mq.addListener(report);
  report(); setTimeout(report, 400); setTimeout(report, 1500);
  setInterval(report, 1000);      /* fallback for browsers or embeddings that do not fire the change event; reading one boolean per second is free */
}})();
</script></body></html>""", height=1)


def switcher() -> None:
    """Compact 'Light | Dark | Match Device' segmented control for the sidebar footer, with the current device appearance when following it."""
    pref = preference()
    st.session_state["theme_seg"] = pref
    # Start from the appearance Streamlit already reports for this device. The browser probe below only writes the box when the device differs
    # from it, so on a normal login it writes nothing: an empty box used to be filled right after login, which forced a SECOND script run
    # while the first page was still being built (the cause of the visible hand-over flicker).
    if st.session_state.get("theme_dev") not in ("light", "dark"):
        st.session_state["theme_dev"] = native()
    with st.container(key="theme_row"):
        st.segmented_control("Theme" if pref != "system" else f"Theme · device is {device()}", list(MODES), key="theme_seg", format_func=lambda m: f"{LABELS[m][1]} {LABELS[m][0]}", on_change=_on_pick,
                             label_visibility="visible", width="stretch", help="Light, Dark, or follow this device. Your choice is remembered in this browser.")
        st.text_input("device appearance", key="theme_dev", label_visibility="collapsed")      # filled by the browser script, never by the user
        _bridge(pref)
