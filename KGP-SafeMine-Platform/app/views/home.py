import json
from html import escape
from pathlib import Path

import streamlit as st

from app import lib, meta

DISCLAIMER = ("KGP-SafeMine is an AI-assisted mining safety intelligence and decision-support system. Its outputs are intended to support, "
              "not replace, qualified investigators, mining safety professionals, regulatory experts, or authorised human decision-makers.")

CSS = """
<style>
.hm-lead { color: var(--muted); font-size: 1.02rem; line-height: 1.6; max-width: 52rem; margin: .1rem 0 .7rem 0; }
.hm-chips { display: flex; flex-wrap: wrap; gap: .5rem; }
.hm-chip { background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: .28rem .8rem; font-size: .8rem; font-weight: 600; color: var(--brand); }
.hm-chip i { font-style: normal; color: var(--amber); font-weight: 800; margin-right: .4rem; }
.hm-h { font-size: 1.12rem; font-weight: 800; color: var(--brand); margin: 1.7rem 0 .2rem 0; display: flex; align-items: center; gap: .55rem; }
.hm-h::before { content: ""; width: 4px; height: 1.1rem; background: var(--amber); border-radius: 2px; }
.hm-sub { color: var(--muted); font-size: .86rem; margin: 0 0 .8rem 0; max-width: 60rem; line-height: 1.55; }
.hm-grid { display: grid; gap: .8rem; }
.hm-g3 { grid-template-columns: repeat(3, minmax(0, 1fr)); } .hm-g4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
@media (max-width: 1000px) { .hm-g3, .hm-g4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .hm-g3, .hm-g4 { grid-template-columns: minmax(0, 1fr); } }
.hm-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: .95rem 1.05rem; box-shadow: 0 1px 2px var(--shadow); }
[data-testid="stMain"] .hm-card h4 { margin: 0 0 .25rem 0; padding: 0; font-size: .95rem; color: var(--brand); line-height: 1.3; }
.hm-card p { margin: 0; color: var(--muted); font-size: .83rem; line-height: 1.5; }
.hm-act { min-height: 10rem; border-top: 4px solid var(--amber); }
.hm-act .ic { font-size: 1.5rem; line-height: 1; margin-bottom: .55rem; }
.hm-stat { font-size: 1.4rem; font-weight: 800; color: var(--brand); line-height: 1.15; }
.hm-meta { font-size: .74rem; color: var(--subtle); margin-top: .35rem; line-height: 1.45; }
.hm-tag { display: inline-block; font-size: .64rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; border-radius: 999px; padding: .08rem .5rem; margin: 0 .25rem .35rem 0; }
.hm-tag.llm { background: var(--info-bg); color: var(--info-fg); } .hm-tag.code { background: var(--surface2); color: var(--brand); }
.hm-tag.human { background: var(--warn-bg); color: var(--warn-fg); } .hm-tag.ok { background: var(--ok-bg); color: var(--ok-fg); }
.hm-tag.no { background: var(--bad-bg); color: var(--bad-fg); }
.hm-flow { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: .5rem; margin-bottom: .9rem; }
@media (max-width: 1100px) { .hm-flow { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 640px) { .hm-flow { grid-template-columns: minmax(0, 1fr); } }
.hm-step { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: .75rem .5rem; text-align: center; }
.hm-step i { display: inline-flex; width: 1.7rem; height: 1.7rem; border-radius: 50%; background: var(--amber); color: var(--on-amber); font-style: normal; font-weight: 800;
             font-size: .84rem; align-items: center; justify-content: center; margin-bottom: .4rem; }
.hm-step b { display: block; color: var(--brand); font-size: .8rem; line-height: 1.3; margin-bottom: .2rem; }
.hm-step span { color: var(--muted); font-size: .73rem; line-height: 1.4; display: block; }
.hm-sup { background: linear-gradient(100deg, var(--hero-from), var(--hero-to)); color: var(--on-hero); border-radius: 12px; padding: .8rem 1rem; border-left: 6px solid var(--amber); margin-bottom: .7rem; }
.hm-sup b { color: var(--on-hero); } .hm-sup span { color: var(--on-hero); opacity: .85; font-size: .82rem; }
.hm-disc { background: var(--note-bg); border-left: 4px solid var(--amber); border-radius: 8px; padding: .75rem 1rem; color: var(--note-text); font-size: .84rem; line-height: 1.55; margin-top: 1.6rem; }
.hm-limits { margin: .4rem 0 0 0; padding-left: 1.1rem; color: var(--muted); font-size: .83rem; line-height: 1.7; }
.hm-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: .95rem 1.05rem; box-shadow: 0 1px 2px var(--shadow); text-align: center; min-height: 8.4rem; }
.hm-kpi .val { font-size: 1.85rem; font-weight: 800; color: var(--brand); line-height: 1.15; }
.hm-kpi .lbl { font-size: .84rem; font-weight: 700; color: var(--brand); margin: .15rem 0 .25rem 0; }
.hm-kpi .note { font-size: .75rem; color: var(--muted); line-height: 1.45; }
.hm-about { color: var(--subtle); font-size: .76rem; line-height: 1.55; margin-top: .8rem; text-align: center; }
[data-testid="stMain"] a[data-testid="stPageLink-NavLink"] { justify-content: center; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
[data-testid="stMain"] a[data-testid="stPageLink-NavLink"]:hover { border-color: var(--amber); }
[data-testid="stMain"] a[data-testid="stPageLink-NavLink"], [data-testid="stMain"] a[data-testid="stPageLink-NavLink"]:hover { text-decoration: none !important; }
[data-testid="stMain"] a[data-testid="stPageLink-NavLink"] p { text-decoration: none !important; font-weight: 600; }
[data-testid="stMain"] a[data-testid="stPageLink-NavLink"] span { color: var(--brand) !important; }
</style>
"""


def H(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="hm-h">{title}</div>' + (f'<div class="hm-sub">{sub}</div>' if sub else ""), unsafe_allow_html=True)


def grid(cls: str, cards: list[str]) -> None:
    st.markdown(f'<div class="hm-grid {cls}">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def go(col, page: str, label: str, icon: str) -> None:
    """Link to another page of the app (a plain link when the page registry is absent, e.g. this page run on its own in a test)."""
    try:
        col.page_link(st.session_state["_sm_pages"][page], label=label, icon=icon, use_container_width=True)
    except Exception:  # noqa: BLE001  StreamlitPageNotFoundError outside st.navigation
        col.markdown(f"[{label}](/{page})")


st.markdown(CSS, unsafe_allow_html=True)

# ------------------------------------------------------------------ 1. welcome
lib.hero("Mining Safety Intelligence Platform", "KGP-SafeMine · evidence-grounded decision support for mine accident investigation and regulatory analysis")
st.markdown('<div class="hm-lead">Ask about US mine accidents, their root causes, MSHA statistics and the 30 CFR safety standards. '
            'Answers are built from official records and cite them.</div>'
            '<div class="hm-chips"><span class="hm-chip"><i>✓</i>Cited and checked</span><span class="hm-chip"><i>✓</i>Says when it does not know</span>'
            '<span class="hm-chip"><i>✓</i>A person has the final say</span></div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ 2. where to start
H("What you can do here", "Pick a task to get started.")
START = [("assistant", "💬", "Ask a question", "Root causes, statistics, requirements and similar cases, in plain language.", "Open AI Assistant", ":material/smart_toy:"),
         ("investigation", "🔍", "Investigate an incident", "Draft a brief from similar MSHA investigations and the standards they cited.", "Start investigation", ":material/search:"),
         ("regulatory", "⚖️", "Look up a regulation", "Read the 30 CFR text as it stood on a chosen date, or search by keyword.", "Open 30 CFR lookup", ":material/gavel:"),
         ("dashboard", "📊", "See safety trends", "Fatal accidents by year, type, mine and state, and the most cited standards.", "Open dashboard", ":material/dashboard:")]
for col, (page, ic, title, desc, label, icon) in zip(st.columns(4), START):
    col.markdown(f'<div class="hm-card hm-act"><div class="ic">{ic}</div><h4>{title}</h4><p>{desc}</p></div>', unsafe_allow_html=True)
    go(col, page, label, icon)
st.markdown('<div class="hm-sub" style="margin:.9rem 0 .3rem 0">Also available: manage the evidence, export a DRAFT report, and review answers.</div>', unsafe_allow_html=True)
more = st.columns(3)
go(more[0], "knowledge", "Knowledge Base", ":material/menu_book:")
go(more[1], "reports", "Reports & Export", ":material/description:")
go(more[2], "review", "Human Review Queue", ":material/fact_check:")

# ------------------------------------------------------------------ 3. key numbers (read from the frozen evaluation files)
EVAL = Path(__file__).resolve().parents[2] / "eval"


@st.cache_data(show_spinner=False, ttl=600)
def results() -> dict:
    """Headline numbers, read from the evaluation result files (nothing typed in by hand). Missing files are skipped."""
    out = {}
    try:
        o = json.loads((EVAL / "results" / "test_final.summary.json").read_text())["overall"]
        out["test"] = (o["pass"], o["n"], o["rate"], o.get("ci95"))
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = json.loads((EVAL / "retrieval_results_v2.json").read_text())
        d = next(r for r in rows if r["chunks"] == "section450" and r["retriever"] == "hybrid+rerank")
        out["retrieval"] = (d["R@10"], d["R@1"], d.get("Ev@8_section"), d["n"])
    except Exception:  # noqa: BLE001
        pass
    try:
        c = json.loads((EVAL / "cfr_results_v2.json").read_text())
        out["cfr"] = (sum(1 for x in c if x["ok"]), len(c))
    except Exception:  # noqa: BLE001
        pass
    try:
        per_placement = []   # the same attacks, hidden at the end and in the middle of a document: never add them together
        for f in ("injection_fin_end", "injection_after_mid"):
            rows = json.loads((EVAL / "results" / f"{f}.json").read_text())
            rows = rows["rows"] if isinstance(rows, dict) else rows
            per_placement.append((sum(1 for x in rows if x.get("verdict") == "COMPROMISED"), len(rows)))
        out["injection"] = max(per_placement)   # show the worse of the two
    except Exception:  # noqa: BLE001
        pass
    return out


def kpi(label: str, value: str, note: str) -> str:
    return f'<div class="hm-kpi"><div class="val">{escape(value)}</div><div class="lbl">{escape(label)}</div><div class="note">{escape(note)}</div></div>'


H("Measured results", "Tested with the graded model, Qwen3-8B. Read from the evaluation result files when this page opens.")
M = results()
k = []
if "test" in M:
    p_, n_, rate, ci = M["test"]
    k.append(kpi("Correct on the frozen test", f"{p_} / {n_}", f"{rate:.1%}" + (f" (95% interval {ci[0]:.0%}-{ci[1]:.0%})" if ci else "")
             + "; the model alone got 7-16%."))
if "retrieval" in M:
    r10, r1, ev8, n_ = M["retrieval"]
    k.append(kpi("Right report in top 10", f"{r10:.0%}", f"Across {n_} report questions; ranked first {r1:.0%} of the time."))
if "cfr" in M:
    ok, n_ = M["cfr"]
    k.append(kpi("30 CFR lookups correct", f"{ok} / {n_}", "Exact text, found by section title or by a past date."))
if "injection" in M:
    c_, n_ = M["injection"]
    k.append(kpi("Hidden attacks blocked", f"{n_ - c_} / {n_}",
                 f"We hid {n_} attacks inside documents. {n_ - c_} failed; {c_} fooled the system."))
if k:
    grid("hm-g4", k)
else:
    st.caption("Evaluation result files were not found, so no measured results are shown.")

# ------------------------------------------------------------------ 4. details, one topic per tab
H("Learn more", "Details are grouped by topic. Open only what you need.")
t_flow, t_agents, t_small, t_data, t_limits = st.tabs(["How it works", "Agents", "Small-model design", "Data", "Coverage and limits"])

with t_flow:
    H("How a question is answered")
    FLOW = [("User question", "You ask in plain language."),
            ("Planning", "Decides what evidence is needed."),
            ("Evidence retrieval", "Fetches reports, tables and CFR text."),
            ("Analysis", "Drafts from that evidence only."),
            ("Verification", "Checks each sentence against its source."),
            ("Response / report", "A cited answer, or an abstention."),
            ("Human review", "Approve, flag or reject.")]
    st.markdown('<div class="hm-flow">' + "".join(f'<div class="hm-step"><i>{i}</i><b>{escape(t)}</b><span>{escape(d)}</span></div>'
                                                  for i, (t, d) in enumerate(FLOW, 1)) + "</div>", unsafe_allow_html=True)
    grid("hm-g3", ['<div class="hm-card"><h4>Grounded and cited</h4><p>Statements with an unverified regulation number, quotation, date or figure of two or more digits are removed; other unsupported ones are flagged.</p></div>',
                   '<div class="hm-card"><h4>Abstains when unsure</h4><p>If the evidence is thin or outside the data’s coverage, the system says so rather than answering.</p></div>',
                   '<div class="hm-card"><h4>Drafts until approved</h4><p>AI-generated reports stay drafts until a reviewer approves them in the Human Review Queue.</p></div>'])

with t_agents:
    H("How the agents work together", "Eight agents plus a supervisor: role-specialised components of one application, not separate services, working over an in-process message bus.")
    st.markdown('<div class="hm-sup"><b>Supervisor (orchestrator)</b><br><span>Routes work between the agents, enforces the step and time budgets, and fails closed: '
                'if a step cannot be completed or verified, the answer is withheld or the system abstains.</span></div>', unsafe_allow_html=True)
    AG = [("Safety / policy check", "llm", "LLM + rules", "Refuses out-of-scope requests and ignores instructions hidden in documents."),
          ("Planner", "llm", "LLM", "Plans which sources, standards and dates matter."),
          ("Retrieval", "code", "Code", "Keyword and semantic search over reports, plus SQL tables and accident statistics."),
          ("Regulatory Intelligence", "code", "Code", "Finds the 30 CFR text in force on the relevant date."),
          ("Incident Investigation", "llm", "LLM", "Writes the analysis strictly from the retrieved evidence, with citations."),
          ("Verification (Validator)", "code", "Code", "Checks citations, quotes, dates, CFR sections and numbers of two or more digits."),
          ("Critic", "llm", "LLM", "Reviews the draft: accept, revise or abstain. Low support is never accepted."),
          ("Report Generation", "code", "Code", "Assembles the verified answer; exports DOCX or PDF marked DRAFT."),
          ("Human Review", "human", "Person", "Not an agent: a reviewer approves, flags or rejects each answer.")]
    grid("hm-g4", [f'<div class="hm-card"><span class="hm-tag {c}">{escape(t)}</span><h4>{escape(n)}</h4><p>{escape(d)}</p></div>' for n, c, t, d in AG])
    st.markdown('<div class="hm-sub" style="margin-top:.9rem"><b>Collaboration:</b> the planner decides what is needed; retrieval and regulatory lookup gather the evidence; '
                'the investigation agent drafts from it; verification can send the draft back (a bounded number of rounds); a human reviews the result.</div>'
                '<div class="hm-sub"><span class="hm-tag ok">Implemented</span> all components above, in the multi-agent mode (a legacy single-pipeline mode is also available).<br>'
                '<span class="hm-tag no">Not implemented</span> a separate statistics agent (statistics are a retrieval tool), independent agent services, '
                'live MSHA data refresh, and non-US regulations.</div>', unsafe_allow_html=True)

with t_small:
    H("Built for a small model", "One hosted model of at most 8 billion parameters (Qwen3-8B): no fine-tuning, no access to weights. "
      "Reliability comes from tools, structure and checks around it.")
    SMALL = [("Structured output, then repair", "Replies are JSON checked against a schema; one repair retry, then a fallback."),
             ("Code does the exact work", "Numbers come from SQL and regulation text from the store; the model never recalls a figure."),
             ("Grounded retrieval", "Keyword and semantic search with a reranker; filters the model invents are dropped."),
             ("Verifier overrides the critic", "Quotes, dates, sections and numbers of two or more digits are checked in code; low support is never accepted."),
             ("Bounded agent loop", "At most 10 steps, 2 revisions and a token budget per question."),
             ("Layered safety", "Rules and a classifier for refusals, an evidence screen, and output filters.")]
    grid("hm-g3", [f'<div class="hm-card"><h4>{escape(t)}</h4><p>{escape(d)}</p></div>' for t, d in SMALL])

F = meta.data_facts()
R = F.get("raw", {})


def ds(title: str, stat: str, lines: list[str], tag: tuple[str, str]) -> str:
    return (f'<div class="hm-card"><span class="hm-tag {tag[0]}">{escape(tag[1])}</span><h4>{escape(title)}</h4><div class="hm-stat">{escape(stat)}</div>'
            f'<div class="hm-meta">{"<br>".join(escape(x) for x in lines)}</div></div>')


with t_data:
    H("Data used by KGP-SafeMine", "Counts, years and dates are computed from the loaded database and data folders when this page opens.")
    if F.get("problems"):
        st.warning("Some data statistics are not available: " + "; ".join(F["problems"]))
    dt = F.get("docs_by_type", {})
    SRCH, SQLQ, NOIDX = ("ok", "Searchable"), ("ok", "Queryable (SQL)"), ("no", "In data folder · not indexed")
    cards = [
        ds("MSHA fatality investigation reports", f"{meta.num(F.get('docs_total'))} documents",
           [f"{meta.num(dt.get('final_report'))} final reports · {meta.num(dt.get('fatality_alert'))} fatality alerts · {meta.num(dt.get('preliminary_report'))} preliminary reports",
            f"{meta.num(F.get('fatal_events'))} fatal events with report text, {meta.years(F.get('span_fatal'))} ({meta.num(F.get('events_indexed'))} events are listed in the corpus index; the rest have no report text)", f"{meta.num(F.get('chunks'))} retrievable passages"], SRCH),
        ds("Accident and injury records", f"{meta.num(F.get('accidents'))} records", [f"Accidents, {meta.years(F.get('span_accidents'))}"], SQLQ),
        ds("Mines register", f"{meta.num(F.get('mines'))} mines", ["Type, status, location, operator"], SQLQ),
        ds("Violations", f"{meta.num(F.get('violations'))} records", [f"Issued {meta.years(F.get('span_violations'))}", f"{meta.num(F.get('orders'))} section 107(a) imminent-danger orders"], SQLQ),
        ds("Inspections", f"{meta.num(F.get('inspections'))} records", [f"Years {meta.years(F.get('span_inspections'))}"], SQLQ),
        ds("Mine production and employment", f"{meta.num(F.get('production'))} rows", [f"One row per mine, sub-unit and year: {meta.num(F.get('production_mine_years'))} mine-years across {meta.num(F.get('production_mines'))} mines", f"Years {meta.years(F.get('span_production'))}"], SQLQ),
        ds("30 CFR (Mine Safety and Health regulations)", f"{meta.num(F.get('cfr_sections'))} sections",
           [f"{meta.num(F.get('cfr_editions'))} dated editions, {str(F.get('cfr_first', ''))[:10]} to {str(F.get('cfr_last', ''))[:10]}",
            f"{meta.num(F.get('cfr_parts_current'))} parts in the current edition ({F.get('cfr_current_date', 'n/a')})",
            f"{meta.num(F.get('cfr_rows'))} section-edition rows"], SQLQ),
        ds("Federal Register rulemakings", f"{meta.num(F.get('fr_rules'))} documents", [f"Published {meta.years(F.get('span_fr'))}"], SQLQ),
        ds("Major mine-disaster investigations", f"{meta.num(R.get('major_disaster_reports'))} report files",
           ["Sago, Upper Big Branch, Crandall Canyon, Quecreek and others", "Collected, but not yet part of the searchable corpus"], NOIDX),
        ds("MSHA policy documents and handbooks", f"{meta.num(R.get('policy_documents'))} documents",
           ["Accident Investigation Procedures Handbook, Program Policy Manual, Part 50 reporting, Form 7000-1 and others", "Collected, but not yet part of the searchable corpus"], NOIDX),
        ds("Statistics and reference material", f"{meta.num(R.get('reference_statistics_files'))} files",
           ["Includes BLS fatality-census (CFOI) tables", "Collected, but not yet part of the searchable corpus"], NOIDX),
    ]
    grid("hm-g3", cards)

with t_limits:
    H("Snapshot and coverage limits")
    snap = F.get("snapshot", "not available")
    st.markdown(f'<div class="hm-card"><p><b>Data snapshot:</b> {escape(snap)} (MSHA data and the current CFR edition as of that date). '
                f'Database built {escape(F.get("db_updated", "n/a"))}; corpus built {escape(F.get("corpus_updated", "n/a"))}.</p>'
                '<ul class="hm-limits"><li>The data is almost entirely from US sources (MSHA, the US Code of Federal Regulations and the Federal Register). '
                'Conclusions apply to US mining; do not extend them to other countries or legal regimes.</li>'
                f'<li>Fatality investigation reports cover {escape(meta.years(F.get("span_fatal")))}; the accident and violation tables cover '
                f'{escape(meta.years(F.get("span_accidents")))} and {escape(meta.years(F.get("span_violations")))}. Events outside these periods are not in the data.</li>'
                '<li>Regulations are answered by effective date from the dated CFR editions held here; an edition that was never collected cannot be quoted.</li>'
                '<li>Items marked "not indexed" are not used by the assistant when it answers.</li></ul></div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ 5. disclaimer and project
st.markdown(f'<div class="hm-disc"><b>Disclaimer.</b> {DISCLAIMER}</div>', unsafe_allow_html=True)
st.markdown('<div class="hm-about">Capstone project, Executive Post Graduate Programme in Generative AI and Agentic AI, Track B (multi-agent system on a '
            'hosted model of at most 8B parameters).</div>', unsafe_allow_html=True)
