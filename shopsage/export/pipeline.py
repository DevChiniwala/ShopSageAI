"""
Data Export Pipeline — Generate CSV/JSON exports of tenant data.

Supports exporting:
- Analytics events
- Billing/usage data
- Conversation history
- Audit logs
- Search queries

Exports are generated as background jobs and stored as files
that can be downloaded via the API.
"""

import csv
import json
import io
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from shopsage.billing.usage_tracker import UsageTracker
from shopsage.analytics.search_tracker import SearchTracker
from shopsage.security.audit_log import AuditLog
from shopsage.history.conversation_store import ConversationStore
from shopsage.config import settings

logger = logging.getLogger("shopsage.export.pipeline")

# Export storage directory
EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)


class ExportPipeline:
    """
    Generates downloadable data exports for tenants.

    Supports CSV and JSON formats. Each export is saved to disk
    and tracked with metadata for retrieval.
    """

    def __init__(self, db_path: str = settings.DB_PATH):
        self._usage = UsageTracker(db_path)
        self._search = SearchTracker(db_path)
        self._audit = AuditLog(db_path)
        self._history = ConversationStore(db_path)
        self._exports: Dict[str, Dict[str, Any]] = {}

    def export_usage(
        self,
        tenant_id: str,
        year_month: str,
        fmt: str = "csv",
    ) -> Dict[str, Any]:
        """
        Export billing/usage data for a tenant.

        Args:
            tenant_id: The tenant to export for.
            year_month: Month to export (YYYY-MM).
            fmt: Output format — "csv" or "json".

        Returns:
            Dict with export_id, filename, and path.
        """
        data = self._usage.get_daily_breakdown(tenant_id, year_month)
        return self._write_export(
            data=data,
            export_type="usage",
            tenant_id=tenant_id,
            fmt=fmt,
            columns=["date", "api_calls", "agent_runs", "searches", "cost_incurred"],
        )

    def export_search_analytics(
        self,
        hours: int = 168,
        fmt: str = "csv",
    ) -> Dict[str, Any]:
        """Export popular search queries."""
        data = self._search.get_popular_queries(limit=500, hours=hours)
        return self._write_export(
            data=data,
            export_type="search_analytics",
            tenant_id="system",
            fmt=fmt,
            columns=["query", "count", "avg_results"],
        )

    def export_audit_log(
        self,
        tenant_id: str = "",
        limit: int = 1000,
        fmt: str = "csv",
    ) -> Dict[str, Any]:
        """Export audit log entries."""
        if tenant_id:
            data = self._audit.get_by_actor(tenant_id, limit)
        else:
            data = self._audit.get_recent(limit)

        return self._write_export(
            data=data,
            export_type="audit_log",
            tenant_id=tenant_id or "system",
            fmt=fmt,
            columns=[
                "id", "timestamp", "actor_id", "actor_type",
                "action", "resource_type", "resource_id",
            ],
        )

    def export_conversations(
        self,
        session_id: str,
        fmt: str = "json",
    ) -> Dict[str, Any]:
        """Export conversation history for a session."""
        messages = self._history.get_messages(session_id)
        data = [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
                "route": m.route,
            }
            for m in messages
        ]
        return self._write_export(
            data=data,
            export_type="conversations",
            tenant_id=session_id,
            fmt=fmt,
            columns=["role", "content", "timestamp", "route"],
        )

    def get_export(self, export_id: str) -> Optional[Dict[str, Any]]:
        """Get export metadata by ID."""
        return self._exports.get(export_id)

    def list_exports(self, tenant_id: str = "") -> List[Dict[str, Any]]:
        """List all exports, optionally filtered by tenant."""
        exports = list(self._exports.values())
        if tenant_id:
            exports = [e for e in exports if e["tenant_id"] == tenant_id]
        return sorted(exports, key=lambda e: e["created_at"], reverse=True)

    def _write_export(
        self,
        data: List[Dict[str, Any]],
        export_type: str,
        tenant_id: str,
        fmt: str,
        columns: List[str],
    ) -> Dict[str, Any]:
        """Write export data to file and track it."""
        export_id = str(uuid.uuid4())[:12]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{export_type}_{tenant_id[:8]}_{timestamp}.{fmt}"
        filepath = os.path.join(EXPORT_DIR, filename)

        try:
            if fmt == "csv":
                self._write_csv(filepath, data, columns)
            else:
                self._write_json(filepath, data)

            file_size = os.path.getsize(filepath)

            metadata = {
                "export_id": export_id,
                "type": export_type,
                "tenant_id": tenant_id,
                "format": fmt,
                "filename": filename,
                "filepath": filepath,
                "row_count": len(data),
                "file_size_bytes": file_size,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._exports[export_id] = metadata

            logger.info(
                f"[Export] Created {fmt.upper()} export: {filename} "
                f"({len(data)} rows, {file_size} bytes)"
            )
            return metadata

        except Exception as e:
            logger.error(f"[Export] Write error: {e}")
            raise

    @staticmethod
    def _write_csv(filepath: str, data: List[Dict], columns: List[str]) -> None:
        """Write data to CSV file."""
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)

    @staticmethod
    def _write_json(filepath: str, data: List[Dict]) -> None:
        """Write data to JSON file."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"data": data, "count": len(data)}, f, indent=2, default=str)
