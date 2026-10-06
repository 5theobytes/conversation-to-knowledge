from conftest import msg

from c2k.normalize.lang import detect_lang, is_ack_or_greeting_or_emoji, is_all_cyrillic
from c2k.normalize.sessions import cut_sessions
from c2k.normalize.threads import build_threads


def test_detect_lang_scripts():
    assert detect_lang("สวัสดีค่ะ wifi ใช้ไม่ได้") == "th"
    assert detect_lang("\u0410\u0411\u0412") == "ru"
    assert detect_lang("wifi is down") == "en"
    assert detect_lang("") == "unknown"


def test_ack_and_greeting_detection():
    for t in ["ok", "Thanks!", "Thank you", "ขอบคุณค่ะ", "Hi", "Hello", "👍", ""]:
        assert is_ack_or_greeting_or_emoji(t), t
    for t in ["ok the printer is broken", "wifi not working", "I lost my card"]:
        assert not is_ack_or_greeting_or_emoji(t), t


def test_is_all_cyrillic():
    assert is_all_cyrillic("\u0410\u0411\u0412")
    assert not is_all_cyrillic("\u0410\u0411 wifi")
    assert not is_all_cyrillic("123")


def test_thread_opens_on_requester_and_agent_cannot_open():
    msgs = [
        msg("c", 1, 1000, "a1", "Reminder: send your ID photo"),      # agent-only, no open thread -> ignored
        msg("c", 2, 2000, "u1", "hello"),
        msg("c", 3, 2010, "u1", "my printer is jammed"),
        msg("c", 4, 2100, "a1", "On it"),
        msg("c", 5, 2500, "u1", "thanks"),
    ]
    th = build_threads(msgs)
    assert len(th) == 1
    t = th[0]
    assert t.msg_ids == [2, 3, 4, 5]
    assert t.thread_id == "c:2"
    assert t.n_requester == 3 and t.n_agent == 1
    assert t.has_substantive_requester_msg
    assert t.has_resolution_signal


def test_thread_closes_after_ack_silence_and_hard_gap():
    msgs = [
        msg("c", 1, 0, "u1", "wifi down"),
        msg("c", 2, 60, "a1", "reconnect please"),
        msg("c", 3, 120, "u1", "ok thanks"),
        msg("c", 4, 120 + 31 * 60, "u1", "now the printer is broken"),   # 31 min after ack -> new thread
        msg("c", 5, 120 + 31 * 60 + 13 * 3600, "u1", "and the coffee machine"),  # >12h -> new thread
    ]
    th = build_threads(msgs)
    assert [t.msg_ids for t in th] == [[1, 2, 3], [4], [5]]


def test_thread_glues_consecutive_requester_messages():
    msgs = [msg("c", 1, 0, "u1", "hello"), msg("c", 2, 5, "u1", "my card"), msg("c", 3, 9, "u1", "does not work")]
    th = build_threads(msgs)
    assert len(th) == 1 and th[0].msg_ids == [1, 2, 3]


def test_sessions_gap_and_dyad_split():
    msgs = [
        msg("g", 1, 0, "u1", "question one"),
        msg("g", 2, 10, "a1", "answer"),
        msg("g", 3, 20, "u2", "unrelated question from another member"),   # 3rd sender, no overlap -> split
        msg("g", 4, 30, "a2", "answer two"),                                # a new agent, still a dyad
        msg("g", 5, 30 + 13 * 3600, "u1", "next day question"),            # 12h gap -> new session
    ]
    sessions, drops = cut_sessions(msgs)
    assert not drops
    assert [s.msg_ids for s in sessions] == [[1, 2], [3, 4], [5]]
    assert sessions[1].parent_session_id == "g:1" and sessions[1].split_idx == 1


def test_sessions_multi_overlap_dropped():
    msgs = [
        msg("g", 1, 0, "u1", "q"), msg("g", 2, 10, "u2", "q2"), msg("g", 3, 20, "a1", "a"),
        msg("g", 4, 30, "u1", "follow-up"),   # u1 speaks after 3rd sender -> interleaved
    ]
    sessions, drops = cut_sessions(msgs)
    assert sessions == []
    assert drops and drops[0].reason == "multi_overlap"
