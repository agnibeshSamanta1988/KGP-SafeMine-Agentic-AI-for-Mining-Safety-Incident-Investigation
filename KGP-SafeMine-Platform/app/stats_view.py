"""Advanced-analytics panel for statistics answers: charts, KPI cards and computed insights.

The rows come straight from the accident_stats tool call (kept in the agent trace), so every number shown here is the database's
number, not text written by the model. Insights are computed in code (shares, peaks, trends) and only describe the data;
they never claim causes.
"""
from __future__ import annotations

import re

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app import lib, theme
from app.theme import K

SNAPSHOT_YEAR = 2026            # data runs to 30 Oct 2026: that year is partial
GROUP_LABEL = {"classification": "classification", "accident_type": "accident type", "equipment": "equipment", "occupation": "occupation",
               "activity": "activity", "injury_source": "injury source", "nature_injury": "nature of injury", "year": "year",
               "state": "state", "coal_metal": "coal / metal", "mine_type": "mine type", "subunit": "mine area", "degree_injury": "injury degree",
               "has_final_report": "final report available"}
UNITS = {"count_by": "accident records (injured persons)", "fatal_events_by": "fatality events (final reports)",
         "corpus_events": "fatality events in the report corpus", "violations_by": "citations issued", "yearly_trend": "accident records"}
KIND = {"count_by": "Fatal accident records", "fatal_events_by": "Fatality events", "corpus_events": "Corpus fatality events",
        "violations_by": "Citations (violations)", "yearly_trend": "Yearly trend"}


def extract(res: dict) -> list[dict]:
    """Chartable accident_stats results of this answer, in call order, without duplicates."""
    out, seen = [], set()
    for ev in res.get("trace", []):
        d = ev.get("data")
        if ev.get("kind") != "tool" or ev.get("tool") != "accident_stats" or not isinstance(d, dict) or d.get("error"):
            continue
        if not (d.get("rows") or d.get("accidents_by_year")):
            continue
        key = repr(sorted((d.get("args") or {}).items())) + str(d.get("metric"))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _period(args: dict) -> str:
    a, b = args.get("year_from"), args.get("year_to")
    if a and b:
        return f"{a}" if a == b else f"{a}–{b}"
    return f"{a} onward" if a else f"up to {b}" if b else "all years in the data"


def _filters(args: dict) -> list[str]:
    names = {"classification": "classification", "accident_type": "type", "equipment": "equipment", "state": "state", "coal_metal": "sector",
             "mine_id": "mine", "has_final_report": "final report"}
    chips = [f"{names[k]}: {args[k]}" for k in names if args.get(k) not in (None, "")]
    if args.get("fatal_only") is False:
        chips.append("all injury severities")
    return chips


def _title(d: dict) -> str:
    args, metric = d.get("args") or {}, d.get("metric")
    if metric == "yearly_trend":
        return f"Yearly trend · {_period(args)}"
    if metric == "mine_profile":
        return "Mine profile"
    g = args.get("group_by") or "classification"
    return f"{KIND.get(metric, 'Counts')} by {GROUP_LABEL.get(g, g)} · {_period(args)}"


def _bar_chart(df: pd.DataFrame, sig: bool = False, horizontal: bool = True) -> alt.Chart:
    d = df.copy()
    d["share"] = d.n / d.n.sum()
    tip = [alt.Tooltip("key:N", title="Group"), alt.Tooltip("n:Q", title="Count", format=","), alt.Tooltip("share:Q", title="Share", format=".1%")]
    base = alt.Chart(d).encode(y=alt.Y("key:N", sort=None, title=None, axis=alt.Axis(labelLimit=240)),
                               x=alt.X("n:Q", title=None, scale=alt.Scale(domain=[0, float(d.n.max()) * 1.18])), tooltip=tip)
    bars = base.mark_bar(color=K.navy, cornerRadiusEnd=3).encode(color=alt.condition(alt.datum.key == d.key.iloc[0], alt.value(K.amber), alt.value(K.navy)))
    labels = base.mark_text(align="left", dx=4, color=K.text).encode(text=alt.Text("n:Q", format=","))
    layers = bars + labels
    if sig and "sig_sub" in d:
        layers = layers + base.mark_bar(color=K.blue, opacity=.9, cornerRadiusEnd=3, size=8).encode(x="sig_sub:Q", tooltip=[alt.Tooltip("sig_sub:Q", title="Significant & substantial")])
    return layers.properties(height=max(120, 30 * len(d)))


def _donut(df: pd.DataFrame, max_slices: int = 7) -> alt.Chart:
    d = df.copy()
    if len(d) > max_slices:
        d = pd.concat([d.head(max_slices - 1), pd.DataFrame([{"key": "Other", "n": d.n.iloc[max_slices - 1:].sum()}])])
    d["share"] = d.n / d.n.sum()
    return alt.Chart(d).mark_arc(innerRadius=58).encode(
        theta="n:Q", color=alt.Color("key:N", sort=None, legend=alt.Legend(title=None, orient="bottom", columns=2, labelLimit=190),
                                     scale=alt.Scale(range=K.series)),
        tooltip=[alt.Tooltip("key:N", title="Group"), alt.Tooltip("n:Q", format=","), alt.Tooltip("share:Q", format=".1%")]).properties(height=300)


def _category_view(d: dict) -> None:
    rows = pd.DataFrame(d["rows"])
    if rows.empty:
        st.info("No rows for this selection.")
        return
    rows["key"] = rows["key"].astype(str)
    shown = int(rows.n.sum())
    total = int(d.get("total_matching_records") or shown)
    top, share = rows.iloc[0], rows.n.iloc[0] / shown
    k = st.columns(4)
    lib.kpi(k[0], "Total", f"{total:,}", UNITS.get(d.get("metric"), "records"))
    lib.kpi(k[1], "Largest group", str(top["key"])[:22], f"{int(top.n):,} · {share:.0%} of shown")
    lib.kpi(k[2], "Groups shown", len(rows), f"top {len(rows)} of the grouping")
    lib.kpi(k[3], "Top 3 share", f"{rows.n.head(3).sum() / shown:.0%}", "concentration")
    st.write("")
    c1, c2 = st.columns([3, 2])
    sig = "sig_sub" in rows
    with c1:
        lib.section("Ranking")
        theme.show(_bar_chart(rows, sig=sig), use_container_width=True)
        if sig:
            st.caption("Blue overlay = citations marked significant & substantial (S&S).")
    with c2:
        lib.section("Share of shown records")
        theme.show(_donut(rows), use_container_width=True)
    ins = []
    ins.append(f"**{top['key']}** is the largest group with **{int(top.n):,}** ({share:.0%} of the {shown:,} shown).")
    if len(rows) >= 2 and rows.n.iloc[1] > 0:
        ins.append(f"It has **{rows.n.iloc[0] / rows.n.iloc[1]:.1f}×** the count of the next group, **{rows['key'].iloc[1]}** ({int(rows.n.iloc[1]):,}).")
    if len(rows) >= 3:
        ins.append(f"The top three groups together account for **{rows.n.head(3).sum() / shown:.0%}** of the shown records.")
    if total > shown:
        ins.append(f"These {len(rows)} groups cover **{shown / total:.0%}** of all {total:,} matching records; the rest is spread across smaller groups.")
    if sig:
        r = rows.assign(s=rows.sig_sub / rows.n)
        hi = r[r.n >= max(5, r.n.max() * 0.05)].sort_values("s", ascending=False).iloc[0]
        ins.append(f"**{rows.sig_sub.sum() / shown:.0%}** of these citations are significant & substantial; the highest rate among larger groups is **{hi['key']}** ({hi.s:.0%}).")
    _insights(ins)
    _data_block(rows.rename(columns={"key": "group", "n": "count"}), d)


def _trend_view(d: dict, key_col: str = "year") -> None:
    rows = pd.DataFrame(d["rows"])
    ycol = "year" if "year" in rows else "key"
    s = rows.set_index(ycol)["n"].astype(float)
    s.index = s.index.astype(int)
    s = s.reindex(range(int(s.index.min()), int(s.index.max()) + 1), fill_value=0)
    df = pd.DataFrame({"year": s.index, "n": s.values})
    df["avg3"] = df.n.rolling(3, min_periods=1).mean()
    partial = int(df.year.max()) >= SNAPSHOT_YEAR
    full = df[df.year < SNAPSHOT_YEAR] if partial else df
    total = int(d.get("total_matching_records") or df.n.sum())
    peak, low = df.loc[df.n.idxmax()], full.loc[full.n.idxmin()] if len(full) else df.loc[df.n.idxmin()]
    slope = float(np.polyfit(full.year, full.n, 1)[0]) if len(full) >= 4 else 0.0
    mean = float(full.n.mean()) if len(full) else 0.0
    direction = "flat" if mean == 0 or abs(slope) / mean < 0.02 else ("downward" if slope < 0 else "upward")
    k = st.columns(4)
    lib.kpi(k[0], "Total", f"{total:,}", f"{int(df.year.min())}–{int(df.year.max())}")
    lib.kpi(k[1], "Peak year", f"{int(peak.year)}", f"{int(peak.n):,}")
    lib.kpi(k[2], "Yearly average", f"{mean:,.0f}", "full years only" if partial else "all years")
    lib.kpi(k[3], "Trend", direction.title(), f"{slope:+.1f} per year" if len(full) >= 4 else "too few years")
    st.write("")
    lib.section("Per year, with 3-year moving average")
    base = alt.Chart(df).encode(x=alt.X("year:O", title=None))
    bars = base.mark_bar(color=K.grey, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        y=alt.Y("n:Q", title=None), tooltip=[alt.Tooltip("year:O"), alt.Tooltip("n:Q", title="Count", format=",")],
        color=alt.condition(alt.datum.year == int(peak.year), alt.value(K.amber), alt.value(K.grey)))
    line = base.mark_line(color=K.navy, point=True, strokeWidth=2.5).encode(y="avg3:Q", tooltip=[alt.Tooltip("avg3:Q", title="3-yr average", format=".1f")])
    layers = bars + line
    if len(full) >= 4:
        fit = pd.DataFrame({"year": full.year, "fit": np.polyval(np.polyfit(full.year, full.n, 1), full.year)})
        layers = layers + alt.Chart(fit).mark_line(color=K.blue, strokeDash=[6, 4]).encode(x=alt.X("year:O"), y="fit:Q")
    theme.show(layers.properties(height=320), use_container_width=True)
    st.caption("Amber bar = peak year · navy line = 3-year moving average · dashed = linear trend over full years.")
    ins = [f"The peak was **{int(peak.year)}** with **{int(peak.n):,}**; the lowest full year was **{int(low.year)}** with **{int(low.n):,}**."]
    if len(full) >= 6:
        a, b = full.n.tail(3).mean(), full.n.iloc[-6:-3].mean()
        if b > 0:
            ins.append(f"The last three full years averaged **{a:,.1f}** a year, **{(a - b) / b:+.0%}** versus the three before ({b:,.1f}).")
    if len(full) >= 4:
        ins.append(f"Overall the linear trend is **{direction}** ({slope:+.1f} per year on an average of {mean:,.1f}).")
    if len(full) >= 2 and full.n.iloc[0] > 0:
        ins.append(f"From {int(full.year.iloc[0])} to {int(full.year.iloc[-1])} (full years) the yearly count changed by "
                   f"**{(full.n.iloc[-1] - full.n.iloc[0]) / full.n.iloc[0]:+.0%}**.")
    if partial:
        ins.append(f"{SNAPSHOT_YEAR} is partial (data runs to 30 Oct), so it is left out of the trend and averages.")
    _insights(ins)
    _data_block(df[["year", "n"]].rename(columns={"n": "count"}), d)


def _profile_view(d: dict) -> None:
    mine = (d.get("mine") or [{}])[0]
    acc = pd.DataFrame(d.get("accidents_by_year") or [])
    show = {"CURRENT_MINE_NAME": "Mine", "STATE": "State", "COAL_METAL_IND": "Sector (C/M)", "CURRENT_MINE_TYPE": "Type",
            "CURRENT_MINE_STATUS": "Status", "NO_EMPLOYEES": "Employees", "DISTRICT": "MSHA district"}
    total = int(acc.n.sum()) if len(acc) else 0
    fatal = int(acc.fatal.sum()) if len(acc) else 0
    k = st.columns(4)
    lib.kpi(k[0], "Mine", str(mine.get("CURRENT_MINE_NAME", "n/a"))[:22], f"{mine.get('STATE', '')} · {mine.get('CURRENT_MINE_TYPE', '')}")
    lib.kpi(k[1], "Accident records", f"{total:,}", "all years in data")
    lib.kpi(k[2], "Fatal", fatal, f"{fatal / total:.1%} of records" if total else "")
    lib.kpi(k[3], "Inspections", f"{int(d.get('n_inspections') or 0):,}", "on record")
    st.write("")
    if len(acc):
        long = pd.concat([acc.assign(kind="Non-fatal", v=acc.n - acc.fatal), acc.assign(kind="Fatal", v=acc.fatal)])
        lib.section("Accident records per year")
        theme.show(alt.Chart(long).mark_bar().encode(
            x=alt.X("yr:O", title=None), y=alt.Y("v:Q", title=None, stack="zero"),
            color=alt.Color("kind:N", scale=alt.Scale(domain=["Non-fatal", "Fatal"], range=[K.grey, K.amber]), legend=alt.Legend(title=None, orient="top")),
            tooltip=["yr", "kind", "v"]).properties(height=280), use_container_width=True)
        w = acc.sort_values("n", ascending=False).iloc[0]
        _insights([f"The worst year on record was **{int(w.yr)}** with **{int(w.n)}** accident records ({int(w.fatal)} fatal).",
                   f"Over {len(acc)} years with records, that is **{total / len(acc):.1f}** a year on average."])
    st.dataframe(pd.DataFrame([{show[k]: mine.get(k) for k in show if k in mine}]), hide_index=True, use_container_width=True)


def _insights(items: list[str]) -> None:
    lib.section("Insights")
    html = lambda t: re.sub(r"\*\*(.+?)\*\*", lambda m: "<b>" + m.group(1) + "</b>", t.replace("<", "&lt;"))  # noqa: E731  markdown is not parsed inside html blocks
    st.markdown('<div class="sm-note"><b>Computed from the data above.</b><br>' + "<br>".join("• " + html(i) for i in items) + "</div>", unsafe_allow_html=True)


def _data_block(df: pd.DataFrame, d: dict) -> None:
    note = d.get("note")
    with st.expander("Data table and download"):
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("Download CSV", df.to_csv(index=False).encode(), file_name="safemine_statistics.csv", mime="text/csv", key=f"dl_{abs(hash(str(d.get('args'))))}_{d.get('metric')}")
        if note:
            st.caption(note)
        st.caption(d.get("source", ""))


def render_stats(res: dict, key: str = "") -> None:
    """Show an analytics panel for each accident_stats result behind this answer."""
    results = extract(res)
    if not results:
        return
    st.markdown("---")
    st.markdown("#### 📊 Analytics")
    if len(results) > 1:
        tabs = st.tabs([_title(d)[:48] for d in results])
    else:
        tabs = [st.container()]
    for tab, d in zip(tabs, results):
        with tab:
            st.markdown(f"**{_title(d)}**")
            chips = _filters(d.get("args") or {})
            if chips:
                st.markdown(" ".join(f'<span class="sm-chip">{c}</span>' for c in chips), unsafe_allow_html=True)
            m, g = d.get("metric"), (d.get("args") or {}).get("group_by")
            if m == "mine_profile":
                _profile_view(d)
            elif m == "yearly_trend" or g == "year":
                _trend_view(d)
            else:
                _category_view(d)
