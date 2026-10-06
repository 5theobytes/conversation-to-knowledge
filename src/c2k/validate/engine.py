"""Rule engine for post-LLM validation.

A rule is ``fn(case: dict, ctx: RuleContext) -> (keep: bool, reason: str)``.
Rules are evaluated in registration order; the first failing rule decides the
drop (cheap regex rules go first, grounding rules that need the message slice
go last). ``explain=True`` evaluates every rule and returns the full trace,
which is what the demo prints as the evidence trail.

Design notes carried over from the production run:
* rules are versioned by name (``_v2``...) and never silently changed:
  disabled rules stay in the registry with ``enabled=False``;
* each rule names its driver (the error class it was added for);
* the engine is a safety net; most of the same constraints are ALSO in the
  worker prompts, because a filter that drops half of the output is a sign
  the prompt is wrong, not a success.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..models import Message

RuleFn = Callable[[dict[str, Any], "RuleContext"], tuple[bool, str]]


@dataclass
class RuleContext:
    messages: dict[int, Message] = field(default_factory=dict)   # msg_id -> Message (the slice)
    known_names: list[str] = field(default_factory=list)
    sensitive_topics: set[str] = field(default_factory=set)
    substantive_keywords: list[str] = field(default_factory=list)


@dataclass
class Rule:
    name: str
    fn: RuleFn
    driver: str = ""
    enabled: bool = True


@dataclass
class Verdict:
    keep: bool
    failed_rule: str | None
    reason: str
    trace: list[tuple[str, bool, str]] = field(default_factory=list)


class RuleEngine:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules: list[Rule] = list(rules or [])

    def add(self, name: str, fn: RuleFn, driver: str = "", enabled: bool = True, before: str | None = None) -> None:
        r = Rule(name, fn, driver, enabled)
        if before:
            idx = next((i for i, x in enumerate(self.rules) if x.name == before), None)
            if idx is not None:
                self.rules.insert(idx, r)
                return
        self.rules.append(r)

    def disable(self, name: str) -> None:
        for r in self.rules:
            if r.name == name:
                r.enabled = False

    def names(self, enabled_only: bool = True) -> list[str]:
        return [r.name for r in self.rules if r.enabled or not enabled_only]

    def evaluate(self, case: dict[str, Any], ctx: RuleContext | None = None, explain: bool = False) -> Verdict:
        ctx = ctx or RuleContext()
        trace: list[tuple[str, bool, str]] = []
        failed: tuple[str, str] | None = None
        for r in self.rules:
            if not r.enabled:
                continue
            ok, reason = r.fn(case, ctx)
            trace.append((r.name, ok, reason))
            if not ok and failed is None:
                failed = (r.name, reason)
                if not explain:
                    break
        if failed:
            return Verdict(False, failed[0], f"{failed[0]}: {failed[1]}", trace)
        return Verdict(True, None, "", trace)

    def filter(self, cases: list[dict[str, Any]], ctx: RuleContext | None = None
               ) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], Verdict]]]:
        kept, dropped = [], []
        for c in cases:
            v = self.evaluate(c, ctx)
            (kept if v.keep else dropped).append(c if v.keep else (c, v))  # type: ignore[arg-type]
        return kept, dropped
