"""
Deal Alerts — Price drop notification system for ShopSage AI.

Allows users to set price watches on products and get notified
when prices drop below their target threshold.
"""

import json
import sqlite3
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.monetise.deals")


@dataclass
class PriceWatch:
    """Represents a user's price watch subscription."""

    id: Optional[int] = None
    user_id: str = ""
    product_query: str = ""
    target_price: float = 0.0
    current_price: Optional[float] = None
    lowest_price: Optional[float] = None
    store: str = ""
    product_url: str = ""
    is_active: bool = True
    triggered: bool = False
    created_at: Optional[str] = None
    last_checked: Optional[str] = None


class DealAlertStore:
    """SQLite-backed store for price watch subscriptions."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_table()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create the price_watches table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_watches (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         TEXT NOT NULL,
                product_query   TEXT NOT NULL,
                target_price    REAL NOT NULL,
                current_price   REAL,
                lowest_price    REAL,
                store           TEXT DEFAULT '',
                product_url     TEXT DEFAULT '',
                is_active       INTEGER DEFAULT 1,
                triggered       INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                last_checked    TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_watches_user
            ON price_watches(user_id, is_active)
        """)
        conn.commit()
        conn.close()
        logger.debug("price_watches table ensured")

    def create_watch(self, user_id: str, product_query: str,
                     target_price: float, store: str = "") -> PriceWatch:
        """Create a new price watch."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO price_watches (user_id, product_query, target_price, store)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, product_query, target_price, store),
        )
        conn.commit()
        watch_id = cursor.lastrowid
        conn.close()

        logger.info(
            f"[DealAlert] Watch created: '{product_query}' "
            f"target ₹{target_price} for user {user_id[:8]}"
        )

        return PriceWatch(
            id=watch_id,
            user_id=user_id,
            product_query=product_query,
            target_price=target_price,
            store=store,
        )

    def get_user_watches(self, user_id: str,
                         active_only: bool = True) -> list[PriceWatch]:
        """Get all price watches for a user."""
        conn = self._get_conn()
        if active_only:
            rows = conn.execute(
                "SELECT * FROM price_watches WHERE user_id = ? AND is_active = 1 "
                "ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM price_watches WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        conn.close()

        return [self._row_to_watch(r) for r in rows]

    def update_price(self, watch_id: int, current_price: float,
                     product_url: str = "") -> bool:
        """
        Update the current price for a watch.

        Returns True if the price dropped below the target (alert triggered).
        """
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()

        # Get current watch
        row = conn.execute(
            "SELECT * FROM price_watches WHERE id = ?", (watch_id,)
        ).fetchone()
        if not row:
            conn.close()
            return False

        lowest = row["lowest_price"]
        if lowest is None or current_price < lowest:
            lowest = current_price

        triggered = current_price <= row["target_price"]

        conn.execute(
            """
            UPDATE price_watches SET
                current_price = ?, lowest_price = ?, product_url = ?,
                last_checked = ?, triggered = ?
            WHERE id = ?
            """,
            (current_price, lowest, product_url, now, int(triggered), watch_id),
        )
        conn.commit()
        conn.close()

        if triggered:
            logger.info(
                f"[DealAlert] 🔔 Price alert triggered! "
                f"Watch #{watch_id}: ₹{current_price} ≤ ₹{row['target_price']}"
            )

        return triggered

    def deactivate_watch(self, watch_id: int, user_id: str) -> bool:
        """Deactivate a price watch."""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE price_watches SET is_active = 0 WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        )
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def get_all_active_watches(self) -> list[PriceWatch]:
        """Get all active watches across all users (for background checker)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM price_watches WHERE is_active = 1"
        ).fetchall()
        conn.close()
        return [self._row_to_watch(r) for r in rows]

    def _row_to_watch(self, row) -> PriceWatch:
        return PriceWatch(
            id=row["id"],
            user_id=row["user_id"],
            product_query=row["product_query"],
            target_price=row["target_price"],
            current_price=row["current_price"],
            lowest_price=row["lowest_price"],
            store=row["store"],
            product_url=row["product_url"],
            is_active=bool(row["is_active"]),
            triggered=bool(row["triggered"]),
            created_at=row["created_at"],
            last_checked=row["last_checked"],
        )

    def format_watches(self, watches: list[PriceWatch]) -> str:
        """Format watch list for display."""
        if not watches:
            return "You don't have any active price alerts."

        lines = [f"📋 Your Price Alerts ({len(watches)} active):\n"]
        for w in watches:
            status = "🔔 TRIGGERED!" if w.triggered else "👀 Watching"
            current = f"₹{w.current_price:,.0f}" if w.current_price else "Not checked"
            lines.append(
                f"  #{w.id} | {w.product_query[:40]}\n"
                f"     Target: ₹{w.target_price:,.0f} | Current: {current} | {status}"
            )

        return "\n".join(lines)
