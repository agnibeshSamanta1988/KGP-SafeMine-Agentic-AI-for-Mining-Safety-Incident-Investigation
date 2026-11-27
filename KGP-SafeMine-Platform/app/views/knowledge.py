import json

import altair as alt
import pandas as pd
import streamlit as st

from app import lib, meta, theme
from app.theme import K
from safemine import config
from safemine.tools.hybrid_search import hybrid_search

lib.hero("Knowledge Base", "What the assistant can retrieve from, direct evidence search, and document upload.")
t1, t2, t3 = st.tabs(["📚 Corpus", "🔎 Evidence search", "⬆️ Upload documents"])


@st.cache_data(show_spinner="Loading corpus statistics …")
def corpus_stats():
    rows = [json.loads(x) for x in open(config.CHUNKS_JSONL, encoding="utf-8")]
    return pd.DataFrame(rows)[["event_id", "doc_type", "section", "year"]]


with t1:
    ch = corpus_stats()
    ev = lib.sql("SELECT count(*) n FROM fatal_events").iloc[0, 0]
    cf = lib.sql("SELECT count(*) n FROM cfr_sections").iloc[0, 0]
    ac = lib.sql("SELECT count(*) n FROM accidents").iloc[0, 0]
    k = st.columns(4)
    lib.kpi(k[0], "Indexed chunks", f"{len(ch):,}", "BM25 + dense (bge-small)")
    listed = meta.data_facts().get("events_indexed")
    lib.kpi(k[1], "Events with a dossier", f"{ev:,}", f"of {listed:,} in the event index" if listed else "with indexed text")
    lib.kpi(k[2], "Accident records", f"{ac:,}", "MSHA structured data")
    lib.kpi(k[3], "CFR section-edition rows", f"{cf:,}", "versioned 30 CFR text")
    st.write("")
    a, b = st.columns(2)
    with a:
        lib.section("Chunks by document type")
        dt = ch.doc_type.value_counts().rename_axis("type").reset_index(name="chunks")
        theme.show(alt.Chart(dt).mark_arc(innerRadius=55).encode(
            theta="chunks:Q", color=alt.Color("type:N", legend=alt.Legend(title=None, orient="bottom"),
                                              scale=alt.Scale(range=K.series)),
            tooltip=["type", "chunks"]).properties(height=280), use_container_width=True)
    with b:
        lib.section("Chunks by report section")
        sc = ch.section.value_counts().head(10).rename_axis("section").reset_index(name="chunks")
        theme.show(alt.Chart(sc).mark_bar(color=K.amber, cornerRadiusEnd=3).encode(
            y=alt.Y("section:N", sort="-x", title=None), x=alt.X("chunks:Q", title=None), tooltip=["section", "chunks"]
        ).properties(height=280), use_container_width=True)
    lib.section("How retrieval works")
    c = st.columns(4)
    lib.card(c[0], "1️⃣", "Two searches", "Keyword (BM25) and meaning (dense embeddings) each return 30 candidates.")
    lib.card(c[1], "2️⃣", "Fusion", "Reciprocal-rank fusion merges the lists into one ranking.")
    lib.card(c[2], "3️⃣", "Rerank", "A cross-encoder re-scores the top 20 against the question.")
    lib.card(c[3], "4️⃣", "Select", "6–8 chunks, normally at most two per event (up to six when one event dominates; pattern questions take one per event, up to 12), become the cited evidence.")
    st.caption("Personal names are redacted before indexing by pattern and name-recognition passes. Redaction is strong, not guaranteed.")

with t2:
    with st.container(border=True):
        q = st.text_input("Search the fatality reports", placeholder="inadequate lockout tagout on conveyor …", label_visibility="collapsed")
        c = st.columns([1, 1, 2, 1])
        y1 = c[0].number_input("From year", 2008, 2026, 2008)
        mtype = c[1].selectbox("Mine type", ["Any", "Surface", "Underground"])
        sec = c[2].multiselect("Section", ["SUMMARY", "ROOT_CAUSE", "ENFORCEMENT", "DISCUSSION", "ACCIDENT_DESCRIPTION"], placeholder="All sections")
        go = c[3].button("Search", type="primary", use_container_width=True)
    if go and len(q.strip()) >= 3:
        with st.spinner("Searching …"):
            res = hybrid_search(query=q, year_from=int(y1), mine_type=None if mtype == "Any" else mtype, sections=sec or None, k=8)
        st.caption(f"{len(res)} chunks, ranked by BM25 + dense fusion and cross-encoder rerank")
        for i, h in enumerate(res, 1):
            with st.expander(f"{i}. {h['date']} · {h['classification']} · {h['section']}"):
                st.markdown(f"{lib.pill(h['mine_type'] or 'n/a', 'info')} {lib.pill(h['doc_type'], 'warn')}", unsafe_allow_html=True)
                st.write(h["text"])
                st.caption(h["event_id"])
    elif go:
        st.warning("Type at least 3 characters.")

with t3:
    st.markdown('<div class="sm-note">Uploaded files are stored and listed here. They are <b>not</b> searched by the assistant yet: adding '
                'them to the index requires the redaction and indexing pipeline (<code>make ingest</code>). Until then, use an uploaded '
                'file as an incident description on the Investigation page.</div>', unsafe_allow_html=True)
    st.write("")
    files = st.file_uploader("Add documents", type=["pdf", "txt", "md", "docx", "csv"], accept_multiple_files=True)
    if files and st.button("Save to upload area", type="primary"):
        lib.UPLOADS.mkdir(parents=True, exist_ok=True)
        for f in files:
            (lib.UPLOADS / f.name).write_bytes(f.getvalue())
        st.success(f"Saved {len(files)} file(s).")
    lib.section("Stored documents")
    rows = [{"file": p.name, "size_kb": round(p.stat().st_size / 1024, 1), "indexed": "no (pending pipeline run)"}
            for p in sorted(lib.UPLOADS.iterdir())] if lib.UPLOADS.exists() else []
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("Nothing uploaded yet.")
