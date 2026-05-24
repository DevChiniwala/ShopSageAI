"""
SaaS API Router — Secure, rate-limited B2B endpoints for ShopSage AI.

Provides versioned REST endpoints under /api/v1 with:
- API key authentication (X-API-Key header)
- Per-key sliding window rate limiting (tier-aware)
- Analytics event tracking
- Tenant management (admin)
"""

import logging
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from shopsage.auth.api_key import verify_api_key
from shopsage.auth.rate_limiter import enforce_rate_limit, get_rate_limiter, RateLimiter
from shopsage.auth.tenant_store import TenantStore
from shopsage.analytics.tracker import AnalyticsStore
from shopsage.billing.usage_tracker import UsageTracker
from shopsage.billing.billing_engine import BillingEngine
from shopsage.agent.shopping_agent import get_shopping_response
from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.router.api_router")

router = APIRouter(prefix="/api/v1", tags=["SaaS API"])

_tenants = TenantStore(db_path=DB_PATH)
_analytics = AnalyticsStore(db_path=DB_PATH)
_usage_tracker = UsageTracker(db_path=DB_PATH)
_billing_engine = BillingEngine(db_path=DB_PATH)


# ─── Request / Response Models ─────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User's input message")
    session_id: str = Field(..., description="Unique session identifier")


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tokens_remaining: Optional[int] = None


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    plan: str = Field("free", pattern="^(free|pro|enterprise)$")


class UpdatePlanRequest(BaseModel):
    plan: str = Field(..., pattern="^(free|pro|enterprise)$")


# ─── Chat Endpoint ─────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse, summary="AI Shopping Chat")
async def chat_endpoint(
    request: ChatRequest,
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> ChatResponse:
    """
    Authenticated, rate-limited chat endpoint for B2B integrations.

    - Requires `X-API-Key` header.
    - Enforces per-tier rate limits (free: 30/min, pro: 120/min).
    - Logs all interactions to the analytics engine.
    """
    plan = tenant.get("plan", "free")
    api_key = tenant.get("api_key", "")

    # Enforce rate limit
    await enforce_rate_limit(None, api_key, plan)

    logger.info(
        f"[API] Chat from tenant='{tenant['name']}' plan={plan} session={request.session_id[:8]}"
    )

    agent_response = get_shopping_response(request.message, request.session_id)

    # Track event
    event_data = {
        "message_length": len(request.message),
        "response_length": len(agent_response),
        "plan": plan,
    }
    _analytics.log_event(
        tenant_id=tenant["id"],
        session_id=request.session_id,
        event_type="chat",
    )

    limiter: RateLimiter = get_rate_limiter()
    usage = limiter.get_usage(api_key, plan)

    return ChatResponse(
        response=agent_response,
        session_id=request.session_id,
        tokens_remaining=usage["remaining"],
    )


# ─── Analytics Endpoints ───────────────────────────────────────────────


@router.get("/analytics/summary", summary="Usage Analytics Summary")
async def get_analytics_summary(
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Return aggregated usage statistics for the authenticated tenant.
    """
    stats = _analytics.get_summary_stats()
    limiter = get_rate_limiter()
    usage = limiter.get_usage(tenant.get("api_key", ""), tenant.get("plan", "free"))

    return {
        "tenant_name": tenant["name"],
        "plan": tenant.get("plan", "free"),
        "rate_limit": usage,
        "analytics": stats,
    }


# ─── Rate Limit Info ───────────────────────────────────────────────────


@router.get("/rate-limit", summary="Rate Limit Status")
async def rate_limit_status(
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Check the current rate limit usage for the calling API key.
    """
    limiter = get_rate_limiter()
    usage = limiter.get_usage(tenant.get("api_key", ""), tenant.get("plan", "free"))
    return {"tenant": tenant["name"], **usage}


# ─── Tenant Management (Admin) ─────────────────────────────────────────


@router.post("/admin/tenants", status_code=status.HTTP_201_CREATED, summary="Create Tenant")
async def create_tenant(
    req: CreateTenantRequest,
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Create a new SaaS tenant with an auto-generated API key.
    Only enterprise tenants can provision sub-tenants.
    """
    if tenant.get("plan") != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only enterprise tenants can create new tenants.",
        )

    new_tenant = _tenants.create_tenant(name=req.name, plan=req.plan)
    logger.info(f"[Admin] Tenant '{req.name}' created by '{tenant['name']}'")
    return new_tenant


@router.get("/admin/tenants", summary="List All Tenants")
async def list_tenants(
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    List all registered tenants. Enterprise-only.
    """
    if tenant.get("plan") != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant listing requires enterprise plan.",
        )

    all_tenants = _tenants.get_all_tenants()
    # Mask API keys in response
    for t in all_tenants:
        key = t.get("api_key", "")
        t["api_key"] = f"{key[:6]}…{key[-4:]}" if len(key) > 10 else "***"

    return {"count": len(all_tenants), "tenants": all_tenants}


@router.patch("/admin/tenants/{tenant_id}/plan", summary="Update Tenant Plan")
async def update_tenant_plan(
    tenant_id: str,
    req: UpdatePlanRequest,
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Upgrade or downgrade a tenant's billing plan. Enterprise-only.
    """
    if tenant.get("plan") != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Plan changes require enterprise plan.",
        )

    success = _tenants.update_tenant_plan(tenant_id, req.plan)
    if not success:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {"success": True, "tenant_id": tenant_id, "new_plan": req.plan}


@router.delete("/admin/tenants/{tenant_id}", summary="Deactivate Tenant")
async def deactivate_tenant(
    tenant_id: str,
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Soft-delete a tenant (sets is_active=False). Enterprise-only.
    """
    if tenant.get("plan") != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant deactivation requires enterprise plan.",
        )

    success = _tenants.deactivate_tenant(tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {"success": True, "tenant_id": tenant_id, "status": "deactivated"}


# ─── Billing (Admin) ───────────────────────────────────────────────────


@router.get("/admin/billing/{tenant_id}", summary="Get Tenant Bill")
async def get_tenant_bill(
    tenant_id: str,
    month: Optional[str] = None,
    tenant: Dict[str, Any] = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Get the current or historical bill for a tenant.
    Requires enterprise plan to view other tenants.
    """
    if tenant["id"] != tenant_id and tenant.get("plan") != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view billing for other tenants unless enterprise.",
        )

    try:
        bill = _billing_engine.calculate_current_bill(tenant_id, month)
        if not month:
            prediction = _billing_engine.predict_end_of_month(tenant_id)
            bill["prediction"] = prediction
        return bill
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
