import datetime as dt

import streamlit as st

from app import lib

lib.hero("Human Review Queue", "Every answer should be checked by a person. Approve, flag for follow-up, or reject; decisions are stored with the turn.")
db = lib.ops_db()
f = st.radio("Show", ["pending", "flag", "approve", "reject", "all"], horizontal=True)
q = "SELECT turn_id, ts, query, answer, evidence, review FROM turns WHERE status='answered'"
rows = db.execute(q + ("" if f == "all" else " AND review=?") + " ORDER BY ts DESC LIMIT 30", () if f == "all" else (f,)).fetchall()
counts = dict(db.execute("SELECT review, count(*) FROM turns WHERE status='answered' GROUP BY review").fetchall())
k = st.columns(4)
for col, name in zip(k, ("pending", "approve", "flag", "reject")):
    lib.kpi(col, name.title(), counts.get(name, 0), "answers")
st.write("")
if not rows:
    st.info("Nothing in this view.")
for tid, ts, query, answer, ev, rv in rows:
    with st.expander(f"{dt.datetime.fromtimestamp(ts):%d %b %H:%M} · {query[:100]} · {rv}"):
        st.markdown(f"**Question:** {query}")
        st.markdown(answer)
        b = st.columns([1, 1, 1, 4])
        for col, d in zip(b, ("approve", "flag", "reject")):
            if col.button(d.title(), key=f"{tid}_{d}"):
                lib.get_agent().store.set_review(tid, d)
                st.rerun()
