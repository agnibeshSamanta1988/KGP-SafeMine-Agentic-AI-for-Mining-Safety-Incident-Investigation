import streamlit as st

from app import lib

lib.hero("Incident Investigation & Root-Cause Analysis",
         "Describe an incident, or name a past one. The agent finds similar MSHA cases, root causes and cited standards, and drafts a brief.")
st.markdown('<div class="sm-note">The facts of a new incident are never invented: the brief restates what you wrote, then adds only what MSHA '
            'records support. Final conclusions belong to the investigator.</div>', unsafe_allow_html=True)
st.write("")
mode = st.radio("What do you need?", ["Investigation brief for a new incident", "Timeline of a past MSHA fatality",
                                       "Similar incidents and risk factors", "Root causes and prevention for a hazard"], horizontal=True)
up = st.file_uploader("Optional: upload an incident description (txt, md, docx, pdf)", type=["txt", "md", "docx", "pdf"])
seed = lib.read_upload_text(up)[:1500] if up else ""
if up and not seed:
    st.warning("Could not read text from that file.")
HINT = {"Investigation brief for a new incident": "a miner was crushed under a raised dump truck bed during maintenance at a surface mine",
        "Timeline of a past MSHA fatality": "the fatal electrical accident at American Eagle Mine on September 17, 2019",
        "Similar incidents and risk factors": "a miner struck by a suspended load during conveyor maintenance",
        "Root causes and prevention for a hazard": "fall of roof fatalities in underground coal mines since 2015"}[mode]
desc = st.text_area("Incident / hazard description", value=seed, placeholder=HINT, height=110)
TEMPLATE = {"Investigation brief for a new incident": "Draft an investigation brief: {}",
            "Timeline of a past MSHA fatality": "Reconstruct the timeline of events for {}.",
            "Similar incidents and risk factors": "Find past incidents similar to {} and compare their risk factors.",
            "Root causes and prevention for a hazard": "What preventive actions does MSHA's history suggest to avoid {}?"}[mode]
if st.button("Run analysis", type="primary", disabled=not lib.ready() or not desc.strip()):
    with st.spinner("Searching the corpus, checking standards, writing and verifying …"):
        r = lib.ask(TEMPLATE.format(desc.strip().rstrip(".")), session_id="investigation")
    st.session_state["last_analysis"] = {"r": r, "title": mode, "q": desc.strip()}
if "last_analysis" in st.session_state:
    a = st.session_state["last_analysis"]
    st.subheader(a["title"])
    lib.render_result(a["r"], key="inv", show_trace=False)
    if a["r"]["status"] == "answered" and st.button("Send to Reports for export"):
        st.session_state["report_turn"] = a["r"]["turn_id"]
        st.session_state.setdefault("report_cache", {})[a["r"]["turn_id"]] = {"r": a["r"], "title": a["title"]}
        st.success("Added. Open Reports & Export.")
