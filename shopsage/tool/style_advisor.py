"""
AI Style Advisor — Intelligent outfit and styling recommendations.

Uses Gemini to generate personalized outfit suggestions based on
occasion, budget, style preferences, and user history.
"""

import json
import logging
from google import genai
from shopsage.config import settings

logger = logging.getLogger("shopsage.tools.style")

_client = genai.Client(api_key=settings.GOOGLE_API_KEY)


STYLE_PROMPT = """You are ShopSage AI's expert fashion stylist. A user needs outfit advice.

User request: {request}
Budget: {budget}
Style preference: {style}
Gender: {gender}
Occasion: {occasion}

Generate exactly 3 complete outfit suggestions. For each outfit:
1. Give it a creative name (e.g., "Urban Minimalist", "Power Meeting")
2. Include 4-5 pieces: top, bottom, shoes, and 1-2 accessories
3. For each piece, provide:
   - item: specific product description (e.g., "navy slim-fit Oxford shirt")
   - estimated_price: realistic price in INR
   - why: one-line styling tip explaining the choice
4. Add an overall "vibe" description for the outfit

Return as JSON:
{{
  "outfits": [
    {{
      "name": "Outfit Name",
      "vibe": "Short vibe description",
      "pieces": [
        {{"item": "...", "category": "top|bottom|shoes|accessory", "estimated_price": "₹X,XXX", "why": "..."}}
      ],
      "total_estimated": "₹X,XXX"
    }}
  ],
  "styling_tips": ["tip1", "tip2", "tip3"]
}}

Output ONLY the JSON. No markdown fences.
"""


def get_outfit_suggestions(
    request: str = "",
    budget: str = "₹5,000-₹10,000",
    style: str = "casual",
    gender: str = "unisex",
    occasion: str = "everyday",
) -> dict:
    """
    Generate AI-powered outfit suggestions.

    Args:
        request: User's specific request (e.g., "date night outfit")
        budget: Budget range
        style: Preferred style (casual, formal, streetwear, etc.)
        gender: Target gender
        occasion: Event or situation

    Returns:
        Dict with outfit suggestions and styling tips.
    """
    try:
        prompt = STYLE_PROMPT.format(
            request=request or "Suggest a stylish outfit",
            budget=budget,
            style=style,
            gender=gender,
            occasion=occasion,
        )

        response = _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}],
        )

        raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        result = json.loads(raw)
        logger.info(f"[StyleAdvisor] Generated {len(result.get('outfits', []))} outfits")
        return result

    except json.JSONDecodeError:
        logger.warning("[StyleAdvisor] Failed to parse JSON, returning raw text")
        return {"raw_response": response.text.strip(), "outfits": [], "styling_tips": []}
    except Exception as e:
        logger.error(f"[StyleAdvisor] Error: {e}")
        return {"error": str(e), "outfits": [], "styling_tips": []}


def analyze_wardrobe_gap(owned_items: list[str]) -> dict:
    """
    Given a list of items the user owns, suggest what's missing
    for a versatile wardrobe.
    """
    try:
        prompt = f"""A user owns these clothing items: {', '.join(owned_items)}.

Analyze their wardrobe and suggest 5 key items they're missing
for a versatile, well-rounded wardrobe. For each:
- item: specific description
- priority: high/medium/low
- reason: why this fills a gap

Return as JSON: {{"suggestions": [{{"item": "...", "priority": "...", "reason": "..."}}]}}
Output ONLY JSON."""

        response = _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}],
        )
        raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"[StyleAdvisor] Wardrobe analysis failed: {e}")
        return {"suggestions": []}
