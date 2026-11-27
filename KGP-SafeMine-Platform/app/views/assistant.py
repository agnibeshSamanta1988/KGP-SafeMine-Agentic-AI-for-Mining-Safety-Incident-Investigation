import streamlit as st

from app import lib
from safemine import config

lib.hero("AI Safety Assistant", "Ask about root causes, statistics, 30 CFR standards or similar incidents, or chat about general safety topics. "
         "Answers from the records cite their evidence and are verified in code.")

CATS = {"🔍 Root causes": ["What root causes did MSHA find for conveyor fatalities at surface mines since 2018?",
                          "What preventive actions does MSHA history suggest for fall of roof fatalities in underground coal mines?"],
        "📊 Statistics": ["How many fatal accidents by classification since 2015?",
                         "How many fatal events does the corpus have per year since 2018?"],
        "⚖️ Standards": ["What does 30 CFR 56.14211 require?",
                        "Which 30 CFR standards apply to unguarded conveyor pulleys?"],
        "🧭 Similar incidents": ["Find past incidents similar to a miner struck by a suspended load during conveyor maintenance.",
                                "Draft an investigation brief: a miner was crushed under a raised dump truck bed during maintenance."],
        "💬 General": ["What can you help me with?",
                      "What is MSHA and what does it regulate?",
                      "What is the difference between a 104(a) citation and a 107(a) imminent-danger order?",
                      "What are good practices to prevent slips and falls at a processing plant?"]}
GENERAL_TAB = "💬 General"
MODES = {"grounded": "📚 Evidence only", "general": "💬 General chat"}
st.session_state.setdefault("chat", [])
st.session_state.setdefault("sid", "console")
st.session_state.setdefault("answer_mode", "grounded")
if st.session_state.get("pending_mode"):   # set before the mode switch is drawn (a widget's value cannot change after that)
    st.session_state["answer_mode"] = st.session_state.pop("pending_mode")

bar = st.columns([3, 1, 1])
bar[0].markdown(f"{lib.pill('MODEL', 'info')} &nbsp;{config.llm_label()} &nbsp;·&nbsp; temperature {config.TEMPERATURE}", unsafe_allow_html=True)
st.radio("Answer mode", list(MODES), format_func=MODES.get, key="answer_mode", horizontal=True,
         help="Evidence only: answers come from MSHA records and 30 CFR, with citations, or the assistant abstains. "
              "General chat: the same, plus a labelled general-knowledge answer for general safety questions the records do not cover "
              "(never for a specific incident, which would be guessing).")
trace = bar[1].toggle("Agent trace (on screen)", help="Shows each answer's step-by-step agent log (plan, tools, checks) under the answer. "
                     "Sending traces to Langfuse is a separate switch: Settings → Generation → Tracing (Langfuse).")
if bar[2].button("New conversation", disabled=not st.session_state["chat"], use_container_width=True):
    st.session_state["chat"] = []
    st.session_state["sid"] = f"console-{lib.now_str()}"
    st.rerun()
if not lib.ready():
    st.info("No usable API key for the selected model. Add one under Settings → Model & API keys.")

if not st.session_state["chat"]:
    c = st.columns(3)
    lib.card(c[0], "📚", "Grounded in evidence", "Answers come from MSHA fatality reports, accident records and the 30 CFR text, with numbered citations.")
    lib.card(c[1], "✅", "Verified in code", "Quotes, dates, CFR sections and numbers of two or more digits are checked against the evidence. Unverified ones are removed and other unsupported sentences are flagged.")
    lib.card(c[2], "🛡️", "Safe by design", "Personal names are redacted (not guaranteed), no speculation about blame, and a clear abstention when the evidence is not enough.")
    lib.section("Try a question")
    tabs = st.tabs(list(CATS))
    for tab, (name, qs) in zip(tabs, CATS.items()):
        with tab:
            for i, ex in enumerate(qs):
                if st.button(ex, key=f"ex_{name}_{i}", use_container_width=True):
                    st.session_state["pending"] = ex
                    if name == GENERAL_TAB:
                        st.session_state["pending_mode"] = "general"   # general examples run in General chat mode
                    st.rerun()
            if name == GENERAL_TAB:
                st.caption("Chat about general mining and workplace-safety topics. The assistant still checks the MSHA records first and cites them; "
                           "if they don't cover the question it answers from general knowledge, clearly labelled and not verified.")

for i, m in enumerate(st.session_state["chat"]):
    with st.chat_message(m["role"], avatar="🧑‍🔧" if m["role"] == "user" else "⛏️"):
        if m["role"] == "user":
            st.write(m["text"])
        else:
            lib.render_result(m["res"], key=f"h{i}", show_trace=trace)

q = st.chat_input("Ask a mining-safety question …" if st.session_state["answer_mode"] == "grounded" else "Ask anything about mining or workplace safety …",
                  disabled=not lib.ready()) or st.session_state.pop("pending", None)
if q:
    st.session_state["chat"].append({"role": "user", "text": q})
    with st.chat_message("user", avatar="🧑‍🔧"):
        st.write(q)
    with st.chat_message("assistant", avatar="⛏️"):
        with st.status("Working …", expanded=True) as s:
            st.write("Planning the search")
            r = lib.ask(q, st.session_state["sid"], mode=st.session_state["answer_mode"])
            s.update(label=f"Done in {r['latency_s']} s", state="complete", expanded=False)
        st.session_state["chat"].append({"role": "assistant", "res": r})
        lib.render_result(r, key=f"h{len(st.session_state['chat']) - 1}", show_trace=trace)
