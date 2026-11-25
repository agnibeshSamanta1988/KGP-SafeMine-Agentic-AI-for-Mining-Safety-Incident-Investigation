import streamlit as st

from app import lib
from safemine import config, tracing

lib.hero("Settings", "Choose the model, manage API keys, tune generation, and check system health. Changes apply to the next question.")
t1, t2, t3 = st.tabs(["🤖 Model & API keys", "🎛️ Generation", "🩺 System health"])
ORDER = list(lib.LABELS)


def mask(key: str) -> str:
    return "not set" if not key or "REPLACE" in key else "•••• " + key[-4:]


with t1:
    st.markdown("##### Active model")
    cur = st.session_state["provider"]
    pick = st.radio("Provider", ORDER, index=ORDER.index(cur), format_func=lambda k: lib.LABELS[k], horizontal=True,
                    label_visibility="collapsed")
    if pick != "upgrad":
        st.markdown('<div class="sm-note">Qwen3-8B is the default and the model all reported results were measured on. Other providers are '
                    'optional: answers and safety behaviour have not been evaluated on them.</div>', unsafe_allow_html=True)
    st.write("")
    st.markdown("##### API keys & models")
    st.caption("Keys are held in memory for this session. 'Save and apply' also writes them to the local .env file (plain text, "
               "keep that file private).")
    new = {}
    for name in ORDER:
        p = config.PROVIDERS[name]
        ready = config.provider_ready(name) or (name != "upgrad" and bool(p["api_key"]))
        with st.expander(f"{lib.LABELS[name]}   ·   key {mask(p['api_key'])}", expanded=(name == pick)):
            c1, c2 = st.columns([3, 2])
            key = c1.text_input("API key", type="password", key=f"k_{name}", placeholder="paste to set or replace",
                                help=None if name == "upgrad" else f"Stored as {lib.KEY_ENV[name]}")
            model = c2.text_input("Model", value=p["model"], key=f"m_{name}")
            if name != "upgrad":
                url = st.text_input("Base URL (advanced)", value=p["base_url"], key=f"u_{name}")
            else:
                url = p["base_url"]
            new[name] = (key.strip(), model.strip(), url.strip())
    st.write("")
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Save and apply", type="primary"):
        upd = {"LLM_PROVIDER": pick}
        for name, (key, model, url) in new.items():
            pr = config.PROVIDERS[name]
            if key:
                pr["api_key"] = key
                upd[lib.KEY_ENV[name]] = key
            if model:
                pr["model"] = model
                upd[lib.MODEL_ENV[name]] = model
            if url and url != pr["base_url"] and name != "upgrad":
                pr["base_url"] = url
                upd[f"{lib.KEY_ENV[name].split('_API_KEY')[0]}_BASE_URL"] = url
        st.session_state["provider"] = pick
        config.set_provider(pick)
        upd["LLM_TEMPERATURE"] = st.session_state["temperature"]
        lib.save_env(upd)
        st.success(f"Saved. Now using {config.llm_label()}.")
    if b2.button("Test connection"):
        config.set_provider(pick)
        if not (config.PROVIDERS[pick]["api_key"] and not "REPLACE" in config.PROVIDERS[pick]["api_key"]):
            st.warning("No key for this provider yet. Save one first.")
        else:
            try:
                from safemine.agent.llm import get_llm
                out = get_llm().chat([{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=12)
                st.success(f"Connected to {config.llm_label()}: {out[:40]}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Connection failed: {str(e)[:200]}")

with t2:
    st.markdown("##### Temperature")
    t = st.slider("Temperature", 0.0, 1.0, step=0.05, key="temperature",
                  help="0 = most deterministic and repeatable; 1 = more varied. Default 0.1.")
    config.TEMPERATURE = float(t)
    st.caption("Applied to every model call (planner, writer, verifier, safety classifier). Low values keep cited answers stable; "
               "the reported results used 0.1.")
    if t > 0.5:
        st.warning("High temperature makes citations and structured JSON less reliable on a small model.")
    st.markdown("##### Rate limiting")
    st.toggle("Pause between LLM calls", key="sleep_on", help="Keeps under free-tier limits. Each question makes 3-8 calls.")
    st.slider("Seconds between calls", 0.5, 10.0, step=0.5, key="sleep_s", disabled=not st.session_state.get("sleep_on", True))
    if st.button("Save generation settings"):
        lib.save_env({"LLM_TEMPERATURE": st.session_state["temperature"], "LLM_SLEEP_ENABLED": str(st.session_state["sleep_on"]).lower(),
                      "LLM_SLEEP_SECONDS": st.session_state["sleep_s"]})
        st.success("Saved.")
    st.markdown("##### Tracing (Langfuse)")
    tr = tracing.status()
    if not tr["enabled"]:
        st.toggle("Send traces to Langfuse", key="trace_on", disabled=True,
                  help="Add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to .env (and LANGFUSE_HOST) to enable tracing.")
        st.caption("No Langfuse keys in .env, so tracing is off. Questions are still saved to the local history and traces.jsonl.")
    else:
        on = st.toggle("Send traces to Langfuse", key="trace_on",
                       help="Off stops sending traces at once, to save the Langfuse free-tier quota. The local history "
                            "(Review Queue, dashboard) and data_processed/traces.jsonl are always kept. "
                            "Turn it back on, or replay later: python -m safemine.tracing replay")
        tracing.set_enabled(on)
        if not on:
            st.info("Tracing is paused: questions are NOT sent to Langfuse (local history is still kept).")
        elif tr.get("reachable") is None:
            st.caption(f"Checking the connection to {tr['host']} …")
        elif not tr.get("reachable"):
            st.error(f"Langfuse at {tr['host']} is not reachable: traces are not being recorded.")
        elif tr.get("auth") is False:
            st.error("Langfuse rejected the keys. Check LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY and the region in LANGFUSE_HOST "
                     "(EU https://cloud.langfuse.com, US https://us.cloud.langfuse.com).")
        else:
            st.success("Tracing is on.")
        last = st.session_state.get("last_turn_id")
        url = tracing.trace_url(last) if (on and last) else None
        if url:
            st.markdown(f"[Open the trace of your last question in Langfuse]({url})")
    if st.button("Save tracing setting", disabled=not tr["enabled"],
                 help="Makes the current on/off choice the default next time the app starts (LANGFUSE_ENABLED in .env)."):
        lib.save_env({"LANGFUSE_ENABLED": str(bool(st.session_state.get("trace_on"))).lower()})
        st.success("Saved.")
    st.markdown("##### Agent limits (read-only)")
    a = st.columns(3)
    lib.kpi(a[0], "Max steps", config.MAX_STEPS, "per question")
    lib.kpi(a[1], "Max revisions", config.MAX_REVISIONS, "critic loops")
    lib.kpi(a[2], "Token budget", f"{config.TOKEN_BUDGET:,}", "per question (x2 for briefs)")
    st.caption("Retrieval: BM25 + dense fusion, cross-encoder rerank, 6–8 evidence chunks. Set limits in .env.")

with t3:
    probs = config.startup_checks()
    if not probs:
        st.success("All checks passed.")
    for p in probs:
        st.error(p)
    st.caption(f"Data folder: {config.OUT}  ·  Active: {config.llm_label()}  ·  Temperature {config.TEMPERATURE}")
