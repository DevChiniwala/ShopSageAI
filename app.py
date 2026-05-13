"""
ShopSage AI - FastAPI Application Entry Point.

An AI-powered intelligent shopping assistant combining LLMs,
RAG, Semantic Routing, and advanced product search.
"""

import uuid
import logging
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from shopsage.router.semantic_router import classify_query
from shopsage.chain.chitchat_chain import get_chitchat_response
from shopsage.agent.shopping_agent import get_shopping_response

# ─── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shopsage")

# ─── FastAPI App ───────────────────────────────────────────────────────
app = FastAPI(
    title="ShopSage AI",
    description="AI-powered intelligent shopping assistant",
    version="1.0.0",
)

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

    return ChatResponse(response=response, route=route, session_id=session_id)


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
