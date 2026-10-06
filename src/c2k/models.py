"""Data models shared by every stage.

Roles are abstract: ``requester`` (the person asking for help) and ``agent``
(the person answering on behalf of the organisation). ``system`` messages are
ignored by thread reconstruction.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class Message:
    chat_id: str
    msg_id: int
    ts: int                      # unix seconds
    from_id: str
    text: str
    from_role: str = "requester"  # requester | agent | system
    lang: str = "unknown"
    reply_to: Optional[int] = None
    chat_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Message":
        return cls(
            chat_id=str(d["chat_id"]),
            msg_id=int(d["msg_id"]),
            ts=int(d["ts"]),
            from_id=str(d.get("from_id", "")),
            text=(d.get("text") or "").strip(),
            from_role=d.get("from_role") or d.get("role") or "requester",
            lang=d.get("lang") or "unknown",
            reply_to=d.get("reply_to"),
            chat_title=d.get("chat_title", ""),
        )


@dataclass
class Thread:
    """A requester-driven conversation slice inside one chat."""
    thread_id: str
    chat_id: str
    msg_ids: list[int]
    ts_first: int
    ts_last: int
    n_requester: int
    n_agent: int
    lang_majority: str
    requester_text_len: int
    has_substantive_requester_msg: bool
    has_resolution_signal: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Session:
    """Sequential-variant slice: 12h-gap cut + dyad (<=2 participants) rule."""
    session_id: str
    chat_id: str
    msg_ids: list[int]
    ts_first: int
    ts_last: int
    participant_ids: list[str]
    role_first: str
    parent_session_id: Optional[str] = None
    split_idx: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NeedsHelpVerdict:
    thread_id: str
    needs_help: bool
    confidence: str = "medium"            # high | medium | low
    question_paraphrase: Optional[str] = None
    first_help_msg_id: Optional[int] = None
    topic_hint: Optional[str] = None
    reason: str = ""
    sensitive_topic_signal: bool = False   # forces escalation_flag=true downstream

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RawCase:
    """One sub-case extracted from one thread (before clustering)."""
    raw_id: str
    thread_id: str
    chat_id: str
    from_id: str
    topic: str
    case: str
    solution: Optional[str]
    status: str                            # resolved | unresolved | escalated | informational
    original_question: str
    original_question_lang: str
    evidence_msg_ids: list[int]
    msg_ids: list[int]
    ts_first: int
    ts_last: int
    n_agent: int
    n_requester: int
    requester_text_len: int
    escalation_flag: bool
    initiated_by: str = "requester"        # requester | agent_action_triggered
    volatile_kinds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalCase:
    case_id: str
    topic: str
    case: str
    solution: Optional[str]
    status: str
    escalation_flag: bool
    instances_count: int
    first_seen_ts: Optional[int]
    last_seen_ts: Optional[int]
    volatile_kinds: list[str]
    original_questions: list[str]
    question_records: list[dict[str, Any]]   # {text, lang, ts, thread_id}
    raw_ids: list[str]
    member_thread_ids: list[str]
    evidence_msg_ids: list[int]
    cluster_id: str
    related_case_ids: list[str] = field(default_factory=list)
    leads_to_case_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CanonicalCase":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})  # type: ignore[arg-type]


@dataclass
class DropRecord:
    """Every drop is logged — this is what makes the pipeline auditable."""
    stage: str
    key: str            # thread_id or raw_id or case_id
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
