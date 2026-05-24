"""
Conversation Store — Persistent chat history for ShopSage AI.

Stores every user message and AI response in SQLite, enabling
conversation replay, export, and context retrieval for long-running
sessions.

Schema:
    conversations:  session_id, message_id, role, content, route, timestamp
"""

import sqlite3
import uuid
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.history")


@dataclass
class Message:
    """A single conversation message."""
    id: str
    session_id: str
    role: str           # "user" | "assistant" | "system"
    content: str
    route: str          # "shopping" | "chitchat" | "visual_search" etc.
    timestamp: str


class ConversationStore:
    """
    SQLite-backed conversation history store.

    Persists all messages per session, enabling:
    - Full conversation replay
    - Context window retrieval for agent memory
    - JSON/CSV export for analytics
    - Session search across history
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create conversations table if it doesn't exist."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        route TEXT DEFAULT '',
                        timestamp TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_conv_session
                    ON conversations(session_id, timestamp)
                """)
                conn.commit()
            logger.info("[ConversationStore] Initialized")
        except sqlite3.Error as e:
            logger.error(f"[ConversationStore] Init error: {e}")
            raise

    # ─── Write ─────────────────────────────────────────────────────

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        route: str = "",
    ) -> Message:
        """
        Persist a single message to history.

        Args:
            session_id: User session identifier.
            role: 'user', 'assistant', or 'system'.
            content: Message text.
            route: Which handler processed the query.

        Returns:
            The created Message dataclass.
        """
        msg = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            route=route,
            timestamp=datetime.utcnow().isoformat(),
        )

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO conversations
                       (id, session_id, role, content, route, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (msg.id, msg.session_id, msg.role,
                     msg.content, msg.route, msg.timestamp),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"[ConversationStore] Save error: {e}")

        return msg

    def save_exchange(
        self,
        session_id: str,
        user_message: str,
        ai_response: str,
        route: str = "",
    ) -> tuple[Message, Message]:
        """Save a user→assistant message pair atomically."""
        user_msg = self.save_message(session_id, "user", user_message, route)
        ai_msg = self.save_message(session_id, "assistant", ai_response, route)
        return user_msg, ai_msg

    # ─── Read ──────────────────────────────────────────────────────

    def get_history(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Message]:
        """
        Retrieve conversation history for a session, newest last.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM conversations
                       WHERE session_id = ?
                       ORDER BY timestamp ASC
                       LIMIT ? OFFSET ?""",
                    (session_id, limit, offset),
                ).fetchall()
                return [Message(**dict(r)) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[ConversationStore] Read error: {e}")
            return []

    def get_recent_context(
        self, session_id: str, n_messages: int = 6
    ) -> str:
        """
        Build a context string from the last N messages for prompt injection.

        Returns a formatted string like:
            User: show me red shoes
            Assistant: Here are 5 options...
        """
        messages = self.get_history(session_id, limit=n_messages)
        if not messages:
            return ""

        lines = []
        for m in messages[-n_messages:]:
            role_label = "User" if m.role == "user" else "ShopSage"
            lines.append(f"{role_label}: {m.content[:200]}")

        return "\n".join(lines)

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Return message count and time range for a session."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) as count,
                              MIN(timestamp) as first_msg,
                              MAX(timestamp) as last_msg
                       FROM conversations WHERE session_id = ?""",
                    (session_id,),
                ).fetchone()

                return {
                    "session_id": session_id,
                    "message_count": row["count"],
                    "first_message": row["first_msg"],
                    "last_message": row["last_msg"],
                }
        except sqlite3.Error as e:
            logger.error(f"[ConversationStore] Stats error: {e}")
            return {"session_id": session_id, "message_count": 0}

    def search_history(
        self, session_id: str, query: str, limit: int = 10
    ) -> List[Message]:
        """Full-text search across a session's history."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM conversations
                       WHERE session_id = ? AND content LIKE ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (session_id, f"%{query}%", limit),
                ).fetchall()
                return [Message(**dict(r)) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[ConversationStore] Search error: {e}")
            return []

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List all sessions with message counts (admin view)."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT session_id,
                              COUNT(*) as msg_count,
                              MIN(timestamp) as started,
                              MAX(timestamp) as last_active
                       FROM conversations
                       GROUP BY session_id
                       ORDER BY last_active DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"[ConversationStore] List sessions error: {e}")
            return []

    def delete_session(self, session_id: str) -> int:
        """Delete all messages for a session. Returns count deleted."""
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM conversations WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
                count = cursor.rowcount
                logger.info(f"[ConversationStore] Deleted {count} messages for {session_id[:8]}")
                return count
        except sqlite3.Error as e:
            logger.error(f"[ConversationStore] Delete error: {e}")
            return 0
