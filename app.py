"""
ShopSage AI - FastAPI Application Entry Point.

An AI-powered intelligent shopping assistant combining LLMs,
RAG, Semantic Routing, User Memory, and advanced product search.
"""

import uuid
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
from shopsage.memory.user_profile import ProfileStore
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
