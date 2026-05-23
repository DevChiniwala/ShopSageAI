import logging
from typing import Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from shopsage.auth.api_key import verify_api_key
from shopsage.analytics.tracker import AnalyticsStore
from shopsage.agent.shopping_agent import get_shopping_response

logger = logging.getLogger("shopsage.router.api_router")

router = APIRouter(prefix="/api/v1")
analytics_store = AnalyticsStore()

class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's input message")
    session_id: str = Field(..., description="Unique session identifier for the user conversation")

class ChatResponse(BaseModel):
    response: str
    session_id: str

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    tenant: Dict[str, Any] = Depends(verify_api_key)
) -> ChatResponse:
    """
    SaaS Chat Endpoint.
    Requires a valid X-API-Key header.
    Processes the user's message and returns the shopping agent's response.
    """
    logger.info(f"Received chat request from tenant '{tenant['name']}' (Session: {request.session_id})")
    
    # Process through agent
    agent_response = get_shopping_response(request.message, request.session_id)
    
    # Log analytics
    analytics_store.log_event(
        tenant_id=tenant["id"],
        session_id=request.session_id,
        event_type="chat",
        event_data={
            "message_length": len(request.message),
            "response_length": len(agent_response)
        }
    )
    
    return ChatResponse(
        response=agent_response,
        session_id=request.session_id
    )

@router.get("/analytics/summary")
async def get_analytics_summary(
    tenant: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get high-level summary statistics of SaaS usage.
    Requires a valid X-API-Key header.
    """
    # For now, return global stats. In a real multi-tenant app, 
    # this might be restricted to an admin or filtered by tenant_id.
    stats = analytics_store.get_summary_stats()
    return {
        "tenant_name": tenant["name"],
        "statistics": stats
    }
