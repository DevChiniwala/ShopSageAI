"""
Collections Store — Save, organize, and manage product collections.

Provides a SQLite-backed persistent storage for user wishlists,
moodboards, and curated product collections.
"""

import json
import sqlite3
import time
import uuid
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("shopsage.collections")


@dataclass
class CollectionItem:
    """A single product saved in a collection."""
    item_id: str
    title: str
    price: str
    store: str
    image_url: str = ""
    affiliate_url: str = ""
    notes: str = ""
    added_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Collection:
    """A named collection of saved products."""
    collection_id: str
    name: str
    description: str = ""
    cover_image: str = ""
    session_id: str = ""
    items: list[CollectionItem] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["item_count"] = len(self.items)
        return d


class CollectionStore:
    """SQLite-backed collection/wishlist manager."""

    def __init__(self, db_path: str = "data/shopsage.sqlite3"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_tables()
        logger.info("[Collections] Store initialized")

    def _conn(self):
        return sqlite3.connect(self._db_path)

    def _init_tables(self):
        with self._lock, self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collections (
                    collection_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    cover_image TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collection_items (
                    item_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    price TEXT DEFAULT '',
                    store TEXT DEFAULT '',
                    image_url TEXT DEFAULT '',
                    affiliate_url TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    added_at REAL NOT NULL,
                    FOREIGN KEY (collection_id) REFERENCES collections(collection_id)
                        ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_collection
                ON collection_items(collection_id)
            """)

    # ── Create ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        description: str = "",
        session_id: str = "",
        cover_image: str = "",
    ) -> Collection:
        """Create a new collection."""
        now = time.time()
        collection = Collection(
            collection_id=str(uuid.uuid4())[:8],
            name=name,
            description=description,
            cover_image=cover_image,
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO collections
                   (collection_id, name, description, cover_image, session_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (collection.collection_id, name, description, cover_image,
                 session_id, now, now),
            )
        logger.info(f"[Collections] Created '{name}' ({collection.collection_id})")
        return collection

    # ── Read ───────────────────────────────────────────────────

    def list_collections(self, session_id: str = "") -> list[dict]:
        """List all collections, optionally filtered by session."""
        with self._lock, self._conn() as conn:
            if session_id:
                rows = conn.execute(
                    """SELECT c.*, COUNT(ci.item_id) as item_count
                       FROM collections c
                       LEFT JOIN collection_items ci ON c.collection_id = ci.collection_id
                       WHERE c.session_id = ?
                       GROUP BY c.collection_id
                       ORDER BY c.updated_at DESC""",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT c.*, COUNT(ci.item_id) as item_count
                       FROM collections c
                       LEFT JOIN collection_items ci ON c.collection_id = ci.collection_id
                       GROUP BY c.collection_id
                       ORDER BY c.updated_at DESC""",
                ).fetchall()

        return [
            {
                "collection_id": r[0], "name": r[1], "description": r[2],
                "cover_image": r[3], "session_id": r[4],
                "created_at": r[5], "updated_at": r[6], "item_count": r[7],
            }
            for r in rows
        ]

    def get_collection(self, collection_id: str) -> Optional[dict]:
        """Get a collection with all its items."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if not row:
                return None

            items = conn.execute(
                """SELECT * FROM collection_items
                   WHERE collection_id = ? ORDER BY added_at DESC""",
                (collection_id,),
            ).fetchall()

        return {
            "collection_id": row[0], "name": row[1], "description": row[2],
            "cover_image": row[3], "session_id": row[4],
            "created_at": row[5], "updated_at": row[6],
            "items": [
                {
                    "item_id": i[0], "title": i[2], "price": i[3],
                    "store": i[4], "image_url": i[5],
                    "affiliate_url": i[6], "notes": i[7], "added_at": i[8],
                }
                for i in items
            ],
        }

    # ── Add / Remove Items ─────────────────────────────────────

    def add_item(
        self,
        collection_id: str,
        title: str,
        price: str = "",
        store: str = "",
        image_url: str = "",
        affiliate_url: str = "",
        notes: str = "",
    ) -> str:
        """Add a product to a collection. Returns the item_id."""
        item_id = str(uuid.uuid4())[:8]
        now = time.time()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO collection_items
                   (item_id, collection_id, title, price, store, image_url, affiliate_url, notes, added_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, collection_id, title, price, store, image_url,
                 affiliate_url, notes, now),
            )
            conn.execute(
                "UPDATE collections SET updated_at = ? WHERE collection_id = ?",
                (now, collection_id),
            )
        logger.info(f"[Collections] Added '{title}' to {collection_id}")
        return item_id

    def remove_item(self, collection_id: str, item_id: str) -> bool:
        """Remove a product from a collection."""
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM collection_items WHERE item_id = ? AND collection_id = ?",
                (item_id, collection_id),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE collections SET updated_at = ? WHERE collection_id = ?",
                    (time.time(), collection_id),
                )
        return cur.rowcount > 0

    # ── Delete ─────────────────────────────────────────────────

    def delete_collection(self, collection_id: str) -> bool:
        """Delete a collection and all its items."""
        with self._lock, self._conn() as conn:
            conn.execute(
                "DELETE FROM collection_items WHERE collection_id = ?",
                (collection_id,),
            )
            cur = conn.execute(
                "DELETE FROM collections WHERE collection_id = ?",
                (collection_id,),
            )
        return cur.rowcount > 0
