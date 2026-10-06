import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from c2k.models import Message  # noqa: E402


def msg(chat: str, mid: int, ts: int, who: str, text: str, role: str | None = None, reply_to: int | None = None) -> Message:
    role = role or ("agent" if who.startswith("a") else "requester")
    return Message(chat_id=chat, msg_id=mid, ts=ts, from_id=who, text=text, from_role=role, reply_to=reply_to)


@pytest.fixture
def synthetic_messages():
    from make_synthetic import generate
    return [Message.from_dict(d) for d in generate(seed=7, n_conversations=40)]
