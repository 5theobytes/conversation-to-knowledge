"""LLM provider interface.

Every LLM-backed stage builds a ``system`` prompt (from ``agents/*.md``) and a
``user`` payload (JSON) and calls ``provider.complete_json(system, user)``.

* ``MockLLM`` is the default: a deterministic, keyword-driven stand-in that
  lets the whole pipeline run offline. It is NOT a model; its purpose is to
  exercise the deterministic parts (threads, clustering, rule engine, graph,
  retrieval) end to end and to document the contract each real model call
  must satisfy.
* ``AnthropicLLM`` is a thin adapter for a real model (optional dependency).
  It is intentionally not wired into the demo.

The task a prompt belongs to is declared by a ``<!-- task: NAME -->`` line in
the prompt file; the mock dispatches on it.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Protocol

TASK_RE = re.compile(r"<!--\s*task:\s*([a-z_]+)\s*-->")


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str: ...

    def complete_json(self, system: str, user: str, max_tokens: int = 1024) -> dict[str, Any]: ...


def parse_task(system: str) -> str:
    m = TASK_RE.search(system or "")
    return m.group(1) if m else "unknown"


def extract_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction (strips code fences, finds outermost braces)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b < a:
            raise
        return json.loads(t[a:b + 1])


class MockLLM:
    """Deterministic stand-in. Handlers are registered per task name."""

    name = "mock"

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        from . import mock_handlers  # noqa: WPS433 (registers defaults)
        mock_handlers.register_all(self)

    def register(self, task: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._handlers[task] = fn

    def complete_json(self, system: str, user: str, max_tokens: int = 1024) -> dict[str, Any]:
        task = parse_task(system)
        payload = json.loads(user) if user.strip().startswith("{") else {"text": user}
        self.calls.append((task, payload))
        fn = self._handlers.get(task)
        if fn is None:
            raise KeyError(f"MockLLM has no handler for task={task!r}")
        return fn(payload)

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        return json.dumps(self.complete_json(system, user, max_tokens), ensure_ascii=False)


class AnthropicLLM:
    """Adapter for a real model. Requires the optional ``anthropic`` package."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, temperature: float = 0.0) -> None:
        from anthropic import Anthropic  # type: ignore
        self._client = Anthropic(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        resp = self._client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=self.temperature,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content)

    def complete_json(self, system: str, user: str, max_tokens: int = 1024) -> dict[str, Any]:
        return extract_json(self.complete(system, user, max_tokens))
