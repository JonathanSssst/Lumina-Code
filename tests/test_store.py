from __future__ import annotations

from lumina.store import SessionStore
from lumina.types import Message, ToolCall, Usage


def _make_store(tmp_path):
    return SessionStore(tmp_path / ".lumina" / "sessions.db")


def test_create_and_list_session(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path, "测试会话")
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].id == sid
    assert sessions[0].title == "测试会话"
    store.close()


def test_append_and_get_messages_roundtrip(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path)

    store.append_message(sid, Message(role="user", content="你好"))
    store.append_message(
        sid,
        Message(
            role="assistant",
            content="我来读取",
            tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "x.py"})],
        ),
    )
    store.append_message(sid, Message(role="tool", tool_call_id="t1", name="read_file", content="内容"))

    msgs = store.get_messages(sid)
    assert [m.role for m in msgs] == ["user", "assistant", "tool"]
    assert msgs[1].tool_calls[0].name == "read_file"
    assert msgs[1].tool_calls[0].arguments == {"path": "x.py"}
    assert msgs[2].tool_call_id == "t1"
    store.close()


def test_list_sessions_filtered_by_workspace(tmp_path):
    store = _make_store(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    store.create_session(tmp_path)
    store.create_session(other)
    assert len(store.list_sessions(tmp_path)) == 1
    assert len(store.list_sessions(other)) == 1
    assert len(store.list_sessions()) == 2
    store.close()


def test_delete_session_cascades(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path)
    store.append_message(sid, Message(role="user", content="x"))
    store.delete_session(sid)
    assert store.get_session(sid) is None
    assert store.get_messages(sid) == []
    store.close()


def test_set_title_and_touch(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path)
    store.set_title(sid, "新标题")
    assert store.get_session(sid).title == "新标题"
    store.close()


def test_truncate_after_user(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path)

    store.append_message(sid, Message(role="user", content="第一问"))
    store.append_message(sid, Message(role="assistant", content="第一个回答"))
    store.append_message(sid, Message(role="tool", tool_call_id="t1", name="read_file", content="内容"))
    store.append_message(sid, Message(role="user", content="第二问"))
    store.append_message(sid, Message(role="assistant", content="第二个回答"))

    assert store.truncate_after_user(sid, 1) is True
    assert [m.role for m in store.get_messages(sid)] == ["user", "assistant", "tool"]
    assert [m.content for m in store.get_messages(sid) if m.role == "user"] == ["第一问"]

    store.append_message(sid, Message(role="user", content="改后第二问"))
    assert [m.content for m in store.get_messages(sid) if m.role == "user"] == ["第一问", "改后第二问"]
    store.close()


def test_truncate_after_user_invalid_index(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path)
    store.append_message(sid, Message(role="user", content="x"))
    assert store.truncate_after_user(sid, 5) is False
    assert store.truncate_after_user(sid, -1) is False
    assert len(store.get_messages(sid)) == 1
    store.close()


def test_record_usage_accumulates_across_runs(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path)

    store.record_usage(
        sid,
        Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150, reasoning_tokens=20, cached_tokens=10),
        iterations=2,
        tool_calls=1,
    )
    store.record_usage(
        sid,
        Usage(prompt_tokens=200, completion_tokens=100, total_tokens=300, reasoning_tokens=0, cached_tokens=0),
        iterations=1,
        tool_calls=0,
    )

    usage = store.get_session_usage(sid)
    assert usage.total_tokens == 450
    assert usage.prompt_tokens == 300
    assert usage.completion_tokens == 150
    assert usage.reasoning_tokens == 20
    assert usage.cached_tokens == 10
    assert store.get_session_usage(sid + 999) is None
    store.close()


def test_get_session_stats_counts_and_usage(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path, "统计会话")
    store.append_message(sid, Message(role="user", content="q"))
    store.append_message(sid, Message(role="assistant", content="a"))
    store.append_message(sid, Message(role="tool", tool_call_id="t1", name="x", content="r"))
    store.record_usage(sid, Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15), iterations=1, tool_calls=1)

    stats = store.get_session_stats(sid)
    assert stats["title"] == "统计会话"
    assert stats["messages"] == 3
    assert stats["counts"] == {"user": 1, "assistant": 1, "tool": 1, "system": 0}
    assert stats["usage"]["total"] == 15
    assert stats["iterations"] == 1
    assert stats["tool_calls"] == 1
    store.close()


def test_delete_session_clears_usage(tmp_path):
    store = _make_store(tmp_path)
    sid = store.create_session(tmp_path)
    store.record_usage(sid, Usage(total_tokens=5))
    store.delete_session(sid)
    assert store.get_session_usage(sid) is None
    store.close()
