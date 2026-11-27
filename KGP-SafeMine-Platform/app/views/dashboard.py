import altair as alt
import pandas as pd
import streamlit as st

from app import lib, meta, theme
from app.theme import K

lib.hero("Safety Dashboard", "Fatality records from the MSHA corpus, standards most often cited, and how the AI assistant is being used.")

ev = lib.sql("SELECT event_id, year, classification, CASE WHEN trim(mine_type) IN ('Surface Mine') THEN 'Surface' WHEN trim(mine_type) = 'Surface of Underground' THEN 'Surface and underground' ELSE trim(mine_type) END AS mine_type, material, state, mine_name, cfr_cited, n_root_causes FROM fatal_events")
lo, hi = int(ev.year.min()), int(ev.year.max())
with st.container(border=True):
    f1, f2, f3 = st.columns([2, 1, 1])
    yr = f1.slider("Years", lo, hi, (lo, hi))
    mt = f2.multiselect("Mine type", sorted(ev.mine_type.dropna().unique()), placeholder="All")
    cl = f3.multiselect("Classification", sorted(ev.classification.dropna().unique()), placeholder="All")
d = ev[(ev.year >= yr[0]) & (ev.year <= yr[1])]
if mt:
    d = d[d.mine_type.isin(mt)]
if cl:
    d = d[d.classification.isin(cl)]
if d.empty:
    st.warning("No events match these filters.")
    st.stop()

per_year = d.groupby("year").size().rename("events").reset_index()
top = d.classification.value_counts().rename_axis("classification").reset_index(name="events")
half = (yr[1] - yr[0] + 1) // 2
recent = int(per_year[per_year.year > yr[1] - half].events.sum()) if half else 0
prior = int(per_year[(per_year.year <= yr[1] - half) & (per_year.year > yr[1] - 2 * half)].events.sum()) if half else 0
delta = f"{(recent - prior) / prior:+.0%} vs previous {half} yrs" if prior else f"last {half} years"
k = st.columns(4)
lib.kpi(k[0], "Events with a dossier", f"{len(d):,}", f"{yr[0]}–{yr[1]}")
lib.kpi(k[1], "Recent period", f"{recent}", delta)
lib.kpi(k[2], "Top classification", top.classification.iloc[0][:20], f"{int(top.events.iloc[0])} events · {top.events.iloc[0] / len(d):.0%}")
lib.kpi(k[3], "Mines involved", f"{d.mine_name.nunique()}", "distinct mine names")
listed = meta.data_facts().get("events_indexed")
if listed:
    st.caption(f"Counts the {len(ev):,} fatality events that have a report dossier; the corpus event index lists {listed:,} events.")
st.write("")

tab1, tab2, tab3, tab4 = st.tabs(["📈 Trends", "🧱 Causes & types", "⚖️ Standards cited", "🤖 Assistant activity"])
with tab1:
    c1, c2 = st.columns([3, 2])
    with c1:
        lib.section("Fatal events per year")
        base = alt.Chart(per_year).encode(x=alt.X("year:O", title=None), y=alt.Y("events:Q", title=None))
        theme.show((base.mark_bar(color=K.amber, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                         + base.mark_line(color=K.navy, point=True)).properties(height=300), use_container_width=True)
    with c2:
        lib.section("Surface vs underground")
        mtd = d.groupby("mine_type").size().rename("events").reset_index()
        theme.show(alt.Chart(mtd).mark_arc(innerRadius=60).encode(
            theta="events:Q", color=alt.Color("mine_type:N", legend=alt.Legend(title=None, orient="bottom"),
                                              scale=alt.Scale(range=K.series)),
            tooltip=["mine_type", "events"]).properties(height=300), use_container_width=True)
with tab2:
    c1, c2 = st.columns(2)
    with c1:
        lib.section("By classification")
        theme.show(alt.Chart(top).mark_bar(color=K.navy, cornerRadiusEnd=3).encode(
            y=alt.Y("classification:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)), x=alt.X("events:Q", title=None),
            tooltip=["classification", "events"]).properties(height=320), use_container_width=True)
    with c2:
        lib.section("Events by classification and year")
        heat = d.groupby(["year", "classification"]).size().rename("events").reset_index()
        theme.show(alt.Chart(heat).mark_rect().encode(
            x=alt.X("year:O", title=None), y=alt.Y("classification:N", title=None, axis=alt.Axis(labelLimit=160)),
            color=alt.Color("events:Q", scale=alt.Scale(range=K.ramp), legend=None), tooltip=["year", "classification", "events"]
        ).properties(height=320), use_container_width=True)
with tab3:
    cited = (d.cfr_cited.dropna().str.split(r"[;,]\s*").explode().str.strip().replace("", pd.NA).dropna().value_counts().head(12)
             .rename_axis("standard").reset_index(name="events"))
    if cited.empty:
        st.info("No cited standards in this selection.")
    else:
        cited["share"] = cited.events / len(d)
        st.dataframe(cited, hide_index=True, use_container_width=True,
                     column_config={"standard": "30 CFR section", "events": st.column_config.NumberColumn("Events"),
                                    "share": st.column_config.ProgressColumn("Share of events", format="percent", min_value=0, max_value=1)})
        st.caption("Look any of these up on the Regulatory Intelligence page.")
with tab4:
    t = lib.ops_db().execute("SELECT status, review, ts, query FROM turns ORDER BY ts DESC").fetchall()
    if not t:
        st.info("No questions asked yet. Use the AI Safety Assistant or Incident Investigation page.")
    else:
        s = pd.DataFrame(t, columns=["status", "review", "ts", "query"])
        a = st.columns(4)
        lib.kpi(a[0], "Questions", len(s), "all sessions")
        lib.kpi(a[1], "Answered", f"{(s.status == 'answered').mean():.0%}", "grounded answers")
        lib.kpi(a[2], "Abstained / refused", f"{(s.status != 'answered').mean():.0%}", "insufficient evidence or policy")
        lib.kpi(a[3], "Awaiting review", int(((s.status == 'answered') & (s.review == 'pending')).sum()), "answers not decided")
        st.write("")
        lib.section("Recent questions")
        s["when"] = pd.to_datetime(s.ts, unit="s").dt.strftime("%d %b %H:%M")
        st.dataframe(s[["when", "query", "status", "review"]].head(8), hide_index=True, use_container_width=True)
