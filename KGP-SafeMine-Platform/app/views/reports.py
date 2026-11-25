import json

import streamlit as st

from app import lib

lib.hero("Reports & Export", "Turn a verified answer into a PDF or Word report. Draft reports are always marked DRAFT until a reviewer approves.")
cache = st.session_state.setdefault("report_cache", {})
db = lib.ops_db()
rows = db.execute("SELECT turn_id, ts, query, status, answer, evidence, review FROM turns WHERE status='answered' ORDER BY ts DESC LIMIT 50").fetchall()
if not rows:
    st.info("No answered questions yet. Run an analysis first.")
    st.stop()
import datetime as dt

opts = {r[0]: f"{dt.datetime.fromtimestamp(r[1]):%d %b %H:%M} · {r[2][:90]}" for r in rows}
default = st.session_state.get("report_turn")
tid = st.selectbox("Source analysis", list(opts), format_func=opts.get, index=list(opts).index(default) if default in opts else 0)
row = next(r for r in rows if r[0] == tid)
res = cache.get(tid, {}).get("r") or {"answer": row[4], "evidence": json.loads(row[5]), "verification": None}
review = lib.review_of(tid)
title = st.text_input("Report title", value="Incident analysis report")

c = st.columns([1, 3])
c[0].markdown(f"Reviewer decision<br>{lib.pill(review.upper(), {'approve': 'ok', 'flag': 'warn', 'reject': 'bad'}.get(review, 'info'))}",
              unsafe_allow_html=True)
stage = "APPROVED" if review == "approve" else "DRAFT: not reviewed or not approved"
c[1].caption("Only an 'approve' decision removes the DRAFT marking." + ("" if review != "reject" else " This answer was rejected: do not rely on it."))
meta = {"stage": stage, "when": lib.now_str(), "review": review}
with st.expander("Preview", expanded=True):
    st.markdown(res["answer"])
d1, d2, _ = st.columns([1, 1, 3])
d1.download_button("Download PDF", lib.report_pdf(title, res, meta), file_name="safemine_report.pdf", mime="application/pdf")
d2.download_button("Download Word", lib.report_docx(title, res, meta), file_name="safemine_report.docx",
                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
if review == "pending":
    st.markdown("**Review now**")
    b = st.columns([1, 1, 1, 4])
    for col, dcs in zip(b, ("approve", "flag", "reject")):
        if col.button(dcs.title(), key=f"rep_{dcs}"):
            lib.get_agent().store.set_review(tid, dcs)
            st.rerun()
