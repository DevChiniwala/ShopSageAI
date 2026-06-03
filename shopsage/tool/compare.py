"""
Product Comparison Engine — Side-by-side product analysis.

Compares products across specs, pricing, reviews, and provides
an AI-generated verdict with pros/cons.
"""

import json
import logging
from google import genai
from shopsage.config import settings

logger = logging.getLogger("shopsage.tools.compare")

_client = genai.Client(api_key=settings.GOOGLE_API_KEY)


COMPARE_PROMPT = """You are ShopSage AI's product comparison expert.

Compare these products: {products}

Generate a detailed comparison with:
1. A structured comparison table covering: Price, Material/Build, Key Features, Best For, Rating (out of 5)
2. Pros and Cons for each product (3 each)
3. A final verdict: which is "Best Overall", "Best Value", and "Best Quality"
4. A one-paragraph recommendation

Return as JSON:
{{
  "products": [
    {{
      "name": "...",
      "price": "...",
      "specs": {{"material": "...", "key_features": ["..."], "best_for": "...", "rating": 4.5}},
      "pros": ["...", "...", "..."],
      "cons": ["...", "...", "..."]
    }}
  ],
  "verdict": {{
    "best_overall": "product name",
    "best_value": "product name",
    "best_quality": "product name"
  }},
  "recommendation": "One paragraph recommendation text"
}}

Output ONLY the JSON. No markdown fences.
"""


def compare_products(product_names: list[str]) -> dict:
    """
    Compare 2-4 products using AI analysis.

    Args:
        product_names: List of product names/descriptions to compare.

    Returns:
        Structured comparison with specs, pros/cons, and verdict.
    """
    if len(product_names) < 2:
        return {"error": "Need at least 2 products to compare"}
    if len(product_names) > 4:
        product_names = product_names[:4]

    try:
        products_str = " vs ".join(product_names)
        prompt = COMPARE_PROMPT.format(products=products_str)

        response = _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}],
        )

        raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        result = json.loads(raw)
        logger.info(f"[Compare] Compared {len(product_names)} products")
        return result

    except json.JSONDecodeError:
        logger.warning("[Compare] Failed to parse JSON")
        return {"raw_response": response.text.strip(), "products": []}
    except Exception as e:
        logger.error(f"[Compare] Error: {e}")
        return {"error": str(e), "products": []}


def quick_compare(product_a: str, product_b: str) -> str:
    """
    Quick natural-language comparison of two products.
    Returns a concise paragraph.
    """
    try:
        prompt = f"""Compare "{product_a}" vs "{product_b}" in 3-4 sentences.
Cover price range, quality, and which is better for whom. Be specific and helpful."""

        response = _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}],
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"[Compare] Quick compare failed: {e}")
        return f"Sorry, I couldn't compare these products right now: {e}"
