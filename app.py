"""
ShopSage AI - FastAPI Application Entry Point.

An AI-powered intelligent shopping assistant combining LLMs,
RAG, Semantic Routing, User Memory, and advanced product search.
"""

import uuid
import json
import logging
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from shopsage.router.semantic_router import classify_query
from shopsage.chain.chitchat_chain import get_chitchat_response
from shopsage.agent.shopping_agent import get_shopping_response
from shopsage.tool.visual_search import search_by_image
from shopsage.tool.price_scraper import fetch_prices, results_to_dict
from shopsage.monetise.deal_alerts import DealAlertStore
from shopsage.workers.price_checker import PriceCheckerWorker
from shopsage.memory.user_profile import ProfileStore
from shopsage.memory.feedback_store import FeedbackStore
from shopsage.history.conversation_store import ConversationStore
from shopsage.history.exporter import export_to_json, export_to_csv, export_to_markdown
from shopsage.monitoring.health import HealthChecker
from shopsage.cache.ttl_cache import price_cache, review_cache, embedding_cache
from shopsage.webhooks.webhook_store import WebhookStore
from shopsage.webhooks.dispatcher import WebhookDispatcher
from shopsage.analytics.search_tracker import SearchTracker
from shopsage.security.middleware import SecurityHeadersMiddleware, RateLimitHeadersMiddleware
from shopsage.events.event_bus import get_event_bus, Event
from shopsage.events.handlers import register_all_handlers
from shopsage.notifications.notification_center import NotificationCenter
from shopsage.workers.job_queue import JobQueue
from shopsage.admin.dashboard_api import AdminDashboard
from shopsage.router.api_router import router as api_router
from shopsage.config import DB_PATH

# ─── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shopsage")

# ─── FastAPI App ───────────────────────────────────────────────────────
app = FastAPI(
    title="ShopSage AI",
    description="AI-powered intelligent shopping assistant with user memory",
    version="2.0.0",
)

# Add Security Middlewares
app.add_middleware(RateLimitHeadersMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# User profile store
_profile_store = ProfileStore(db_path=DB_PATH)

# Background price checker
_price_checker = PriceCheckerWorker(db_path=DB_PATH)

# Feedback store
_feedback_store = FeedbackStore(db_path=DB_PATH)

# Conversation history
_conversation_store = ConversationStore(db_path=DB_PATH)

# Webhook system
_webhook_store = WebhookStore(db_path=DB_PATH)
_webhook_dispatcher = WebhookDispatcher(db_path=DB_PATH)

# Search analytics
_search_tracker = SearchTracker(db_path=DB_PATH)

# Notification center
_notification_center = NotificationCenter(db_path=DB_PATH)

# Job queue
_job_queue = JobQueue(db_path=DB_PATH)

# Admin dashboard
_admin_dashboard = AdminDashboard(db_path=DB_PATH)

# Include SaaS API Router
app.include_router(api_router)


@app.on_event("startup")
async def startup_event():
    """Start background workers and event bus on app startup."""
    _price_checker.start()
    _job_queue.start_worker(poll_interval=3.0)
    register_all_handlers()
    logger.info("[App] Background workers, job queue, and event bus started")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully stop background workers."""
    await _price_checker.stop()
    logger.info("[App] Background workers stopped")


@app.get("/worker/status")
async def worker_status():
    """Get the price checker worker status and stats."""
    return {
        "running": _price_checker.is_running,
        "stats": _price_checker.stats,
    }


_health_checker = HealthChecker(db_path=DB_PATH)


@app.get("/health")
async def health_check():
    """Comprehensive health check for monitoring and load balancers."""
    result = _health_checker.check_all()
    status_code = 200 if result["status"] == "healthy" else 503
    return JSONResponse(content=result, status_code=status_code)


@app.get("/cache/stats")
async def cache_stats():
    """Return hit/miss stats for all cache layers."""
    return {
        "prices": price_cache.stats,
        "reviews": review_cache.stats,
        "embeddings": embedding_cache.stats,
    }


# ─── Request / Response Models ─────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    route: str
    session_id: str


# ─── Routes ────────────────────────────────────────────────────────────


@app.get("/")
async def home(request: Request):
    """Serve the chat interface."""
    return templates.TemplateResponse(request, "index.html")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a chat message and return an AI response.

    The message is first classified by the Semantic Router,
    then routed to either the Chitchat Chain or Shopping Agent.
    User profile is loaded for personalized responses.
    """
    message = request.message.strip()
    session_id = request.session_id or str(uuid.uuid4())

    if not message:
        return ChatResponse(
            response="Please type a message to get started! 😊",
            route="chitchat",
            session_id=session_id,
        )

    logger.info(f"[Session {session_id[:8]}] Message: {message[:50]}...")

    # Step 1: Classify the query
    route = classify_query(message)
    logger.info(f"[Session {session_id[:8]}] Route: {route}")

    # Step 2: Route to appropriate handler
    if route == "shopping":
        response = get_shopping_response(message, session_id)
    else:
        response = get_chitchat_response(message, session_id)

    logger.info(f"[Session {session_id[:8]}] Response: {response[:80]}...")

    # Save to conversation history
    _conversation_store.save_exchange(session_id, message, response, route)

    # Track search query for analytics
    _search_tracker.track(session_id, message, route)

    return ChatResponse(response=response, route=route, session_id=session_id)


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@app.post("/chat-image")
async def chat_with_image(
    file: UploadFile = File(...),
    message: str = Form(""),
    session_id: str = Form(""),
):
    """
    Process an image upload for visual product search.

    The image is analyzed by Gemini Vision to extract product attributes,
    then matched against the inventory database.

    Args:
        file: The uploaded product image (JPEG, PNG, WebP).
        message: Optional text message accompanying the image.
        session_id: Session identifier for continuity.
    """
    session_id = session_id or str(uuid.uuid4())

    # Validate file type
    content_type = file.content_type or "image/jpeg"
    if content_type not in ALLOWED_IMAGE_TYPES:
        return JSONResponse(
            status_code=400,
            content={
                "response": "Please upload a valid image (JPEG, PNG, or WebP).",
                "route": "error",
                "session_id": session_id,
            },
        )

    # Read and validate size (max 10MB)
    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        return JSONResponse(
            status_code=400,
            content={
                "response": "Image is too large. Please upload an image under 10MB.",
                "route": "error",
                "session_id": session_id,
            },
        )

    logger.info(
        f"[Session {session_id[:8]}] Visual search: "
        f"{file.filename} ({len(image_bytes)} bytes)"
    )

    # Run visual search pipeline
    result = search_by_image(image_bytes, content_type)

    description = result["description"]
    products = result["results"]

    # Build response combining vision analysis + search results
    if description:
        user_context = f"Looking for: {message}" if message else ""
        response_text = (
            f"**I see:** {description}\n\n"
            f"{user_context}\n\n"
            f"**Here's what I found in our inventory:**\n\n{products}"
        )
    else:
        response_text = (
            "I couldn't analyze this image clearly. "
            "Could you try uploading a clearer product photo?"
        )

    return {
        "response": response_text,
        "route": "visual_search",
        "session_id": session_id,
        "image_description": description,
    }


@app.get("/compare-prices")
async def compare_prices_endpoint(q: str = ""):
    """
    Compare live prices for a product across Amazon, Flipkart, and Croma.

    Args:
        q: Product search query string.

    Returns:
        JSON with best deal, all results, and metadata.
    """
    if not q.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Please provide a product query using ?q=product+name"},
        )

    logger.info(f"[API] Price comparison: {q[:50]}")

    results = await fetch_prices(q.strip())
    return results_to_dict(q.strip(), results)


@app.get("/profile/{session_id}")
async def get_user_profile(session_id: str):
    """
    Retrieve the user profile for a given session.

    Returns the user's stored preferences including budget,
    favourite brands, style tags, and sizes.
    """
    profile = _profile_store.get_profile(session_id)

    if profile is None:
        return {"exists": False, "profile": None}

    return {
        "exists": True,
        "profile": {
            "name": profile.name,
            "budget_min": profile.budget_min,
            "budget_max": profile.budget_max,
            "preferred_brands": profile.preferred_brands,
            "preferred_colors": profile.preferred_colors,
            "style_tags": profile.style_tags,
            "gender": profile.gender,
            "sizes": profile.sizes,
        },
    }


# ─── Deal Alert Endpoints ──────────────────────────────────────────────

_deal_store = DealAlertStore(db_path=DB_PATH)


class AlertRequest(BaseModel):
    product_query: str
    target_price: float
    session_id: str


@app.post("/alerts")
async def create_alert(req: AlertRequest):
    """
    Create a new price drop alert.

    The user will be notified when the product price drops
    below the specified target.
    """
    if req.target_price <= 0:
        return JSONResponse(
            status_code=400,
            content={"error": "Target price must be greater than 0."},
        )

    watch = _deal_store.create_watch(
        user_id=req.session_id,
        product_query=req.product_query,
        target_price=req.target_price,
    )
    return {
        "success": True,
        "alert_id": watch.id,
        "product": watch.product_query,
        "target_price": watch.target_price,
    }


@app.get("/alerts/{session_id}")
async def list_alerts(session_id: str):
    """
    List all active price alerts for a user session.
    """
    watches = _deal_store.get_user_watches(session_id, active_only=True)
    return {
        "count": len(watches),
        "alerts": [
            {
                "id": w.id,
                "product": w.product_query,
                "target_price": w.target_price,
                "current_price": w.current_price,
                "lowest_price": w.lowest_price,
                "triggered": w.triggered,
                "created_at": w.created_at,
            }
            for w in watches
        ],
    }


@app.delete("/alerts/{session_id}/{alert_id}")
async def delete_alert(session_id: str, alert_id: int):
    """
    Deactivate a price alert.
    """
    success = _deal_store.deactivate_watch(alert_id, session_id)
    if success:
        return {"success": True, "message": f"Alert #{alert_id} removed."}
    return JSONResponse(
        status_code=404,
        content={"error": f"Alert #{alert_id} not found."},
    )

# ─── Feedback & Dashboard Endpoints ────────────────────────────────────

class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    rating: int
    comment: Optional[str] = None

@app.post("/feedback")
async def log_feedback(req: FeedbackRequest):
    """
    Log user feedback (thumbs up/down) for an AI response.
    """
    _feedback_store.log_feedback(
        session_id=req.session_id,
        message_id=req.message_id,
        rating=req.rating,
        comment=req.comment
    )
    return {"success": True}

@app.get("/dashboard")
async def dashboard_page(request: Request):
    """
    Render the Admin SaaS Dashboard page.
    """
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/api/v1/dashboard/stats")
async def dashboard_stats():
    """
    Get aggregated stats for the dashboard.
    Mocking tenant count for now.
    """
    feedback_stats = _feedback_store.get_feedback_stats()
    return {
        "tenant_count": 3,  # Mocked active tenants
        "api_calls": 1250,  # Mocked total API calls
        "feedback_stats": feedback_stats
    }


# ─── Conversation History Endpoints ────────────────────────────────────


@app.get("/history/{session_id}")
async def get_conversation_history(
    session_id: str, limit: int = 50, offset: int = 0
):
    """Retrieve conversation history for a session."""
    messages = _conversation_store.get_history(session_id, limit, offset)
    stats = _conversation_store.get_session_stats(session_id)
    return {
        "session_id": session_id,
        "stats": stats,
        "messages": [
            {
                "id": m.id, "role": m.role, "content": m.content,
                "route": m.route, "timestamp": m.timestamp,
            }
            for m in messages
        ],
    }


@app.get("/history/{session_id}/export")
async def export_conversation(session_id: str, format: str = "json"):
    """
    Export conversation history in JSON, CSV, or Markdown format.
    """
    messages = _conversation_store.get_history(session_id, limit=500)
    if not messages:
        return JSONResponse(status_code=404, content={"error": "No messages found."})

    if format == "csv":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=export_to_csv(messages),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=shopsage_{session_id[:8]}.csv"},
        )
    elif format == "markdown":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=export_to_markdown(messages),
            media_type="text/markdown",
        )
    else:
        return JSONResponse(content=json.loads(export_to_json(messages)))


@app.get("/history/{session_id}/search")
async def search_conversation(session_id: str, q: str = ""):
    """Search through a session's conversation history."""
    if not q.strip():
        return JSONResponse(status_code=400, content={"error": "Query parameter 'q' is required."})

    results = _conversation_store.search_history(session_id, q.strip())
    return {
        "query": q,
        "count": len(results),
        "results": [
            {"id": m.id, "role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in results
        ],
    }


@app.delete("/history/{session_id}")
async def delete_conversation(session_id: str):
    """Delete all messages in a session."""
    count = _conversation_store.delete_session(session_id)
    return {"deleted": count, "session_id": session_id}


# ─── Webhook Endpoints ─────────────────────────────────────────────────


class WebhookRegisterRequest(BaseModel):
    url: str
    events: Optional[list] = None


@app.post("/webhooks")
async def register_webhook(
    req: WebhookRegisterRequest,
    session_id: str = "",
):
    """
    Register a webhook URL to receive event notifications.
    """
    tenant_id = session_id or "default"
    wh = _webhook_store.register(
        tenant_id=tenant_id,
        url=req.url,
        events=req.events,
    )
    return {
        "id": wh.id,
        "url": wh.url,
        "events": wh.events,
        "secret": wh.secret,
    }


@app.get("/webhooks/{tenant_id}")
async def list_webhooks(tenant_id: str):
    """List all webhooks for a tenant."""
    hooks = _webhook_store.get_by_tenant(tenant_id)
    return {
        "count": len(hooks),
        "webhooks": [
            {
                "id": h.id, "url": h.url, "events": h.events,
                "is_active": h.is_active,
                "delivery_count": h.delivery_count,
                "failure_count": h.failure_count,
            }
            for h in hooks
        ],
    }


@app.delete("/webhooks/{tenant_id}/{webhook_id}")
async def delete_webhook(tenant_id: str, webhook_id: str):
    """Deactivate a webhook."""
    success = _webhook_store.deactivate(webhook_id, tenant_id)
    if success:
        return {"success": True}
    return JSONResponse(status_code=404, content={"error": "Webhook not found."})


@app.get("/webhooks/{webhook_id}/logs")
async def webhook_logs(webhook_id: str, limit: int = 20):
    """Get delivery logs for a webhook."""
    logs = _webhook_store.get_delivery_logs(webhook_id, limit)
    return {"count": len(logs), "logs": logs}


# ─── Search Analytics Endpoints ────────────────────────────────────────


@app.get("/analytics/search/popular")
async def popular_searches(limit: int = 20, hours: int = 24):
    """Get the most popular search queries."""
    return {
        "period_hours": hours,
        "queries": _search_tracker.get_popular_queries(limit, hours),
    }


@app.get("/analytics/search/demand")
async def demand_signals(limit: int = 20, hours: int = 48):
    """Get zero-result queries — products users want but can't find."""
    return {
        "period_hours": hours,
        "zero_result_queries": _search_tracker.get_zero_result_queries(limit, hours),
    }


@app.get("/analytics/search/volume")
async def search_volume(hours: int = 24):
    """Get search volume statistics."""
    return _search_tracker.get_search_volume(hours)


@app.get("/analytics/search/trend")
async def search_trend(hours: int = 24):
    """Get hourly search count trend."""
    return {
        "period_hours": hours,
        "trend": _search_tracker.get_hourly_trend(hours),
    }


# ─── Notification Endpoints ────────────────────────────────────────────


@app.get("/notifications/{tenant_id}")
async def get_notifications(tenant_id: str, unread_only: bool = False, limit: int = 50):
    """Get notifications for a tenant."""
    if unread_only:
        notifs = _notification_center.get_unread(tenant_id, limit)
    else:
        notifs = _notification_center.get_all(tenant_id, limit)
    return {
        "count": len(notifs),
        "unread_count": _notification_center.get_unread_count(tenant_id),
        "notifications": notifs,
    }


@app.post("/notifications/{tenant_id}/{notification_id}/read")
async def mark_notification_read(tenant_id: str, notification_id: str):
    """Mark a notification as read."""
    success = _notification_center.mark_read(notification_id, tenant_id)
    if success:
        return {"success": True}
    return JSONResponse(status_code=404, content={"error": "Notification not found."})


@app.post("/notifications/{tenant_id}/read-all")
async def mark_all_read(tenant_id: str):
    """Mark all notifications as read."""
    count = _notification_center.mark_all_read(tenant_id)
    return {"success": True, "marked_read": count}


@app.get("/events/stats")
async def event_bus_stats():
    """Get event bus statistics and history."""
    bus = get_event_bus()
    return {
        "stats": bus.get_stats(),
        "subscriptions": bus.list_subscriptions(),
        "recent_events": bus.get_history(limit=20),
    }


# ─── Job Queue Endpoints ───────────────────────────────────────────────


class EnqueueJobRequest(BaseModel):
    job_type: str
    payload: Optional[dict] = None
    priority: int = 0
    delay_seconds: int = 0


@app.post("/jobs")
async def enqueue_job(req: EnqueueJobRequest):
    """Enqueue a background job."""
    job_id = _job_queue.enqueue(
        req.job_type, req.payload, req.priority, delay_seconds=req.delay_seconds
    )
    return {"job_id": job_id, "status": "pending"}


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get job status."""
    job = _job_queue.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found."})
    return job


@app.get("/jobs")
async def get_queue_stats():
    """Get job queue statistics."""
    return _job_queue.get_stats()


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a pending job."""
    if _job_queue.cancel_job(job_id):
        return {"success": True}
    return JSONResponse(status_code=404, content={"error": "Job not found or not pending."})


# ─── Admin Dashboard Endpoint ─────────────────────────────────────────


@app.get("/admin/dashboard")
async def admin_dashboard():
    """Get aggregated admin dashboard metrics."""
    return _admin_dashboard.get_overview()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions gracefully."""
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "response": "Something went wrong on our end. Please try again.",
            "route": "error",
            "session_id": "",
        },
    )


# ─── Run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
