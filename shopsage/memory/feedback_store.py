import sqlite3
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from shopsage.config import settings

logger = logging.getLogger("shopsage.memory.feedback_store")

class FeedbackStore:
    """
    SQLite-backed store for user feedback on AI responses.
    """
    def __init__(self, db_path: str = settings.DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS feedback (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        rating INTEGER NOT NULL,
                        comment TEXT,
                        timestamp TEXT NOT NULL
                    )
                """)
                conn.commit()
            logger.info(f"FeedbackStore initialized with DB at {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize FeedbackStore database: {e}")
            raise

    def log_feedback(self, session_id: str, message_id: str, rating: int, comment: Optional[str] = None) -> str:
        """
        Log user feedback for a specific message.
        """
        try:
            feedback_id = str(uuid.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO feedback (id, session_id, message_id, rating, comment, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (feedback_id, session_id, message_id, rating, comment, timestamp))
                conn.commit()
                
            logger.info(f"Logged feedback {feedback_id} for message {message_id}")
            return feedback_id
        except sqlite3.Error as e:
            logger.error(f"Failed to log feedback: {e}")
            raise

    def get_feedback_stats(self) -> Dict[str, Any]:
        """
        Get aggregated feedback statistics.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_feedback,
                        SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) as positive_feedback,
                        SUM(CASE WHEN rating < 0 THEN 1 ELSE 0 END) as negative_feedback
                    FROM feedback
                """)
                
                row = cursor.fetchone()
                
                total = row["total_feedback"] or 0
                positive = row["positive_feedback"] or 0
                negative = row["negative_feedback"] or 0
                
                cursor.execute("SELECT * FROM feedback ORDER BY timestamp DESC LIMIT 10")
                recent_rows = cursor.fetchall()
                recent_feedback = [dict(r) for r in recent_rows]
                
                return {
                    "total": total,
                    "positive": positive,
                    "negative": negative,
                    "recent": recent_feedback
                }
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve feedback stats: {e}")
            return {"total": 0, "positive": 0, "negative": 0, "recent": []}
