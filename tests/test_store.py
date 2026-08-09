from __future__ import annotations

from lumina.store import SessionStore
from lumina.types import Message, ToolCall


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
