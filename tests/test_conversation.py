"""
Tests for ConversationStore and conversation exporters.
"""

import os
import pytest
import tempfile

from shopsage.history.conversation_store import ConversationStore
from shopsage.history.exporter import export_to_json, export_to_csv, export_to_markdown


@pytest.fixture
def store(tmp_path):
    """Create a ConversationStore with a temporary DB."""
    db_file = tmp_path / "test_conv.db"
    return ConversationStore(db_path=str(db_file))


def test_save_and_retrieve_message(store):
    """Messages should be saved and retrievable."""
    msg = store.save_message("sess-1", "user", "hello world", "chitchat")
    assert msg.role == "user"
    assert msg.content == "hello world"

    history = store.get_history("sess-1")
    assert len(history) == 1
    assert history[0].content == "hello world"


def test_save_exchange(store):
    """save_exchange should create a user + assistant pair."""
    user_msg, ai_msg = store.save_exchange(
        "sess-2", "find me shoes", "Here are some shoes!", "shopping"
    )
    assert user_msg.role == "user"
    assert ai_msg.role == "assistant"

    history = store.get_history("sess-2")
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"


def test_get_recent_context(store):
    """get_recent_context should return a formatted context string."""
    store.save_exchange("sess-3", "hi", "hello!", "chitchat")
    store.save_exchange("sess-3", "red shoes", "Here are red shoes", "shopping")

    ctx = store.get_recent_context("sess-3", n_messages=4)
    assert "User: hi" in ctx
    assert "ShopSage: hello!" in ctx
    assert "User: red shoes" in ctx


def test_search_history(store):
    """search_history should find messages matching a query."""
    store.save_exchange("sess-4", "Nike air max", "Here are Nike options", "shopping")
    store.save_exchange("sess-4", "Adidas shoes", "Here are Adidas shoes", "shopping")

    results = store.search_history("sess-4", "Nike")
    assert len(results) >= 1
    assert any("Nike" in m.content for m in results)


def test_session_stats(store):
    """get_session_stats should return correct counts."""
    store.save_exchange("sess-5", "msg1", "resp1", "chitchat")
    store.save_exchange("sess-5", "msg2", "resp2", "shopping")

    stats = store.get_session_stats("sess-5")
    assert stats["message_count"] == 4


def test_delete_session(store):
    """delete_session should remove all messages."""
    store.save_exchange("sess-6", "test", "response", "chitchat")
    assert len(store.get_history("sess-6")) == 2

    count = store.delete_session("sess-6")
    assert count == 2
    assert len(store.get_history("sess-6")) == 0


def test_list_sessions(store):
    """list_sessions should return all active sessions."""
    store.save_message("sess-a", "user", "hello", "chitchat")
    store.save_message("sess-b", "user", "world", "chitchat")

    sessions = store.list_sessions()
    ids = [s["session_id"] for s in sessions]
    assert "sess-a" in ids
    assert "sess-b" in ids


def test_export_json(store):
    """export_to_json should return valid JSON."""
    store.save_exchange("sess-7", "test msg", "test response", "shopping")
    messages = store.get_history("sess-7")
    result = export_to_json(messages)
    assert '"shopsage_conversation_v1"' in result
    assert "test msg" in result


def test_export_csv(store):
    """export_to_csv should return CSV with headers."""
    store.save_exchange("sess-8", "csv test", "csv response", "shopping")
    messages = store.get_history("sess-8")
    result = export_to_csv(messages)
    assert "id" in result
    assert "session_id" in result
    assert "csv test" in result


def test_export_markdown(store):
    """export_to_markdown should return formatted Markdown."""
    store.save_exchange("sess-9", "md test", "md response", "shopping")
    messages = store.get_history("sess-9")
    result = export_to_markdown(messages)
    assert "# ShopSage AI" in result
    assert "🧑 User" in result
    assert "🤖 ShopSage AI" in result
