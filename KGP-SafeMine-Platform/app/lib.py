"""Shared helpers for the multi-page UI: theme, agent, data access, review queue, report export."""
from __future__ import annotations

import io
import json
import re
import sqlite3
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
import streamlit as st  # noqa: E402

from safemine import config  # noqa: E402

NAVY, AMBER, SLATE = "#0B2545", "#F2A900", "#13315C"
UPLOADS = config.OUT / "uploads"
LABELS = {"upgrad": "Qwen3-8B (default)", "openai": "OpenAI", "gemini": "Google Gemini", "anthropic": "Anthropic Claude",
          "groq": "Groq gpt-oss-20b (testing)"}
KEY_ENV = {"upgrad": "UPGRAD_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "groq": "GROQ_API_KEY"}
MODEL_ENV = {"upgrad": "UPGRAD_MODEL", "openai": "OPENAI_MODEL", "gemini": "GEMINI_MODEL", "anthropic": "ANTHROPIC_MODEL", "groq": "GROQ_MODEL"}
ENV_PATH = config.ROOT / ".env"
STATUS_BADGE = {"answered": ("ANSWERED", "ok"), "abstained": ("ABSTAINED · insufficient evidence", "warn"),
                "refused": ("REFUSED · out of policy", "bad")}

CSS = f"""
<style>
:root {{ --navy:{NAVY}; --amber:{AMBER}; --slate:{SLATE}; --bg:#F6F8FB; --surface:#FFFFFF; --surface2:#EEF2F8; --border:#E2E8F0; --text:#1B2A3D;
        --muted:#5B6B80; --subtle:#7A8798; --brand:{NAVY}; --note-bg:#FFF8E1; --note-text:#4A3B00; --shadow:rgba(11,37,69,.05);
        --ok-bg:#DCFCE7; --ok-fg:#166534; --warn-bg:#FEF3C7; --warn-fg:#92400E; --bad-bg:#FEE2E2; --bad-fg:#991B1B; --info-bg:#DBEAFE; --info-fg:#1E40AF;
        --sb-bg:{NAVY}; --sb-bg2:{SLATE}; --sb-text:#C9D6EA; --sb-strong:#FFFFFF; --sb-muted:#8FA6C8; --sb-border:rgba(255,255,255,.14); --sb-hover:rgba(255,255,255,.08); --sb-active:rgba(242,169,0,.16); --sb-accent:{AMBER};
        --hero-from:{NAVY}; --hero-to:{SLATE}; --on-hero:#FFFFFF; --on-amber:{NAVY}; --header-bg:transparent; }}
.block-container {{ padding-top: 1.2rem; max-width: 1280px; }}
[data-testid="stSidebar"] {{ background: linear-gradient(180deg,var(--sb-bg) 0%,var(--sb-bg2) 100%); }}
[data-testid="stSidebar"] * {{ color: var(--sb-text); }}
[data-testid="stSidebar"] [data-baseweb="input"] input, [data-testid="stSidebar"] textarea {{ color:#111; }}
.sm-brand {{ display:flex; flex-direction:column; align-items:center; gap:.45rem; padding:.2rem 0 .8rem 0; border-bottom:1px solid rgba(255,255,255,.18); margin-bottom:.6rem; }}
.sm-brand img.sm-logo {{ width:118px; height:auto; filter: drop-shadow(0 4px 10px rgba(0,0,0,.35)); }}
.sm-brand .tag {{ font-size:.68rem; opacity:.8; letter-spacing:.06em; text-transform:uppercase; text-align:center; }}
.sm-hero {{ background:linear-gradient(100deg,var(--hero-from),var(--hero-to)); color:var(--on-hero); border-radius:12px; padding:1.1rem 1.4rem; margin-bottom:1rem;
           border-left:6px solid var(--amber); }}
.sm-hero h2 {{ margin:0; color:var(--on-hero); font-size:1.5rem; }}
.sm-hero p {{ margin:.25rem 0 0 0; opacity:.85; font-size:.92rem; }}
.sm-kpi {{ background:var(--surface); border:1px solid var(--border); border-top:4px solid var(--amber); border-radius:10px; padding:.7rem 1rem; box-sizing:border-box; width:100%; height:112px; display:flex; flex-direction:column; justify-content:center; overflow:hidden; }}
.sm-kpi .v {{ font-size:1.55rem; font-weight:800; color:var(--brand); line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.sm-kpi .v.m {{ font-size:1.15rem; line-height:1.3; }}
.sm-kpi .v.x {{ font-size:.95rem; line-height:1.25; white-space:normal; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }}
.sm-kpi .l {{ font-size:.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.sm-kpi .s {{ font-size:.75rem; color:var(--subtle); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
[data-testid="stColumn"]:has(.sm-kpi) {{ min-width:0 !important; flex:1 1 0 !important; }}
.sm-pill {{ display:inline-block; padding:.15rem .6rem; border-radius:999px; font-size:.75rem; font-weight:700; }}
.sm-pill.ok {{ background:var(--ok-bg); color:var(--ok-fg); }} .sm-pill.warn {{ background:var(--warn-bg); color:var(--warn-fg); }}
.sm-pill.bad {{ background:var(--bad-bg); color:var(--bad-fg); }} .sm-pill.info {{ background:var(--info-bg); color:var(--info-fg); }}
.sm-note {{ background:var(--note-bg); border-left:4px solid var(--amber); padding:.6rem .9rem; border-radius:6px; font-size:.85rem; color:var(--note-text); }}
.sm-foot {{ color:var(--subtle); font-size:.72rem; margin-top:2rem; border-top:1px solid var(--border); padding-top:.5rem; }}
.sm-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1rem 1.1rem; height:100%; box-shadow:0 1px 2px var(--shadow); }}
.sm-card h4 {{ margin:.1rem 0 .3rem 0; color:var(--brand); font-size:1rem; }}
.sm-card p {{ margin:0; color:var(--muted); font-size:.85rem; }}
.sm-card .ic {{ font-size:1.4rem; }}
.sm-chip {{ display:inline-block; background:var(--surface2); color:var(--brand); border-radius:6px; padding:.1rem .5rem; font-size:.72rem; margin-right:.3rem; }}
.sm-sec {{ font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; color:var(--subtle); font-weight:700; margin:1rem 0 .3rem 0; }}
.stTabs [data-baseweb="tab-list"] {{ gap:.25rem; border-bottom:1px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{ border-radius:8px 8px 0 0; padding:.45rem 1rem; font-weight:600; }}
.stTabs [aria-selected="true"] {{ background:var(--surface2); color:var(--brand); }}
.stButton>button[kind="primary"] {{ background:{NAVY}; border:0; color:#fff; font-weight:700; }}
.stButton>button[kind="primary"]:hover {{ background:{SLATE}; }}
.stButton>button {{ border-radius:8px; }}
[data-testid="stChatMessage"] {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:.8rem 1rem; }}
[data-testid="stExpander"] {{ border-radius:10px; border:1px solid var(--border); background:var(--surface); }}
</style>
"""


def theme():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, sub: str):
    st.markdown(f'<div class="sm-hero"><h2>{title}</h2><p>{sub}</p></div>', unsafe_allow_html=True)


def kpi(col, label: str, value, sub: str = ""):
    """Fixed-size metric card: same height and width everywhere; long text is cut with an ellipsis (full text on hover)."""
    from html import escape
    v, l, sb = escape(str(value)), escape(str(label)), escape(str(sub))
    cls = "" if len(str(value)) <= 13 else (" m" if len(str(value)) <= 20 else " x")   # long text gets a smaller font instead of a wider card
    col.markdown(f'<div class="sm-kpi" title="{l}: {v}{" · " + sb if sb else ""}"><div class="l">{l}</div><div class="v{cls}">{v}</div>'
                 f'<div class="s">{sb or "&nbsp;"}</div></div>', unsafe_allow_html=True)


def card(col, icon: str, title: str, body: str):
    col.markdown(f'<div class="sm-card"><div class="ic">{icon}</div><h4>{title}</h4><p>{body}</p></div>', unsafe_allow_html=True)


def section(text: str):
    st.markdown(f'<div class="sm-sec">{text}</div>', unsafe_allow_html=True)


def pill(text: str, kind: str = "info") -> str:
    return f'<span class="sm-pill {kind}">{text}</span>'


def footer():
    st.markdown('<div class="sm-foot">KGP-SafeMine · decision support over public MSHA data and 30 CFR. Not an investigator, '
                'not legal advice. Every answer needs human review before use.</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ start-up preload
_PRELOAD = {"started": False}


def preload() -> None:
    """While the login screen is on show, import the heavy libraries and start loading the search index in a background thread, so the first
    page after login does not pay for them (about 3 s of imports, plus the index). Runs once per server process; never blocks a page."""
    if _PRELOAD["started"]:
        return
    _PRELOAD["started"] = True

    def _go():
        try:
            time.sleep(1.0)                                   # let the login page paint first
            import altair, duckdb, openai, pandas  # noqa: F401
            from safemine.agent import orchestrator  # noqa: F401
            from safemine.tools.hybrid_search import warmup
            warmup()
            from app import meta
            meta.data_facts()                                 # the Home page's figures, cached before anyone has logged in
        except Exception:  # noqa: BLE001  preloading is an optimisation only
            pass
    import threading
    threading.Thread(target=_go, name="preload", daemon=True).start()


# ------------------------------------------------------------------ agent + data
@st.cache_resource(show_spinner="Loading retrieval indexes and models …")
def get_agent():
    from safemine.agent.orchestrator import Agent
    from safemine.tools.hybrid_search import warmup
    warmup()   # indexes and models load in the background while the user types the first question
    return Agent()


@st.cache_resource
def _db():
    import duckdb
    return duckdb.connect(str(config.DUCKDB_PATH), read_only=True)


@st.cache_data(ttl=600, show_spinner="Loading data …")
def sql(q: str, params: tuple = ()):
    return _db().execute(q, list(params)).fetchdf()


def ops_db() -> sqlite3.Connection:
    return get_agent().store.db


def ready() -> bool:
    return config.llm_configured()


def ask(query: str, session_id: str, mode: str = "grounded") -> dict:
    """mode="grounded": evidence-only agent (default). mode="general": the same agent first, then a labelled general-knowledge answer
    for general safety questions the records do not cover (safemine/agent/general.py)."""
    if mode == "general":
        from safemine.agent import general
        return general.answer(get_agent(), query, session_id)
    return get_agent().run(query, session_id=session_id)


def render_result(r: dict, key: str, show_trace: bool = False, review: bool = True):
    label, kind = STATUS_BADGE.get(r["status"], (r["status"].upper(), "info"))
    u = r["usage"]
    st.markdown(f"{pill(label, kind)} &nbsp; <span style='color:var(--muted);font-size:.8rem'>{r['latency_s']} s · {r['tool_calls']} tool calls · "
                f"{u['llm_calls']} LLM calls · {u['prompt_tokens'] + u['completion_tokens']} tokens"
                f"</span>", unsafe_allow_html=True)
    if r.get("general_knowledge"):
        st.info("💬 **General knowledge, not from the MSHA records.** The records search found no evidence for this question, so this answer "
                "comes from the model's general knowledge and is **not verified** against any source. Check it before relying on it.")
    st.markdown(r["answer"])
    _inj = [e for e in r.get("trace", []) if e.get("kind") == "injection_in_evidence"]
    if _inj:   # retrieved documents contained text that tried to give the assistant orders
        st.warning(f"🛡️ {sum(e.get('removed', 1) for e in _inj)} instruction-like passage(s) in {len(_inj)} retrieved document(s) were removed before "
                   "the model read them. Treat those sources with caution: " + ", ".join(f"[{e['evidence']}]" for e in _inj))
    try:   # statistics answers: charts, KPIs and computed insights from the exact rows the answer used
        from app import stats_view
        if r["status"] == "answered":     # no confident charts under an abstention or refusal
            stats_view.render_stats(r, key)
    except Exception as e:  # noqa: BLE001  a chart problem must never hide the answer
        st.caption(f"(analytics panel unavailable: {type(e).__name__})")
    v = r.get("verification")
    if v:
        st.progress(min(1.0, v["support_ratio"]), text=f"Claim support {v['support_ratio']:.0%} (verified in code against the evidence)")
    try:   # claim-by-claim verification and the agents that produced the answer (multi-agent layer)
        from app import agent_view
        if r["status"] == "answered":
            agent_view.render_verification(r)
        agent_view.render_agent_trail(r)
    except Exception as e:  # noqa: BLE001  a display problem must never hide the answer
        st.caption(f"(verification detail unavailable: {type(e).__name__})")
    ev = r.get("evidence", [])
    if ev:
        with st.expander(f"Evidence ({len(ev)} items)"):
            for e in ev:
                st.markdown(f"**[{e['id']}] {e['label']}**")
                st.caption(e["text"][:1500])
    if review and r["status"] == "answered":
        c = st.columns([1, 1, 1, 4])
        for col, d in zip(c, ("approve", "flag", "reject")):
            if col.button(d.title(), key=f"{key}_{d}"):
                get_agent().store.set_review(r["turn_id"], d)
                st.toast(f"Review recorded: {d}")
    if r.get("turn_id"):
        st.session_state["last_turn_id"] = r["turn_id"]   # Settings links to the trace of the last question
        try:
            from safemine import tracing
            if tracing.enabled():
                url = tracing.trace_url(r["turn_id"])
                if url:
                    st.caption(f"[View this question's trace in Langfuse]({url})")
        except Exception:  # noqa: BLE001  a tracing problem must never hide the answer
            pass
    if show_trace:
        with st.expander("Agent trace"):
            st.json(r["trace"])


# ------------------------------------------------------------------ settings persistence
def save_env(updates: dict) -> None:
    if not ENV_PATH.exists():
        ex = config.ROOT / ".env.example"
        ENV_PATH.write_text(ex.read_text() if ex.exists() else "")
    lines = ENV_PATH.read_text().splitlines()
    for k, v in updates.items():
        for i, ln in enumerate(lines):
            if re.match(rf"^\s*{k}\s*=", ln):
                lines[i] = f"{k}={v}"
                break
        else:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


# ------------------------------------------------------------------ report export
def _clean_md(t: str) -> str:
    return re.sub(r"[*_`]", "", t)


def _latin(t: str) -> str:
    return t.encode("latin-1", "replace").decode("latin-1")


def report_docx(title: str, r: dict, meta: dict) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor
    d = Document()
    h = d.add_heading(title, 0)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0x0B, 0x25, 0x45)
    p = d.add_paragraph(f"Status: {meta['stage']}   ·   Generated {meta['when']}   ·   Reviewer decision: {meta['review']}")
    p.runs[0].font.size = Pt(9)
    d.add_paragraph("Prepared by KGP-SafeMine (decision support). Not an official investigation and not legal advice.").runs[0].italic = True
    for line in r["answer"].splitlines():
        s = line.rstrip()
        if not s:
            continue
        if s.startswith("## "):
            d.add_heading(s[3:], 2)
        elif s.startswith("# "):
            d.add_heading(s[2:], 1)
        elif s.startswith(("- ", "* ")):
            d.add_paragraph(_clean_md(s[2:]), style="List Bullet")
        elif s.startswith(">"):
            d.add_paragraph(_clean_md(s.lstrip("> ")), style="Intense Quote")
        else:
            d.add_paragraph(_clean_md(s))
    d.add_heading("Evidence", 2)
    for e in r.get("evidence", []):
        para = d.add_paragraph(style="List Number")
        para.add_run(f"[{e['id']}] {e['label']}. ").bold = True
        para.add_run(e["text"][:500].replace("\n", " "))
    v = r.get("verification")
    if v:
        d.add_paragraph(f"Claim support verified in code: {v['support_ratio']:.0%}.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def report_pdf(title: str, r: dict, meta: dict) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_fill_color(11, 37, 69)
    pdf.rect(0, 0, 210, 22, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_xy(10, 7)
    pdf.cell(0, 8, _latin(title))
    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(10, 26)
    pdf.multi_cell(190, 4, _latin(f"Status: {meta['stage']}  |  Generated {meta['when']}  |  Reviewer decision: {meta['review']}\n"
                                  "Prepared by KGP-SafeMine (decision support). Not an official investigation and not legal advice."))
    pdf.ln(3)
    for line in r["answer"].splitlines():
        s = line.rstrip()
        if not s:
            pdf.ln(2)
            continue
        pdf.set_x(10)
        if s.startswith("#"):
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(11, 37, 69)
            pdf.multi_cell(190, 7, _latin(s.lstrip("# ")))
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(190, 5, _latin(("  - " + _clean_md(s[2:])) if s.startswith(("- ", "* ")) else _clean_md(s.lstrip("> "))))
    pdf.ln(3)
    pdf.set_x(10)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(11, 37, 69)
    pdf.cell(0, 7, "Evidence", ln=1)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(60, 60, 60)
    for e in r.get("evidence", []):
        pdf.set_x(10)
        pdf.multi_cell(190, 4, _latin(f"[{e['id']}] {e['label']}: " + e["text"][:350].replace("\n", " ")))
        pdf.ln(1)
    return bytes(pdf.output())


def review_of(turn_id: str) -> str:
    row = ops_db().execute("SELECT review FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
    return row[0] if row else "pending"


def read_upload_text(f) -> str:
    name = f.name.lower()
    data = f.getvalue()
    if name.endswith((".txt", ".md", ".csv")):
        return data.decode("utf-8", "ignore")
    if name.endswith(".docx"):
        from docx import Document
        return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    if name.endswith(".pdf"):
        import pymupdf
        return "\n".join(pg.get_text() for pg in pymupdf.open(stream=data, filetype="pdf"))
    return ""


def now_str() -> str:
    return datetime.now().strftime("%d %b %Y %H:%M")
