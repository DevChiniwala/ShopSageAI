import sqlite3
import uuid
import secrets
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.auth.tenant_store")

class TenantStore:
    """Manages SaaS tenants and API keys using SQLite."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the tenants table if it doesn't exist."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS tenants (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        api_key TEXT UNIQUE NOT NULL,
                        plan TEXT DEFAULT 'free',
                        usage_count INTEGER DEFAULT 0,
                        is_active INTEGER DEFAULT 1,
                        created_at TIMESTAMP NOT NULL
                    )
                    '''
                )
                conn.commit()
            logger.info("Initialized tenants table.")
            # Add plan/is_active columns if DB was created before Day 17
            try:
                with self._get_connection() as conn:
                    conn.execute("ALTER TABLE tenants ADD COLUMN plan TEXT DEFAULT 'free'")
                    conn.execute("ALTER TABLE tenants ADD COLUMN is_active INTEGER DEFAULT 1")
                    conn.commit()
            except sqlite3.OperationalError:
                pass  # Columns already exist
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize tenants table: {e}")
            raise

    def create_tenant(self, name: str, plan: str = "free", api_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new tenant with an auto-generated API key.

        Args:
            name (str): Tenant / company name.
            plan (str): Billing plan — 'free', 'pro', or 'enterprise'.
            api_key (str, optional): Custom key; auto-generated if omitted.

        Returns:
            Dict[str, Any]: The created tenant record including the API key.
        """
        tenant_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        if not api_key:
            api_key = f"sk-{secrets.token_urlsafe(32)}"
        
        try:
            with self._get_connection() as conn:
                conn.execute(
                    '''
                    INSERT INTO tenants (id, name, api_key, plan, usage_count, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (tenant_id, name, api_key, plan, 0, 1, created_at)
                )
                conn.commit()
            
            logger.info(f"Created tenant '{name}' (plan={plan}) with ID {tenant_id}")
            return {
                "id": tenant_id,
                "name": name,
                "api_key": api_key,
                "plan": plan,
                "usage_count": 0,
                "is_active": True,
                "created_at": created_at
            }
        except sqlite3.Error as e:
            logger.error(f"Error creating tenant {name}: {e}")
            raise

    def get_tenant_by_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve an active tenant by their API key.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM tenants WHERE api_key = ? AND is_active = 1",
                    (api_key,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Error retrieving tenant by key: {e}")
            return None

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a tenant by their ID.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM tenants WHERE id = ?",
                    (tenant_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Error retrieving tenant by ID: {e}")
            return None

    def get_all_tenants(self) -> List[Dict[str, Any]]:
        """Return all tenants (for admin view)."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("SELECT * FROM tenants ORDER BY created_at DESC")
                return [dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching tenants: {e}")
            return []

    def update_tenant_plan(self, tenant_id: str, plan: str) -> bool:
        """Upgrade or downgrade a tenant's billing plan."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE tenants SET plan = ? WHERE id = ?",
                    (plan, tenant_id)
                )
                conn.commit()
            logger.info(f"Updated tenant {tenant_id} to plan={plan}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error updating tenant plan: {e}")
            return False

    def deactivate_tenant(self, tenant_id: str) -> bool:
        """Soft-delete a tenant by setting is_active=0."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE tenants SET is_active = 0 WHERE id = ?",
                    (tenant_id,)
                )
                conn.commit()
            logger.info(f"Deactivated tenant {tenant_id}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error deactivating tenant: {e}")
            return False

    def increment_usage(self, tenant_id: str) -> None:
        """
        Increment the usage count for a given tenant.

        Args:
            tenant_id (str): The ID of the tenant.
        """
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE tenants SET usage_count = usage_count + 1 WHERE id = ?",
                    (tenant_id,)
                )
                conn.commit()
            logger.debug(f"Incremented usage for tenant {tenant_id}")
        except sqlite3.Error as e:
            logger.error(f"Error incrementing usage for tenant {tenant_id}: {e}")
