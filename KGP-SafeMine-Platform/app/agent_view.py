"""UI for the multi-agent layer: claim-by-claim verification and the agent trail of one answer."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import lib

ICON = {"safety": "🛡️", "planner": "🧭", "retrieval": "🔎", "regulatory": "⚖️", "investigation": "🕵️", "validator": "✅", "critic": "🧐",
        "report": "📄", "supervisor": "🎛️"}


def _verdict(c: dict) -> str:
    if c["status"] == "unsupported":
        return "❌ unsupported"
    if not c["citations"]:
        return "⚠️ uncited"
    return "🟡 weak support" if c.get("weak_support") else "✅ supported"


def render_verification(res: dict) -> None:
    """Every factual sentence of the answer, the evidence it cites, its verdict and where that evidence came from."""
    claims, s = res.get("claim_map"), res.get("verification_report")
    if not claims or not s:
        return
    with st.expander(f"🔬 Verification detail · {s['supported']}/{s['claims']} claims supported · traceability {s['traceability']:.0%}"):
        k = st.columns(4)
        lib.kpi(k[0], "Claims checked", s["claims"], f"{s['rounds']} drafting round(s)")
        lib.kpi(k[1], "Supported", f"{s['supported']}", f"support ratio {s['support_ratio']:.0%}")
        lib.kpi(k[2], "Traceability", f"{s['traceability']:.0%}", "claims with a citation")
        lib.kpi(k[3], "Removed", s["removed"], "unverifiable statements")
        st.write("")
        rows = [{"Claim": c["sentence"], "Verdict": _verdict(c), "Evidence": " ".join(c["citations"]) or "none",
                 "Grounding": c["grounding"], "Source": (c["sources"][0].get("event_id") or c["sources"][0].get("label") or "") if c["sources"] else ""}
                for c in claims]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={"Grounding": st.column_config.ProgressColumn("Word overlap with evidence", min_value=0, max_value=1, format="%.2f")})
        st.caption("Supported = every number, date, quote and CFR section in the claim was found in its cited evidence (checked in code). "
                   "Word overlap is a soft signal: a low value on a 'supported' claim means the sentence barely resembles its source and deserves a human look.")
        bad = [c for c in claims if c["issues"]]
        for c in bad:
            st.markdown(f"- ❌ {c['sentence'][:160]} → {'; '.join(c['issues'])}")


def render_agent_trail(res: dict) -> None:
    trail = res.get("agent_trail")
    if not trail:
        return
    tasks = [m for m in trail if m["kind"] == "task" and m["from"] == "supervisor"]
    seen, order = set(), []
    for m in tasks:
        if m["to"] not in seen:
            seen.add(m["to"])
            order.append(m["to"])
    if order:
        st.caption("Agents involved: " + "  →  ".join(f"{ICON.get(a, '')} {a}" for a in order))
    with st.expander("Agent messages"):
        rows = [{"t (s)": m["t"], "From": m["from"], "To": m["to"], "Type": m["kind"], "Action": m["action"],
                 "Info": ", ".join(f"{k}={v}" for k, v in (m.get("info") or {}).items())} for m in trail]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
