import sqlite3
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.analytics.tracker")

class AnalyticsStore:
    """Manages SaaS analytics events using SQLite."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the analytics_events table if it doesn't exist."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS analytics_events (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        event_data TEXT,
                        timestamp TIMESTAMP NOT NULL
                    )
                    '''
                )
                conn.commit()
            logger.info("Initialized analytics_events table.")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize analytics_events table: {e}")
            raise

    def log_event(self, tenant_id: str, session_id: str, event_type: str, event_data: Dict[str, Any]) -> None:
        """
        Log an analytics event.

        Args:
            tenant_id (str): ID of the tenant.
            session_id (str): Session identifier.
            event_type (str): Type of the event (e.g., 'chat', 'search').
            event_data (Dict[str, Any]): Additional event data as a dictionary.
        """
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        
        try:
            event_data_json = json.dumps(event_data)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize event_data to JSON: {e}")
            event_data_json = "{}"

        try:
            with self._get_connection() as conn:
                conn.execute(
                    '''
                    INSERT INTO analytics_events (id, tenant_id, session_id, event_type, event_data, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (event_id, tenant_id, session_id, event_type, event_data_json, timestamp)
                )
                conn.commit()
            logger.debug(f"Logged {event_type} event for tenant {tenant_id}")
        except sqlite3.Error as e:
            logger.error(f"Error logging event for tenant {tenant_id}: {e}")

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get aggregated summary statistics of all events.

        Returns:
            Dict[str, Any]: Summary statistics dictionary.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    '''
                    SELECT event_type, COUNT(*) as count 
                    FROM analytics_events 
                    GROUP BY event_type
                    '''
                )
                rows = cursor.fetchall()
                
                stats = {row['event_type']: row['count'] for row in rows}
                
                cursor = conn.execute("SELECT COUNT(DISTINCT tenant_id) as tenant_count FROM analytics_events")
                tenant_count = cursor.fetchone()['tenant_count']
                
                cursor = conn.execute("SELECT COUNT(*) as total_events FROM analytics_events")
                total_events = cursor.fetchone()['total_events']
                
                return {
                    "events_by_type": stats,
                    "total_active_tenants": tenant_count,
                    "total_events": total_events
                }
        except sqlite3.Error as e:
            logger.error(f"Error fetching summary stats: {e}")
            return {}
