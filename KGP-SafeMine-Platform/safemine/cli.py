"""Ask KGP-SafeMine from the terminal:  .venv/bin/python -m safemine.cli "your question" [--trace]"""
import json
import sys
import warnings

warnings.filterwarnings("ignore")

from safemine.agent.orchestrator import Agent  # noqa: E402
from safemine import config  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    q = " ".join(args) or "What root causes did MSHA find for conveyor fatalities at surface mines since 2018?"
    print(f"[LLM: {config.llm_label()}]\n")
    r = Agent().run(q, session_id="cli")
    print(f"STATUS: {r['status']}  latency={r['latency_s']}s  tool_calls={r['tool_calls']}  usage={r['usage']}\n")
    print(r["answer"], "\n")
    for e in r.get("evidence", [])[:8]:
        print(f"  [{e['id']}] {e['label']}")
    if "--trace" in sys.argv:
        print(json.dumps(r["trace"], indent=1, default=str))


if __name__ == "__main__":
    main()
