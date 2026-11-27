# Multi-agent reasoning and verification

`safemine/agents/` replaces the single Planner–Executor–Critic state machine with specialised agents coordinated by a supervisor.
The old state machine is still in `safemine/agent/orchestrator.py` (`AGENT_MODE=legacy`) for comparison and as a fallback.
`Agent.run(query, session_id)` is unchanged, so the UI, the API, the evaluation scripts and the CLI work as before.

## Agents

| Agent | Owns | Actions |
|---|---|---|
| `safety` | input policy: spec rules R1–R7, LLM policy classifier, injection stripping, out-of-snapshot dates | `screen` |
| `planner` | intent, at most four tool steps, output format, deterministic plan corrections | `plan` |
| `retrieval` | `hybrid_search`, `accident_stats`, `record_lookup`; finding the one named incident | `execute_step`, `fetch_named_event` |
| `regulatory` | `cfr_lookup` (as-of-date 30 CFR); standards behind an incident or a brief | `execute_step`, `enrich_standards` |
| `investigation` | named-incident grounding, premise checks, report-not-published (A2), cited drafting (answers and briefs) | `ground_incident`, `draft` |
| `validator` | citation repair, claim verification, grounding score, hallucination stripping, best-draft and remainder rules, claim map | `validate`, `salvage`, `sanitize`, `claim_map` |
| `critic` | accept / revise / abstain, with a deterministic support floor (below 0.6 is never accepted); may request two extra steps | `review` |
| `report` | final assembly: notes, answer-policy gate, name filter, human-review flag | `compose`, `not_accepted`, `no_evidence` |
| `supervisor` | control flow, delegation, global limits, error policy | `run` |

## Flow

```
safety.screen -> planner.plan -> dispatch steps (retrieval | regulatory, in plan order)
  -> regulatory.enrich_standards -> investigation.ground_incident (named incidents only)
  -> refine loop: investigation.draft -> validator.validate -> critic.review
                  (revise: extra steps go back to the owning agent; at most MAX_REVISIONS + 1 rounds, 2 for a brief)
  -> validator.salvage -> validator.sanitize -> report.compose
```

Agents delegate to each other through `ctx.call(sender, recipient, action, ...)`, for example the investigation agent asks the
retrieval agent for a named event, and the regulatory agent asks retrieval for an incident's enforcement chunks.

## Inter-agent communication

* `TaskContext` (`context.py`) holds all state of one request and is passed explicitly. Agents are stateless, so concurrent
  requests do not interfere.
* Every delegation is a typed `Message` (task / result / error) on a per-request `MessageBus` (`messages.py`). The bus becomes
  `res["agent_trail"]` and is shown in the UI ("Agent messages"), written to `traces.jsonl` and sent to Langfuse.
* `BaseAgent.invoke` is the only way to call an agent. It records the messages, times the call and turns an unexpected exception into an
  `AgentError` result.

## Error handling

| Failure | Behaviour |
|---|---|
| tool raises, bad tool arguments | one repair attempt, then a `tool_error` trace event; the run continues with the other evidence |
| planner model or agent fails | deterministic heuristic plan |
| critic model or agent fails | deterministic critic (support ratio decides) |
| draft call fails (bad JSON, budget, network) | best earlier verified draft, otherwise abstain |
| API key rejected (401/403) | an explicit error answer naming the key |
| **validator fails** | **fail closed: abstain** (an unverified draft is never released) |
| **report agent fails** | **fail closed: abstain** (`report_failed`) |
| incident grounding fails | abstain (`incident_grounding_failed`) |
| wall clock exceeds `AGENT_DEADLINE_S` (default 420 s) | stop refining, abstain (`deadline`) |
| any other exception | abstain with `internal_error`; the user never sees a traceback |

Global limits: `MAX_STEPS` tool calls (10), `MAX_REVISIONS` critic rounds (2), `TOKEN_BUDGET` (12,000; 24,000 for a brief).

## Citation accuracy, factual consistency, traceability

* Deterministic checks (no model): every `[E#]` exists; quotes are verbatim; numbers, dates and CFR sections appear in the cited evidence;
  factual sentences are cited. **Numbers now match as whole numbers**: "20" is no longer verified by "2019" or "56.14211" (it was a
  substring test before, which accepted an invented "20 years").
* **Claim map** (`res["claim_map"]`): every factual sentence of the final answer, its citations, verdict, and its sources
  (event, chunk, report file). **Verification report** (`res["verification_report"]`): claims, supported, unsupported, uncited,
  weakly supported, removed, drafting rounds, support ratio, traceability (share of claims with a citation), mean grounding.
  Notes the system itself appends (coverage, caveat, premise lines) are not counted as model claims.
* **Grounding score**: share of a sentence's content words found in its cited evidence. A soft signal that catches a cited but
  unrelated sentence with no number to check. On 972 cited sentences from stored answers the median was 0.86, 7% fell below 0.5 and 4.4%
  below 0.35. Claims below 0.5 are flagged "weak support" in the UI. With `AGENT_STRICT_GROUNDING=true` a cited sentence below
  `AGENT_GROUNDING_MIN` (0.35) counts as unsupported; this is off by default and has not been benchmarked.

## Safety and human review (unchanged)

Input rules and classifier, injection stripping, answer-level policy check, name filter, the "report not published" abstention,
non-blocking human-review flag (approve / flag / reject), and DRAFT marking in exports all run as before.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_MODE` | `multi` | `legacy` runs the original single state machine |
| `AGENT_DEADLINE_S` | 420 | wall-clock limit per question, 0 = none |
| `AGENT_STRICT_GROUNDING` | false | weakly grounded cited sentences count as unsupported |
| `AGENT_GROUNDING_MIN` | 0.35 | threshold for the strict mode |

## Tests

```powershell
..\.venv\Scripts\python -m pytest tests -q
```

The full suite has 243 tests; some need the built data, the models and a login file (see the README). The multi-agent tests
(`tests/test_agents.py`) need no network and no key (a scripted fake model and fake tools); three of them also need the built indexes. They cover the message bus, base agent error handling, agent
coordination order, safety refusals, hallucination stripping, refinement bounds, every failure mode in the table above, the claim map
and grounding score, and that `legacy` and `multi` produce identical results on the same inputs.

## Extending

To add an agent: subclass `BaseAgent` (`name`, actions taking `(ctx, ...)`), register it in `Supervisor.__init__`, and call it from the
pipeline or from another agent with `ctx.call`. To add a tool: add it to `orchestrator.TOOLS`, list it in the owning agent's `OWNS` and in
`supervisor.TOOL_OWNER`.
