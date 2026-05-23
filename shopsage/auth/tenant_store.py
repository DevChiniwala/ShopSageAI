import sqlite3
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional

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
                        usage_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP NOT NULL
                    )
                    '''
                )
                conn.commit()
            logger.info("Initialized tenants table.")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize tenants table: {e}")
            raise

    def create_tenant(self, name: str, api_key: str) -> Dict[str, Any]:
        """
        Create a new tenant.

        Args:
            name (str): Tenant name.
            api_key (str): Unique API key for the tenant.

        Returns:
            Dict[str, Any]: The created tenant record.
        """
        tenant_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        
        try:
            with self._get_connection() as conn:
                conn.execute(
                    '''
                    INSERT INTO tenants (id, name, api_key, usage_count, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (tenant_id, name, api_key, 0, created_at)
                )
                conn.commit()
            
            logger.info(f"Created tenant {name} with ID {tenant_id}")
            return {
                "id": tenant_id,
                "name": name,
                "api_key": api_key,
                "usage_count": 0,
                "created_at": created_at
            }
        except sqlite3.Error as e:
            logger.error(f"Error creating tenant {name}: {e}")
            raise

    def get_tenant_by_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a tenant by their API key.

        Args:
            api_key (str): The API key to look up.

        Returns:
            Optional[Dict[str, Any]]: Tenant dictionary if found, else None.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT id, name, api_key, usage_count, created_at FROM tenants WHERE api_key = ?",
                    (api_key,)
                )
                row = cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
        except sqlite3.Error as e:
            logger.error(f"Error retrieving tenant by key: {e}")
            return None

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
