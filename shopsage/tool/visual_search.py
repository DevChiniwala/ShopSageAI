"""
Visual Search Tool — Image-based product discovery for ShopSage AI.

Uses Gemini 2.0 Flash's multimodal capability to analyze uploaded
product images, extract visual attributes (color, type, brand, style),
and search across live stores for matching products.
"""

import base64
import json
import logging
from google import genai
from shopsage.config import settings
from shopsage.utils.data_loader import ProductDataLoader

logger = logging.getLogger("shopsage.tools.visual")

_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
_loader = ProductDataLoader()

# ─── Vision Prompt ─────────────────────────────────────────────────────

VISION_PROMPT = """Analyze this product image for a shopping search engine.

Extract the following attributes and return them as JSON:
{
  "product_type": "e.g., t-shirt, jacket, shoes, dress, handbag",
  "color": "primary color(s)",
  "brand": "brand name if visible, otherwise 'Unknown'",
  "material": "if identifiable, e.g., cotton, leather, denim",
  "style": "casual, formal, sporty, streetwear, ethnic, minimalist",
  "gender": "men, women, unisex",
  "features": "distinctive features like print pattern, collar type, fit",
  "search_query": "a natural language search query to find this product online",
  "estimated_price_range": "e.g., $20-$50 or ₹1,000-₹3,000"
}

Output ONLY the JSON, no markdown fences, no explanation.
"""

STYLE_MATCH_PROMPT = """Based on this product image, suggest 3 complementary items
that would create a complete outfit or look. For each item, provide:
- item_type (e.g., "slim fit chinos")
- color suggestion
- style tip (why it pairs well)

Return as JSON array. Output ONLY the JSON, no markdown fences.
"""


# ─── Core Functions ────────────────────────────────────────────────────


def analyze_product_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Use Gemini 2.0 Flash Vision to describe a product in an image.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        mime_type: MIME type of the image (jpeg, png, webp).

    Returns:
        A concise text description of the product for search.
    """
    try:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        response = _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                {"text": VISION_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": b64_data}},
            ],
        )

        description = response.text.strip()
        logger.info(f"[Visual] Image analyzed: {description[:80]}...")
        return description

    except Exception as e:
        logger.error(f"[Visual] Image analysis failed: {e}")
        return ""


def analyze_product_image_structured(
    image_bytes: bytes, mime_type: str = "image/jpeg"
) -> dict:
    """
    Analyze a product image and return structured attributes.

    Returns:
        Dict with product_type, color, brand, style, search_query, etc.
    """
    raw = analyze_product_image(image_bytes, mime_type)
    if not raw:
        return {}

    try:
        # Try parsing as JSON
        cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: return as comma-separated description
        return {
            "product_type": "product",
            "search_query": raw,
            "raw_description": raw,
        }


def get_style_suggestions(
    image_bytes: bytes, mime_type: str = "image/jpeg"
) -> list:
    """
    Given a product image, suggest complementary items to complete the look.

    Returns:
        List of dicts with item_type, color, and style_tip.
    """
    try:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        response = _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                {"text": STYLE_MATCH_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": b64_data}},
            ],
        )

        raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"[Visual] Style suggestion failed: {e}")
        return []


def search_by_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Full visual search pipeline: analyze image → search products.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        mime_type: MIME type of the image.

    Returns:
        Dict with 'analysis' (structured attributes), 'description',
        'results' (matching products), and 'style_suggestions'.
    """
    # Step 1: Analyze the image
    analysis = analyze_product_image_structured(image_bytes, mime_type)

    if not analysis:
        return {
            "analysis": {},
            "description": "",
            "results": "I couldn't analyze this image. Please try a clearer product photo.",
            "style_suggestions": [],
        }

    # Step 2: Build search query
    search_query = analysis.get("search_query", "")
    if not search_query:
        # Build from parts
        parts = [
            analysis.get("color", ""),
            analysis.get("material", ""),
            analysis.get("product_type", ""),
            analysis.get("brand", ""),
        ]
        search_query = " ".join(p for p in parts if p and p.lower() != "unknown")

    description = search_query
    logger.info(f"[Visual] Searching for: {description}")

    # Step 3: Search with extracted description
    results = _loader.search_products(description)

    # If no results, try individual attribute terms
    if "No products found" in results:
        fallback_terms = [
            analysis.get("product_type", ""),
            analysis.get("color", ""),
            analysis.get("style", ""),
        ]
        for term in fallback_terms:
            if term and len(term) > 2:
                results = _loader.search_products(term)
                if "No products found" not in results:
                    break

    # Step 4: Get style suggestions (async-friendly in future)
    style_suggestions = get_style_suggestions(image_bytes, mime_type)

    return {
        "analysis": analysis,
        "description": description,
        "results": results,
        "style_suggestions": style_suggestions,
    }
