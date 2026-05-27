"""
API Versioning — Version management, deprecation tracking, and migration
helpers for ShopSage AI's REST API.

Supports:
- Multiple API versions with lifecycle states (active, deprecated, sunset)
- Automatic deprecation headers on responses
- Version negotiation via URL prefix or Accept header
- Migration guides between versions
- Per-version feature availability matrix

Versions:
    v1 (current): Original API — all existing endpoints
    v2 (preview): Enhanced API — structured errors, pagination, field filtering
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("shopsage.router.versioning")


# ─── Version Lifecycle ────────────────────────────────────────────────


class VersionStatus(str, Enum):
    PREVIEW = "preview"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUNSET = "sunset"


@dataclass
class APIVersion:
    """Metadata for a single API version."""
    version: str                       # e.g. "v1", "v2"
    status: VersionStatus
    released: str                      # ISO date
    deprecated_on: Optional[str] = None
    sunset_on: Optional[str] = None
    changelog: List[str] = field(default_factory=list)
    features: Dict[str, bool] = field(default_factory=dict)


# ─── Version Registry ─────────────────────────────────────────────────


class VersionRegistry:
    """
    Central registry holding all API version definitions and providing
    version negotiation, deprecation checks, and migration metadata.
    """

    def __init__(self) -> None:
        self._versions: Dict[str, APIVersion] = {}
        self._default_version: str = "v1"
        self._migration_guides: Dict[str, Dict[str, Any]] = {}

    # ── Registration ──────────────────────────────────────────────────

    def register(self, version: APIVersion) -> None:
        """Register an API version."""
        self._versions[version.version] = version
        logger.info(
            f"[Versioning] Registered API {version.version} "
            f"(status={version.status.value})"
        )

    def set_default(self, version_key: str) -> None:
        """Set the default API version for unversioned requests."""
        if version_key in self._versions:
            self._default_version = version_key

    # ── Lookup ────────────────────────────────────────────────────────

    def get(self, version_key: str) -> Optional[APIVersion]:
        """Get version metadata by key."""
        return self._versions.get(version_key)

    def get_default(self) -> APIVersion:
        """Return the default API version."""
        return self._versions[self._default_version]

    def list_versions(self) -> List[Dict[str, Any]]:
        """Return all registered versions as dicts."""
        result = []
        for v in self._versions.values():
            result.append({
                "version": v.version,
                "status": v.status.value,
                "released": v.released,
                "deprecated_on": v.deprecated_on,
                "sunset_on": v.sunset_on,
                "is_default": v.version == self._default_version,
                "feature_count": len(v.features),
                "changelog_entries": len(v.changelog),
            })
        return result

    def get_active_versions(self) -> List[str]:
        """Return version keys that are active or preview."""
        return [
            k for k, v in self._versions.items()
            if v.status in (VersionStatus.ACTIVE, VersionStatus.PREVIEW)
        ]

    # ── Deprecation ───────────────────────────────────────────────────

    def is_deprecated(self, version_key: str) -> bool:
        """Check if a version is deprecated or sunset."""
        v = self._versions.get(version_key)
        if not v:
            return False
        return v.status in (VersionStatus.DEPRECATED, VersionStatus.SUNSET)

    def is_sunset(self, version_key: str) -> bool:
        """Check if a version is fully sunset (should be rejected)."""
        v = self._versions.get(version_key)
        if not v:
            return False
        return v.status == VersionStatus.SUNSET

    def get_deprecation_info(self, version_key: str) -> Optional[Dict[str, Any]]:
        """Get deprecation details for a version."""
        v = self._versions.get(version_key)
        if not v or not self.is_deprecated(version_key):
            return None
        return {
            "version": v.version,
            "deprecated_on": v.deprecated_on,
            "sunset_on": v.sunset_on,
            "status": v.status.value,
            "migration_target": self._default_version,
        }

    # ── Migration Guides ──────────────────────────────────────────────

    def add_migration_guide(
        self, from_version: str, to_version: str,
        breaking_changes: List[str],
        new_features: List[str],
        removed_endpoints: List[str] = None,
        renamed_fields: Dict[str, str] = None,
    ) -> None:
        """Register a migration guide between two versions."""
        key = f"{from_version}->{to_version}"
        self._migration_guides[key] = {
            "from": from_version,
            "to": to_version,
            "breaking_changes": breaking_changes,
            "new_features": new_features,
            "removed_endpoints": removed_endpoints or [],
            "renamed_fields": renamed_fields or {},
        }

    def get_migration_guide(
        self, from_version: str, to_version: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a migration guide."""
        key = f"{from_version}->{to_version}"
        return self._migration_guides.get(key)

    # ── Version Negotiation ───────────────────────────────────────────

    def negotiate(self, request_path: str, accept_header: str = "") -> str:
        """
        Determine the API version from the request.

        Priority:
        1. URL prefix (/api/v2/...)
        2. Accept header (application/vnd.shopsage.v2+json)
        3. Default version
        """
        # Check URL prefix
        for vk in self._versions:
            if f"/api/{vk}/" in request_path or request_path.endswith(f"/api/{vk}"):
                return vk

        # Check Accept header
        if "vnd.shopsage." in accept_header:
            for vk in self._versions:
                if f"vnd.shopsage.{vk}" in accept_header:
                    return vk

        return self._default_version

    # ── Feature Matrix ────────────────────────────────────────────────

    def has_feature(self, version_key: str, feature: str) -> bool:
        """Check if a specific feature is available in a version."""
        v = self._versions.get(version_key)
        if not v:
            return False
        return v.features.get(feature, False)

    def get_feature_matrix(self) -> Dict[str, Dict[str, bool]]:
        """Return the full feature availability matrix."""
        return {
            v.version: v.features for v in self._versions.values()
        }


# ─── Middleware ────────────────────────────────────────────────────────


class VersioningMiddleware(BaseHTTPMiddleware):
    """
    Injects deprecation headers and version metadata into API responses.

    Headers added:
    - X-API-Version: The resolved API version
    - Deprecation: RFC 8594 deprecation date (if deprecated)
    - Sunset: RFC 8594 sunset date (if scheduled)
    - Link: Migration documentation link
    """

    def __init__(self, app, registry: VersionRegistry):
        super().__init__(app)
        self.registry = registry

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        accept = request.headers.get("accept", "")

        # Only process /api/ requests
        if not path.startswith("/api/"):
            return await call_next(request)

        version_key = self.registry.negotiate(path, accept)
        version = self.registry.get(version_key)

        # Reject sunset versions
        if version and self.registry.is_sunset(version_key):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=410,
                content={
                    "error": "API version gone",
                    "message": f"API {version_key} has been sunset. "
                               f"Please migrate to {self.registry._default_version}.",
                    "migration_guide": f"/api/versions/migrate?"
                                       f"from={version_key}&to={self.registry._default_version}",
                },
                headers={"X-API-Version": version_key},
            )

        response = await call_next(request)

        # Inject version header
        response.headers["X-API-Version"] = version_key

        # Add deprecation headers
        if version and self.registry.is_deprecated(version_key):
            if version.deprecated_on:
                response.headers["Deprecation"] = version.deprecated_on
            if version.sunset_on:
                response.headers["Sunset"] = version.sunset_on
            response.headers["Link"] = (
                f'</api/versions/migrate?from={version_key}'
                f'&to={self.registry._default_version}>; rel="successor-version"'
            )

        return response


# ─── Default Setup ────────────────────────────────────────────────────


def create_default_registry() -> VersionRegistry:
    """Create a pre-configured registry with v1 and v2 definitions."""
    registry = VersionRegistry()

    v1 = APIVersion(
        version="v1",
        status=VersionStatus.ACTIVE,
        released="2026-05-01",
        changelog=[
            "Initial release — chat, analytics, tenants",
            "Added billing engine and usage tracking",
            "Added feature flags and API key management",
            "Added webhooks and search analytics",
            "Added export pipeline and task scheduler",
            "Added plugin system and dynamic config",
        ],
        features={
            "chat": True,
            "analytics": True,
            "billing": True,
            "feature_flags": True,
            "key_management": True,
            "webhooks": True,
            "export": True,
            "plugins": True,
            "dynamic_config": True,
            "structured_errors": False,
            "pagination": False,
            "field_filtering": False,
            "rate_limit_analytics": False,
        },
    )

    v2 = APIVersion(
        version="v2",
        status=VersionStatus.PREVIEW,
        released="2026-05-28",
        changelog=[
            "Structured error responses with error codes",
            "Cursor-based pagination on list endpoints",
            "Field filtering via ?fields= parameter",
            "Rate limit analytics and historical reporting",
            "Enhanced deprecation and versioning headers",
        ],
        features={
            "chat": True,
            "analytics": True,
            "billing": True,
            "feature_flags": True,
            "key_management": True,
            "webhooks": True,
            "export": True,
            "plugins": True,
            "dynamic_config": True,
            "structured_errors": True,
            "pagination": True,
            "field_filtering": True,
            "rate_limit_analytics": True,
        },
    )

    registry.register(v1)
    registry.register(v2)
    registry.set_default("v1")

    # Migration guide v1 -> v2
    registry.add_migration_guide(
        from_version="v1",
        to_version="v2",
        breaking_changes=[
            "Error responses now return {error_code, message, details} instead of plain strings",
            "List endpoints return {data, pagination} wrapper instead of flat arrays",
        ],
        new_features=[
            "Cursor-based pagination on all list endpoints",
            "Field filtering via ?fields=name,plan query parameter",
            "Rate limit analytics with historical data",
            "Structured error codes for programmatic handling",
        ],
        renamed_fields={
            "tokens_remaining": "rate_limit.remaining",
            "count": "pagination.total",
        },
    )

    return registry
