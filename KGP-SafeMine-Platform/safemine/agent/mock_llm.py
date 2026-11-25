"""Offline stand-in used until LLM_BASE_URL / LLM_API_KEY are set in .env.
The orchestrator routes each role to safemine.agent.heuristics when llm.is_mock is True."""


class MockLLM:
    is_mock = True

    def __init__(self, usage):
        self.usage = usage
