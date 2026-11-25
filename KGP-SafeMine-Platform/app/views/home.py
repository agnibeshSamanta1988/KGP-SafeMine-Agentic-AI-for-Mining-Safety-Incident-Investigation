import json
from html import escape
from pathlib import Path

import streamlit as st

from app import lib, meta

DISCLAIMER = ("KGP-SafeMine is an AI-assisted mining safety intelligence and decision-support system. Its outputs are intended to support, "
              "not replace, qualified investigators, mining safety professionals, regulatory experts, or authorised human decision-makers.")

CSS = """
<style>
.hm-lead { color: var(--muted); font-size: .98rem; line-height: 1.6; max-width: 62rem; margin: .2rem 0 .6rem 0; }
.hm-h { font-size: 1.15rem; font-weight: 800; color: var(--brand); margin: 1.6rem 0 .15rem 0; display: flex; align-items: center; gap: .55rem; }
.hm-h::before { content: ""; width: 4px; height: 1.1rem; background: var(--amber); border-radius: 2px; }
.hm-sub { color: var(--muted); font-size: .86rem; margin: 0 0 .8rem 0; max-width: 60rem; }
.hm-grid { display: grid; gap: .8rem; }
.hm-g3 { grid-template-columns: repeat(3, minmax(0, 1fr)); } .hm-g4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.hm-g2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (max-width: 1000px) { .hm-g3, .hm-g4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .hm-g2, .hm-g3, .hm-g4 { grid-template-columns: minmax(0, 1fr); } }
.hm-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: .9rem 1rem; box-shadow: 0 1px 2px var(--shadow); }
.hm-card h4 { margin: 0 0 .25rem 0; font-size: .95rem; color: var(--brand); line-height: 1.3; }
.hm-card p { margin: 0; color: var(--muted); font-size: .83rem; line-height: 1.5; }
.hm-num { display: inline-flex; width: 1.7rem; height: 1.7rem; border-radius: 50%; background: var(--amber); color: var(--on-amber); font-weight: 800; font-size: .85rem;
          align-items: center; justify-content: center; margin-bottom: .45rem; }
.hm-stat { font-size: 1.45rem; font-weight: 800; color: var(--brand); line-height: 1.15; }
.hm-meta { font-size: .74rem; color: var(--subtle); margin-top: .35rem; line-height: 1.45; }
.hm-tag { display: inline-block; font-size: .66rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; border-radius: 999px; padding: .08rem .5rem; margin-right: .25rem; }
.hm-tag.llm { background: var(--info-bg); color: var(--info-fg); } .hm-tag.code { background: var(--surface2); color: var(--brand); }
.hm-tag.human { background: var(--warn-bg); color: var(--warn-fg); } .hm-tag.ok { background: var(--ok-bg); color: var(--ok-fg); }
.hm-tag.no { background: var(--bad-bg); color: var(--bad-fg); }
.hm-flow { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: .5rem; }
@media (max-width: 1100px) { .hm-flow { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 640px) { .hm-flow { grid-template-columns: minmax(0, 1fr); } }
.hm-step { background: var(--surface); border: 1px solid var(--border); border-top: 4px solid var(--amber); border-radius: 10px; padding: .65rem .75rem; }
.hm-step b { display: block; color: var(--brand); font-size: .86rem; margin-bottom: .15rem; } .hm-step span { color: var(--muted); font-size: .76rem; line-height: 1.4; display: block; }
.hm-sup { background: linear-gradient(100deg, var(--hero-from), var(--hero-to)); color: var(--on-hero); border-radius: 12px; padding: .8rem 1rem; border-left: 6px solid var(--amber); margin-bottom: .7rem; }
.hm-sup b { color: var(--on-hero); } .hm-sup span { color: var(--on-hero); opacity: .85; font-size: .82rem; }
.hm-disc { background: var(--note-bg); border-left: 4px solid var(--amber); border-radius: 8px; padding: .8rem 1rem; color: var(--note-text); font-size: .88rem; line-height: 1.55; margin-top: 1.6rem; }
.hm-limits { margin: .4rem 0 0 0; padding-left: 1.1rem; color: var(--muted); font-size: .83rem; line-height: 1.6; }
.hm-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: .85rem 1rem; box-shadow: 0 1px 2px var(--shadow); }
.hm-kpi .lbl { font-size: .72rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--subtle); }
.hm-kpi .val { font-size: 1.7rem; font-weight: 800; color: var(--brand); line-height: 1.15; margin: .15rem 0 .1rem 0; }
.hm-kpi .note { font-size: .78rem; color: var(--muted); line-height: 1.45; }
.hm-kpi .src { font-size: .68rem; color: var(--subtle); margin-top: .35rem; font-family: ui-monospace, Menlo, Consolas, monospace; }
.hm-about { color: var(--subtle); font-size: .78rem; line-height: 1.55; margin-top: .9rem; }
[data-testid="stMain"] a[data-testid="stPageLink-NavLink"], [data-testid="stMain"] a[data-testid="stPageLink-NavLink"]:hover { text-decoration: none !important; }
[data-testid="stMain"] a[data-testid="stPageLink-NavLink"] p { text-decoration: none !important; }
</style>
"""


def H(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="hm-h">{title}</div>' + (f'<div class="hm-sub">{sub}</div>' if sub else ""), unsafe_allow_html=True)


def grid(cls: str, cards: list[str]) -> None:
    st.markdown(f'<div class="hm-grid {cls}">' + "".join(cards) + "</div>", unsafe_allow_html=True)


st.markdown(CSS, unsafe_allow_html=True)

# ------------------------------------------------------------------ A. welcome + where to start
lib.hero("Mining Safety Intelligence Platform", "KGP-SafeMine · evidence-grounded decision support for mine accident investigation and regulatory analysis")
st.markdown('<div class="hm-lead">Ask questions about US mine accidents, their root causes, MSHA statistics and the 30 CFR safety standards. '
            'KGP-SafeMine finds the relevant records, has a hosted 8-billion-parameter model analyse them, and checks the factual statements in every answer against the '
            'evidence before showing it, with citations. When the evidence is not enough it says so instead of guessing, and nothing is final until '
            'a person has reviewed it.</div>', unsafe_allow_html=True)
def go(col, page: str, label: str, icon: str) -> None:
    """Link to another page of the app (a plain link when the page registry is absent, e.g. this page run on its own in a test)."""
    try:
        col.page_link(st.session_state["_sm_pages"][page], label=label, icon=icon, use_container_width=True)
    except Exception:  # noqa: BLE001  StreamlitPageNotFoundError outside st.navigation
        col.markdown(f"[{label}](/{page})")


cta = st.columns(4)
go(cta[0], "assistant", "Ask the AI Safety Assistant", ":material/smart_toy:")
go(cta[1], "investigation", "Investigate an incident", ":material/search:")
go(cta[2], "regulatory", "Look up a 30 CFR standard", ":material/gavel:")
go(cta[3], "dashboard", "Open the safety dashboard", ":material/dashboard:")

# ------------------------------------------------------------------ B. measured results (read from the frozen evaluation files)
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
        runs = comp = 0
        for f in ("injection_fin_end", "injection_after_mid", "injection_leet_mid"):
            rows = json.loads((EVAL / "results" / f"{f}.json").read_text())
            rows = rows["rows"] if isinstance(rows, dict) else rows
            runs += len(rows)
            comp += sum(1 for x in rows if x.get("verdict") == "COMPROMISED")
        out["injection"] = (comp, runs)
    except Exception:  # noqa: BLE001
        pass
    return out


def kpi(label: str, value: str, note: str, src: str) -> str:
    return (f'<div class="hm-kpi"><div class="lbl">{escape(label)}</div><div class="val">{escape(value)}</div>'
            f'<div class="note">{escape(note)}</div><div class="src">{escape(src)}</div></div>')


H("Measured results", "On the team's frozen 100-question benchmark (written before any agent code) and held-out tests, with the graded model, "
  "Qwen3-8B. Read from the evaluation result files when this page opens.")
M = results()
k = []
if "test" in M:
    p_, n_, rate, ci = M["test"]
    k.append(kpi("End-to-end accuracy", f"{p_} / {n_}", f"{rate:.1%} on the frozen test split"
             + (f" (95% interval {ci[0]:.0%}-{ci[1]:.0%})" if ci else "") + "; prompting the same model alone got 7-16%.", "eval/results/test_final"))
if "retrieval" in M:
    r10, r1, ev8, n_ = M["retrieval"]
    k.append(kpi("Finds the right report", f"{r10:.0%}", f"in the top 10 for {n_} report questions (first place {r1:.0%}); "
             + (f"the right section reaches the answer {ev8:.0%} of the time." if ev8 is not None else ""), "eval/retrieval_results_v2.json"))
if "cfr" in M:
    ok, n_ = M["cfr"]
    k.append(kpi("30 CFR lookups", f"{ok} / {n_}", "exact text, section found by its title, and the edition in force on a past date.", "eval/cfr_results_v2.json"))
if "injection" in M:
    c_, n_ = M["injection"]
    k.append(kpi("Prompt-injection attacks", f"{n_ - c_} / {n_} held", f"attacks hidden in retrieved documents, incl. leetspeak and look-alike letters; "
             f"{c_} got through (planted false facts).", "eval/results/injection_*"))
if k:
    grid("hm-g4", k)
else:
    st.caption("Evaluation result files were not found, so no measured results are shown.")

# ------------------------------------------------------------------ C. what you can do
H("What you can do here")
CAN = [("AI Safety Assistant", "Ask in plain language: root causes across incidents, statistics, 30 CFR requirements, similar cases, or general safety "
        "questions in General chat mode. Cited, verified answers, or an explicit abstention."),
       ("Incident Investigation", "Draft an investigation brief for a described incident from the most similar MSHA investigations and the standards they cited."),
       ("Regulatory Intelligence", "Read the exact 30 CFR text as it stood on a chosen date, search standards by keyword, and see which standards a described situation touches."),
       ("Safety Dashboard", "Trends in fatal accidents by year, classification, mine type and state, and the standards cited most often."),
       ("Knowledge Base", "See what the assistant can retrieve from, search the evidence directly, and add documents."),
       ("Reports and Human Review", "Export a verified answer as a DRAFT DOCX or PDF; a reviewer approves, flags or rejects it in the Review Queue.")]
grid("hm-g3", [f'<div class="hm-card"><h4>{escape(t)}</h4><p>{escape(d)}</p></div>' for t, d in CAN])

# ------------------------------------------------------------------ D. how a question is answered
H("How a question is answered")
FLOW = [("User question", "You ask in plain language, optionally with a date or a standard."),
        ("Planning", "The planner decides what evidence is needed."),
        ("Evidence retrieval", "Reports, tables and the CFR text for the right date are fetched."),
        ("Analysis", "The investigation agent drafts from that evidence only."),
        ("Verification", "Each factual sentence is checked against its cited source."),
        ("Response / report", "A cited answer, or an explicit abstention; optional DOCX/PDF."),
        ("Human review", "A reviewer approves, flags or rejects.")]
parts = []
for i, (t, d) in enumerate(FLOW):
    parts.append(f'<div class="hm-step"><b>{i + 1}. {escape(t)}</b><span>{escape(d)}</span></div>')
st.markdown('<div class="hm-flow">' + "".join(parts) + "</div>", unsafe_allow_html=True)
grid("hm-g3", ['<div class="hm-card"><h4>Grounded and cited</h4><p>Answers are built from retrieved evidence and cite it; statements with an invented regulation number, quotation, figure or date are removed and weakly supported ones are flagged.</p></div>',
               '<div class="hm-card"><h4>Abstains when unsure</h4><p>If the evidence is thin or outside the data’s coverage, the system says so rather than answering.</p></div>',
               '<div class="hm-card"><h4>Drafts until approved</h4><p>AI-generated reports stay drafts until an authorised reviewer approves them in the Human Review Queue.</p></div>'])

# ------------------------------------------------------------------ D. architecture
H("How the agents work together",
  "One request runs through role-specialised agents in a single orchestrated pipeline. They are components of one application, coordinated by a "
  "supervisor over an in-process message bus, not separate services or autonomous processes.")
st.markdown('<div class="hm-sup"><b>Supervisor (orchestrator)</b><br><span>Creates a per-request task context, routes work between the agents below, enforces the '
            'step and time budgets, and fails closed: if a step cannot be completed or verified, the answer is withheld or the system abstains.</span></div>', unsafe_allow_html=True)
AG = [("Safety / policy check", "llm", "LLM + rules", "Screens the question and the retrieved text: out-of-scope requests are refused and instructions hidden in documents are ignored."),
      ("Planner", "llm", "LLM", "Turns the question into a plan: which sources to consult, which standards and dates matter."),
      ("Retrieval", "code", "Code", "Hybrid keyword and semantic search over report passages, plus SQL access to the structured tables. The accident-statistics step is a tool of this agent."),
      ("Regulatory Intelligence", "code", "Code", "Looks up the exact 30 CFR section text that was in force on the relevant date, from the historical editions."),
      ("Incident Investigation", "llm", "LLM", "Writes the analysis (root causes, contributing factors, comparisons) strictly from the retrieved evidence, with citations."),
      ("Verification", "code", "Code + LLM", "A validator checks each factual sentence (citations, quotes, numbers, dates, CFR sections) against its cited source; a critic reviews the draft. A sentence with an invented regulation number, quotation, figure or date is removed; other weakly supported sentences are flagged."),
      ("Report Generation", "code", "Code", "Assembles the verified answer with its notes, evidence and claim map on screen; the Reports page exports it as a DOCX or PDF (answer, evidence and support score), marked DRAFT until approved."),
      ("Human Review", "human", "Person", "Not an agent: a reviewer approves, flags or rejects each answer in the Human Review Queue.")]
grid("hm-g4", [f'<div class="hm-card"><span class="hm-tag {k}">{escape(t)}</span><h4>{escape(n)}</h4><p>{escape(d)}</p></div>' for n, k, t, d in AG])
with st.expander("How the agents collaborate, and what is implemented"):
    st.markdown('<div class="hm-sub" style="margin-top:.4rem"><b>Collaboration:</b> the planner decides what is needed; retrieval and regulatory lookup gather the evidence; the investigation agent '
            'drafts from that evidence only; verification can send the draft back for revision (a bounded number of rounds); the result goes to a human reviewer.</div>', unsafe_allow_html=True)
    st.markdown('<div class="hm-sub"><span class="hm-tag ok">Implemented</span> all components above, in the multi-agent mode (a legacy single-pipeline mode is also available). '
            '<span class="hm-tag no">Not implemented</span> a separate statistics agent (statistics are a retrieval tool), independent agent services, '
            'live MSHA data refresh, and non-US regulations.</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ E. built for a small model (Track B)
H("Built for a small model", "Track B gives us one hosted model of at most 8 billion parameters (Qwen3-8B): no fine-tuning, no access to weights. "
  "Reliability is won with tools, structure and checks around the model.")
SMALL = [("Structured output, then repair", "Every model call returns JSON validated against a schema; one repair retry, then a deterministic fallback, so a malformed reply never crashes an answer."),
         ("Code does the exact work", "Numbers come from SQL, regulation text from the versioned store, record IDs from lookups: the model never writes SQL or recalls a figure."),
         ("Grounded retrieval", "Keyword and semantic search with a reranker; filters the model invents are dropped unless the question states them."),
         ("Verifier overrides the critic", "Quotes, numbers, dates and CFR sections are checked against the cited text in code; low support is never accepted."),
         ("Bounded agent loop", "At most 10 steps, 2 revisions and a token budget per question; the upGrad endpoint's 8k context and 1-request limit are respected."),
         ("Layered safety", "Rules plus a model classifier for refusals, an evidence screen against hidden instructions, and output filters for names and verdicts.")]
grid("hm-g3", [f'<div class="hm-card"><h4>{escape(t)}</h4><p>{escape(d)}</p></div>' for t, d in SMALL])

# ------------------------------------------------------------------ F. data
H("Data used by KGP-SafeMine", "Counts, year ranges and dates are computed from the loaded database, corpus and data folders when this page opens; the short descriptions beside them are written by hand.")
F = meta.data_facts()
R = F.get("raw", {})
if F.get("problems"):
    st.warning("Some data statistics are not available: " + "; ".join(F["problems"]))


def ds(title: str, stat: str, lines: list[str], tag: tuple[str, str]) -> str:
    return (f'<div class="hm-card"><span class="hm-tag {tag[0]}">{escape(tag[1])}</span><h4>{escape(title)}</h4><div class="hm-stat">{escape(stat)}</div>'
            f'<div class="hm-meta">{"<br>".join(escape(x) for x in lines)}</div></div>')


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
        f"{meta.num(F.get('cfr_parts_current'))} parts in the current edition ({F.get('cfr_current_date', 'n/a')})"], SQLQ),
    ds("Federal Register rulemakings", f"{meta.num(F.get('fr_rules'))} documents", [f"Published {meta.years(F.get('span_fr'))}"], SQLQ),
    ds("Major mine-disaster investigations", f"{meta.num(R.get('major_disaster_reports'))} report files",
       ["Sago, Upper Big Branch, Crandall Canyon, Quecreek and others", "Collected, but not yet part of the searchable corpus"], NOIDX),
    ds("MSHA policy documents and handbooks", f"{meta.num(R.get('policy_documents'))} documents",
       ["Accident Investigation Procedures Handbook, Program Policy Manual, Part 50 reporting, Form 7000-1 and others", "Collected, but not yet part of the searchable corpus"], NOIDX),
    ds("Statistics and reference material", f"{meta.num(R.get('reference_statistics_files'))} files",
       ["Includes BLS fatality-census (CFOI) tables", "Collected, but not yet part of the searchable corpus"], NOIDX),
]
grid("hm-g3", cards)
snap = F.get("snapshot", "not available")
st.markdown(f'<div class="hm-card" style="margin-top:.8rem"><h4>Snapshot and coverage limits</h4><p><b>Data snapshot:</b> {escape(snap)} (MSHA data and the current CFR edition as of that date). '
            f'Database built {escape(F.get("db_updated", "n/a"))}; corpus built {escape(F.get("corpus_updated", "n/a"))}.</p>'
            '<ul class="hm-limits"><li>The data is almost entirely from US sources (MSHA, the US Code of Federal Regulations and the Federal Register). '
            'Conclusions apply to US mining; do not extend them to other countries or legal regimes.</li>'
            f'<li>Fatality investigation reports cover {escape(meta.years(F.get("span_fatal")))}; the accident and violation tables cover '
            f'{escape(meta.years(F.get("span_accidents")))} and {escape(meta.years(F.get("span_violations")))}. Events outside these periods are not in the data.</li>'
            '<li>Regulations are answered by effective date from the dated CFR editions held here; an edition that was never collected cannot be quoted.</li>'
            '<li>Items marked "not indexed" are not used by the assistant when it answers.</li></ul></div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ G. disclaimer and project
st.markdown(f'<div class="hm-disc"><b>Disclaimer.</b> {DISCLAIMER}</div>', unsafe_allow_html=True)
st.markdown('<div class="hm-about">Capstone project, Executive Post Graduate Programme in Generative AI and Agentic AI, Track B (multi-agent system on a '
            'hosted model of at most 8B parameters).</div>', unsafe_allow_html=True)
