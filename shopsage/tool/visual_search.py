"""
Visual Search Tool — Image-based product discovery for ShopSage AI.

Uses Gemini 2.0 Flash's multimodal capability to analyze uploaded
product images, extract visual attributes (color, type, brand, style),
and search the inventory for matching products.
"""

import base64
import logging
from google import genai
from shopsage.config import GOOGLE_API_KEY
from shopsage.utils.data_loader import ProductDataLoader

logger = logging.getLogger("shopsage.tools.visual")

_client = genai.Client(api_key=GOOGLE_API_KEY)
_loader = ProductDataLoader()

# ─── Vision Prompt ─────────────────────────────────────────────────────

VISION_PROMPT = """Analyze this product image for a shopping search engine.

Extract the following attributes in a concise, comma-separated format:
- Product type (e.g., t-shirt, jacket, shoes, dress, polo)
- Color(s)
- Brand (if logo or text is visible, otherwise say "unknown")
- Material (if identifiable, e.g., cotton, leather, denim)
- Style (casual, formal, sporty, streetwear, ethnic)
- Gender target (men, women, unisex)
- Any distinctive features (print pattern, collar type, fit)

Output ONLY the comma-separated description, nothing else.
Example: "red cotton polo shirt, Nike, casual, men, slim fit, pique knit"
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


def search_by_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Full visual search pipeline: analyze image → search products.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        mime_type: MIME type of the image.

    Returns:
        Dict with 'description' (what the AI saw) and 'results' (matching products).
    """
    description = analyze_product_image(image_bytes, mime_type)

    if not description:
        return {
            "description": "",
            "results": "I couldn't analyze this image. Please try a clearer product photo.",
        }

    # Search using extracted description terms
    # Split description and search with key terms
    search_terms = [term.strip() for term in description.split(",")]

    # Try full description first
    results = _loader.search_products(description)

    # If no results, try individual terms
    if "No products found" in results and len(search_terms) > 1:
        for term in search_terms[:3]:  # try top 3 terms
            if len(term) > 2:
                results = _loader.search_products(term)
                if "No products found" not in results:
                    break

    return {
        "description": description,
        "results": results,
    }
