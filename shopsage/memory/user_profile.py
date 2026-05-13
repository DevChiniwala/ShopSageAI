"""
User Profile — Persistent preference storage for ShopSage AI.

Stores and retrieves user taste profiles (budget, brands, style, sizes)
from SQLite so the shopping agent can personalize every interaction.
"""

import json
import sqlite3
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.memory")


# ─── Data Model ────────────────────────────────────────────────────────


@dataclass
class UserProfile:
    """Represents a user's shopping preferences and taste profile."""

    user_id: str
    name: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferred_brands: list[str] = field(default_factory=list)
    preferred_colors: list[str] = field(default_factory=list)
    preferred_materials: list[str] = field(default_factory=list)
    style_tags: list[str] = field(default_factory=list)
    gender: Optional[str] = None
    sizes: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_prompt_context(self) -> str:
        """Convert profile to a natural language string for LLM injection."""
        parts = []

        if self.name:
            parts.append(f"Name: {self.name}")
        if self.budget_min or self.budget_max:
            bmin = f"₹{self.budget_min:,.0f}" if self.budget_min else "any"
            bmax = f"₹{self.budget_max:,.0f}" if self.budget_max else "any"
            parts.append(f"Budget: {bmin} – {bmax}")
        if self.preferred_brands:
            parts.append(f"Favourite brands: {', '.join(self.preferred_brands)}")
        if self.preferred_colors:
            parts.append(f"Preferred colors: {', '.join(self.preferred_colors)}")
        if self.preferred_materials:
            parts.append(f"Preferred materials: {', '.join(self.preferred_materials)}")
        if self.style_tags:
            parts.append(f"Style: {', '.join(self.style_tags)}")
        if self.gender:
            parts.append(f"Gender: {self.gender}")
        if self.sizes:
            size_str = ", ".join(f"{k}: {v}" for k, v in self.sizes.items())
            parts.append(f"Sizes: {size_str}")
        if self.notes:
            parts.append(f"Notes: {self.notes}")

        if not parts:
            return "No preferences stored yet."

        return "\n".join(f"  • {p}" for p in parts)


# ─── Profile Store ─────────────────────────────────────────────────────


class ProfileStore:
    """SQLite-backed persistent store for user profiles."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_table()

    def _get_conn(self) -> sqlite3.Connection:
        """Create a new database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create the user_profiles table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id            TEXT PRIMARY KEY,
                name               TEXT,
                budget_min         REAL,
                budget_max         REAL,
                preferred_brands   TEXT DEFAULT '[]',
                preferred_colors   TEXT DEFAULT '[]',
                preferred_materials TEXT DEFAULT '[]',
                style_tags         TEXT DEFAULT '[]',
                gender             TEXT,
                sizes              TEXT DEFAULT '{}',
                notes              TEXT DEFAULT '',
                created_at         TEXT DEFAULT (datetime('now')),
                updated_at         TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
        logger.debug("user_profiles table ensured")

    # ─── CRUD ──────────────────────────────────────────────────────────

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Retrieve a user profile by session/user ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()

        if row is None:
            return None

        return UserProfile(
            user_id=row["user_id"],
            name=row["name"],
            budget_min=row["budget_min"],
            budget_max=row["budget_max"],
            preferred_brands=json.loads(row["preferred_brands"] or "[]"),
            preferred_colors=json.loads(row["preferred_colors"] or "[]"),
            preferred_materials=json.loads(row["preferred_materials"] or "[]"),
            style_tags=json.loads(row["style_tags"] or "[]"),
            gender=row["gender"],
            sizes=json.loads(row["sizes"] or "{}"),
            notes=row["notes"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_profile(self, profile: UserProfile) -> None:
        """Insert or update a user profile."""
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT INTO user_profiles
                (user_id, name, budget_min, budget_max,
                 preferred_brands, preferred_colors, preferred_materials,
                 style_tags, gender, sizes, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = COALESCE(excluded.name, name),
                budget_min = COALESCE(excluded.budget_min, budget_min),
                budget_max = COALESCE(excluded.budget_max, budget_max),
                preferred_brands = excluded.preferred_brands,
                preferred_colors = excluded.preferred_colors,
                preferred_materials = excluded.preferred_materials,
                style_tags = excluded.style_tags,
                gender = COALESCE(excluded.gender, gender),
                sizes = excluded.sizes,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                profile.user_id,
                profile.name,
                profile.budget_min,
                profile.budget_max,
                json.dumps(profile.preferred_brands),
                json.dumps(profile.preferred_colors),
                json.dumps(profile.preferred_materials),
                json.dumps(profile.style_tags),
                profile.gender,
                json.dumps(profile.sizes),
                profile.notes,
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()
        logger.info(f"Profile saved for user {profile.user_id[:8]}")

    def merge_preferences(self, user_id: str, new_prefs: dict) -> UserProfile:
        """
        Merge new preferences into an existing profile.

        List fields (brands, colors, etc.) are merged with deduplication.
        Scalar fields (budget, gender) are overwritten if provided.

        Args:
            user_id: The user's session/ID.
            new_prefs: Dict of preference keys and values to merge.

        Returns:
            The updated UserProfile.
        """
        profile = self.get_profile(user_id) or UserProfile(user_id=user_id)

        # Merge list fields (deduplicate)
        list_fields = [
            "preferred_brands", "preferred_colors",
            "preferred_materials", "style_tags",
        ]
        for key in list_fields:
            if key in new_prefs and new_prefs[key]:
                existing = getattr(profile, key)
                incoming = new_prefs[key]
                if isinstance(incoming, str):
                    incoming = [incoming]
                merged = list(dict.fromkeys(existing + incoming))  # dedup, keep order
                setattr(profile, key, merged)

        # Merge scalar fields (overwrite)
        scalar_fields = ["name", "budget_min", "budget_max", "gender", "notes"]
        for key in scalar_fields:
            if key in new_prefs and new_prefs[key] is not None:
                setattr(profile, key, new_prefs[key])

        # Merge sizes dict
        if "sizes" in new_prefs and isinstance(new_prefs["sizes"], dict):
            profile.sizes.update(new_prefs["sizes"])

        self.upsert_profile(profile)
        return profile

    def delete_profile(self, user_id: str) -> bool:
        """Delete a user profile. Returns True if a profile was deleted."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM user_profiles WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        conn.close()
        return cursor.rowcount > 0
