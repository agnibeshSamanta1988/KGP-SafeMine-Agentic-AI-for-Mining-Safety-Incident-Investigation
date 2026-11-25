import datetime as dt

import streamlit as st

from app import lib
from safemine.tools.cfr_lookup import cfr_lookup

lib.hero("Regulatory Intelligence & Compliance Check",
         "Versioned 30 CFR text (as in force on a chosen date) and an evidence-based check of which standards a situation touches.")
t1, t2, t3 = st.tabs(["Look up a standard", "Search standards", "Compliance check"])

with t1:
    c1, c2 = st.columns([2, 1])
    sec = c1.text_input("Section", placeholder="56.14211  or  30 CFR 75.202(a)")
    asof = c2.date_input("In force on", value=dt.date(2026, 10, 30), min_value=dt.date(2008, 7, 1), max_value=dt.date(2026, 10, 30))
    if st.button("Fetch text", key="fetch") and sec.strip():
        try:
            res = cfr_lookup(mode="exact", section=sec, as_of=asof)
        except Exception as e:  # invalid section string
            res = {"error": str(e)}
        if res.get("error") or not res.get("text"):
            st.warning(res.get("error") or "Section not found in the corpus.")
        else:
            st.markdown(f"**30 CFR {res.get('section', sec)}** · {res.get('subject', '')}")
            st.caption(f"Version status: {res.get('version_status', '?')}  ·  {res.get('source', '')}")
            st.write(res["text"])

with t2:
    qy = st.text_input("Keywords", placeholder="conveyor guard, roof bolts, ventilation …")
    part = st.selectbox("Part", ["Any", "46", "48", "50", "56", "57", "70", "71", "72", "75", "77"])
    if st.button("Search", key="search") and qy.strip():
        res = cfr_lookup(mode="search", query=qy, part=None if part == "Any" else part, k=8)
        for h in res.get("results", []):
            with st.expander(f"30 CFR {h['section']} · {h['subject']}"):
                st.write(h["text"])
        if not res.get("results"):
            st.info("No matches.")

with t3:
    st.markdown('<div class="sm-note">Decision support, not a legal opinion. The answer lists standards MSHA text supports and what was '
                'cited in past cases; it does not declare a site compliant or non-compliant.</div>', unsafe_allow_html=True)
    cond = st.text_area("Situation or condition to check", height=100,
                        placeholder="Unguarded conveyor pulleys near a travelway at a surface crushing plant")
    if st.button("Check standards", type="primary", disabled=not lib.ready() or not cond.strip()):
        with st.spinner("Finding standards and past citations …"):
            r = lib.ask(f"Which 30 CFR standards are relevant to {cond.strip().rstrip('.')}, and what did MSHA cite in past cases?", "regulatory")
        st.session_state["last_reg"] = r
        st.session_state.setdefault("report_cache", {})[r["turn_id"]] = {"r": r, "title": "Regulatory check"}
    if "last_reg" in st.session_state:
        lib.render_result(st.session_state["last_reg"], key="reg")
