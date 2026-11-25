"""LLM client for the Track B OpenAI-compatible endpoint (Qwen3-8B), with the small-model safety net:

* JSON mode requested, then pydantic validation; on failure ONE repair retry with the validation error,
  then raise LLMFormatError (the orchestrator turns that into an abstention, never a crash).
* Qwen3 "thinking" disabled for Planner/Critic (chat_template_kwargs + /no_think), <think> blocks stripped.
* Token accounting per query, enforced against TOKEN_BUDGET.
* If no endpoint/key is configured, MockLLM is used so the whole pipeline still runs offline.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from safemine import config

T = TypeVar("T", bound=BaseModel)


class LLMFormatError(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def extract_json(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        return m.group(1)
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i >= 0 and j > i else text


class Usage:
    def __init__(self):
        self.prompt = self.completion = self.calls = 0
        self.latency = self.slept = 0.0
        self.provider = ""
        self.log: list[dict] = []   # one entry per LLM call (role, timing, tokens, short input/output) -> one Langfuse generation each

    def as_dict(self):
        return {"provider": self.provider, "llm_calls": self.calls, "prompt_tokens": self.prompt,
                "completion_tokens": self.completion, "llm_latency_s": round(self.latency, 2),
                "rate_limit_sleep_s": round(self.slept, 2)}


_SEMAPHORES: dict[str, threading.Semaphore] = {}
_PACE_LOCK = threading.Lock()
_LAST_CALL = {"t": 0.0}


def pace() -> float:
    """Sleep so consecutive LLM calls start at least LLM_SLEEP_SECONDS apart (toggle: LLM_SLEEP_ENABLED / UI).
    Returns the seconds slept."""
    if not config.LLM_SLEEP_ENABLED or config.LLM_SLEEP_SECONDS <= 0:
        return 0.0
    with _PACE_LOCK:
        wait = _LAST_CALL["t"] + config.LLM_SLEEP_SECONDS - time.time()
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL["t"] = time.time()
        return max(0.0, wait)


class LLM:
    is_mock = False

    def __init__(self, usage: Usage | None = None):
        import httpx
        from openai import OpenAI
        # upGrad endpoint uses a self-signed cert: verify against the group's .crt (never verify=False)
        http = httpx.Client(verify=config.LLM_CA_CERT, timeout=120) if config.LLM_CA_CERT else None
        # max_retries: the SDK backs off on 429 / 5xx (both providers rate-limit)
        self.client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, timeout=120, max_retries=4,
                             http_client=http)
        self.model = config.LLM_MODEL
        self.provider = config.P
        self.sem = _SEMAPHORES.setdefault(config.LLM_PROVIDER, threading.Semaphore(self.provider["max_concurrent"]))
        self.usage = usage or Usage()
        self.usage.provider = config.LLM_PROVIDER

    def chat(self, messages: list[dict], max_tokens: int = 800, temperature: float | None = None, json_mode: bool = False,
             no_think: bool = True) -> str:
        limit = getattr(self.usage, "budget", None) or config.TOKEN_BUDGET
        if self.usage.prompt + self.usage.completion > limit:
            raise BudgetExceeded(f"token budget {limit} exhausted")
        msgs = [dict(m) for m in messages]
        if no_think and config.LLM_DISABLE_THINKING and self.provider["no_think_tag"] and msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += "\n/no_think"
        max_tokens = min(max_tokens, self.provider["max_tokens_cap"])
        kw = dict(model=self.model, messages=msgs, max_tokens=max_tokens,
                  temperature=config.TEMPERATURE if temperature is None else temperature)
        extra = dict(self.provider["extra_body"]) if config.LLM_DISABLE_THINKING else {}
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        # context guard: prompt + max_tokens must fit the provider window (8,192 on upGrad)
        est_prompt = sum(len(m["content"]) for m in msgs) // 3 + 50
        room = self.provider["context_window"] - est_prompt
        if room < 64:
            raise BudgetExceeded(f"prompt (~{est_prompt} tok) does not fit the {self.provider['context_window']} context window")
        kw["max_tokens"] = min(kw["max_tokens"], room)
        self.usage.slept += pace()   # rate-limit pause (not counted as model latency)
        t = time.time()
        self.sem.acquire()  # upGrad allows 1 active request per key: queue instead of getting 429
        try:
            r = self._create(kw, extra)
        finally:
            self.sem.release()
        t_end = time.time()
        self.usage.latency += t_end - t
        self.usage.calls += 1
        if r.usage:
            self.usage.prompt += r.usage.prompt_tokens or 0
            self.usage.completion += r.usage.completion_tokens or 0
        text = re.sub(r"<think>.*?</think>", "", r.choices[0].message.content or "", flags=re.S).strip()
        try:
            self.usage.log.append({"name": call_role(msgs), "start": t, "end": t_end, "model": self.model,
                                   "prompt_tokens": (r.usage.prompt_tokens or 0) if r.usage else 0,
                                   "completion_tokens": (r.usage.completion_tokens or 0) if r.usage else 0,
                                   "input": next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")[:1500],
                                   "output": text[:1500], "json_mode": json_mode})
        except Exception:  # noqa: BLE001  bookkeeping must never break an answer
            pass
        return text

    def _create(self, kw, extra):
        try:
            return self.client.chat.completions.create(**kw, extra_body=extra or None)
        except Exception as e:  # noqa: BLE001
            # auth / connection errors are real failures; only retry plain on a 400 about unsupported params
            if getattr(e, "status_code", None) != 400:
                raise
            kw.pop("response_format", None)
            return self.client.chat.completions.create(**kw, extra_body=extra or None)

    def chat_json(self, messages: list[dict], schema: Type[T], max_tokens: int = 600) -> T:
        raw = self.chat(messages, max_tokens=max_tokens, json_mode=True)
        try:
            return schema.model_validate_json(extract_json(raw))
        except (ValidationError, ValueError) as e:
            repair = messages + [{"role": "assistant", "content": raw},
                                 {"role": "user", "content": f"That was not valid JSON for the schema. Error: {str(e)[:400]}\n"
                                                             f"Reply with ONLY the corrected JSON object."}]
            raw2 = self.chat(repair, max_tokens=max_tokens, json_mode=True)
            try:
                return schema.model_validate_json(extract_json(raw2))
            except (ValidationError, ValueError) as e2:
                if "answer" in schema.model_fields:
                    text = salvage_answer(raw2) or salvage_answer(raw)
                    if text:
                        return schema.model_validate({"answer": text})
                raise LLMFormatError(str(e2)[:300]) from e2


_ROLE = re.compile(r"You are the ([A-Za-z/ -]{3,40}?) (?:of|for) KGP-SafeMine", re.I)


def call_role(msgs: list[dict]) -> str:
    """'Planner', 'Executor/Writer', 'Critic', 'safety gate' ... from the system prompt's first line (for the trace dashboard)."""
    sys_msg = next((m["content"] for m in msgs if m.get("role") == "system"), "")
    m = _ROLE.search(sys_msg[:300])
    return ("llm: " + m.group(1).strip()) if m else ("llm: repair retry" if len(msgs) > 2 and msgs[-1].get("role") == "user"
                                                     and "not valid JSON" in msgs[-1].get("content", "") else "llm")


def salvage_answer(raw: str) -> str | None:
    """The endpoint caps output at 1,024 tokens, so a long answer can be cut off mid-JSON ("EOF while parsing a string"). Recover
    the text written so far: take the "answer" string, unescape it, and cut it back to the last complete sentence or citation."""
    m = re.search(r'"answer"\s*:\s*"(.*)', raw, flags=re.S)
    if not m:
        return None
    body = m.group(1)
    body = re.split(r'",\s*"(?:insufficient_evidence|missing)"', body)[0]          # a complete answer ends before the next key
    body = body.rstrip().rstrip('"}').replace('\\n', "\n").replace('\\"', '"')
    cut = max(body.rfind(". "), body.rfind(".\n"), body.rfind("]."), body.rfind("]\n"), body.rfind(". ["))
    if cut > 80:
        body = body[:cut + 1]
    return body.strip() if len(body.strip()) > 80 else None


def get_llm(usage: Usage | None = None):
    if config.llm_configured():
        return LLM(usage)
    from safemine.agent.mock_llm import MockLLM
    return MockLLM(usage or Usage())
