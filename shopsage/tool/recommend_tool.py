"""
Recommendation Tool — Profile-aware product suggestions for ShopSage AI.

Uses the user's stored preferences (brands, colors, budget, style tags)
to generate personalized "You might also like" recommendations by
querying the product search index with profile-derived filters.
"""

import logging
from langchain_core.tools import tool
from shopsage.tool.preference_tool import get_profile_context
from shopsage.memory.user_profile import ProfileStore
from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.tools.recommend")

_profile_store = ProfileStore(db_path=DB_PATH)


@tool
def get_recommendations(session_id: str, category: str = "") -> str:
    """
    Generate personalized product recommendations based on the user's profile.

    Uses stored preferences (brands, budget, colors, style) to build
    a targeted search query. Call this when the user asks for:
    - "What do you recommend for me?"
    - "Suggest something I might like"
    - "Any recommendations?"
    - "Show me products matching my taste"
    - "What should I buy?"

    Args:
        session_id: The user's session ID to look up their profile.
        category: Optional product category hint (e.g. "shoes", "jackets").

    Returns:
        A search query string tailored to the user's preferences,
        or a fallback message if no profile exists.
    """
    try:
        profile = _profile_store.get_profile(session_id)

        if profile is None:
            return (
                "I don't have your preferences saved yet! "
                "Tell me about your style, favourite brands, "
                "budget range, and preferred colours, and I'll give you "
                "personalized recommendations.\n\n"
                "For example: 'I like Nike and Adidas, budget 2000-5000, "
                "I prefer black and navy colours, casual style.'"
            )

        # Build a smart search query from profile data
        query_parts = []

        if category:
            query_parts.append(category)

        if profile.preferred_brands:
            top_brands = profile.preferred_brands[:3]
            query_parts.append(" or ".join(top_brands))

        if profile.style_tags:
            query_parts.append(" ".join(profile.style_tags[:2]))

        if profile.preferred_colors:
            query_parts.append(profile.preferred_colors[0])

        if profile.gender:
            query_parts.append(f"{profile.gender}'s")

        # Budget context
        budget_str = ""
        if profile.budget_min and profile.budget_max:
            budget_str = f" (budget ₹{profile.budget_min:,.0f} – ₹{profile.budget_max:,.0f})"
        elif profile.budget_max:
            budget_str = f" (under ₹{profile.budget_max:,.0f})"

        search_query = " ".join(query_parts) if query_parts else "trending popular products"

        # Build the recommendation context
        rec_context = (
            f"🎯 **Personalized Recommendations for {profile.name or 'You'}**\n\n"
            f"Based on your profile, I'm searching for: **{search_query}**{budget_str}\n\n"
            f"📋 **Your Preferences:**\n"
        )

        if profile.preferred_brands:
            rec_context += f"  • Brands: {', '.join(profile.preferred_brands)}\n"
        if profile.preferred_colors:
            rec_context += f"  • Colors: {', '.join(profile.preferred_colors)}\n"
        if profile.style_tags:
            rec_context += f"  • Style: {', '.join(profile.style_tags)}\n"
        if profile.sizes:
            rec_context += f"  • Sizes: {', '.join(f'{k}:{v}' for k, v in profile.sizes.items())}\n"

        rec_context += (
            f"\n💡 Now let me search the product catalog with these preferences. "
            f"Use `product_search` with query: '{search_query}'"
        )

        logger.info(
            f"[Recommend] Generated query '{search_query}' for session {session_id[:8]}"
        )
        return rec_context

    except Exception as e:
        logger.error(f"[Recommend] Error: {e}")
        return "Sorry, I couldn't generate recommendations right now. Please try again."


@tool
def trending_products(category: str = "fashion") -> str:
    """
    Show currently trending products across the platform.

    Call this when the user asks:
    - "What's trending?"
    - "What's popular right now?"
    - "Show me bestsellers"
    - "What are other people buying?"

    Args:
        category: Product category to check trends for.

    Returns:
        A curated list of trending search queries.
    """
    trends = {
        "fashion": [
            "🔥 Oversized cotton t-shirts",
            "👟 Retro running sneakers",
            "🧥 Lightweight bomber jackets",
            "👗 Floral midi dresses",
            "🎒 Minimalist laptop backpacks",
        ],
        "electronics": [
            "🎧 Noise-cancelling earbuds under ₹3000",
            "📱 Budget smartphones with 5G",
            "⌚ Fitness smartwatches",
            "🔌 65W GaN fast chargers",
            "🖥️ Portable monitors for WFH",
        ],
        "home": [
            "🛋️ Ergonomic desk chairs",
            "💡 Smart LED strip lights",
            "🍳 Cast iron cookware sets",
            "🌱 Indoor planters with self-watering",
            "🧹 Robot vacuum cleaners",
        ],
    }

    items = trends.get(category.lower(), trends["fashion"])

    return (
        f"📈 **Trending in {category.title()} Right Now:**\n\n"
        + "\n".join(f"  {i+1}. {item}" for i, item in enumerate(items))
        + "\n\n💬 Ask me about any of these to see products, prices, and reviews!"
    )
