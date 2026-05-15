"""
Preference Tool — Lets the shopping agent save discovered user preferences.

When the agent detects preference signals in conversation (budget mentions,
brand love, size info, style keywords), it calls this tool to persist them
in the user's profile for future personalization.
"""

import json
import logging
from langchain_core.tools import tool
from shopsage.memory.user_profile import ProfileStore
from shopsage.config import DB_PATH

logger = logging.getLogger("shopsage.tools")

_store = ProfileStore(db_path=DB_PATH)


@tool
def save_user_preference(user_id: str, preference_json: str) -> str:
    """
    Save a discovered user preference to their profile.

    Call this tool whenever you learn something new about the user's
    shopping preferences during conversation. This helps personalize
    future recommendations.

    Examples of when to call this:
    - User says "I like Nike" → {"preferred_brands": ["Nike"]}
    - User says "my budget is 5000" → {"budget_max": 5000}
    - User says "I wear size L" → {"sizes": {"shirt": "L"}}
    - User says "I prefer cotton" → {"preferred_materials": ["Cotton"]}
    - User says "I love minimal style" → {"style_tags": ["minimal"]}
    - User says "I'm looking for women's clothing" → {"gender": "Women"}

    Args:
        user_id: The current session/user ID.
        preference_json: JSON string with preference key-value pairs.
            Valid keys: name, budget_min, budget_max, preferred_brands,
            preferred_colors, preferred_materials, style_tags, gender,
            sizes, notes.

    Returns:
        Confirmation message with saved preferences summary.
    """
    try:
        prefs = json.loads(preference_json)

        if not isinstance(prefs, dict) or not prefs:
            return "No valid preferences provided."

        profile = _store.merge_preferences(user_id, prefs)

        saved_items = []
        for key, value in prefs.items():
            if value:
                saved_items.append(f"{key}: {value}")

        logger.info(
            f"[Preference] Saved for {user_id[:8]}: {', '.join(saved_items)}"
        )

        return (
            f"Preferences saved successfully. "
            f"I'll remember: {', '.join(saved_items)}. "
            f"This will help me personalize future recommendations for you."
        )

    except json.JSONDecodeError:
        return "Could not parse preference data. Please provide valid JSON."
    except Exception as e:
        logger.error(f"[Preference] Error saving: {e}")
        return "I noted your preference but couldn't save it right now."


def get_profile_context(user_id: str) -> str:
    """
    Load a user's profile and format it for system prompt injection.

    Args:
        user_id: The session/user ID to look up.

    Returns:
        Natural language description of the user's preferences,
        or a default message if no profile exists.
    """
    profile = _store.get_profile(user_id)

    if profile is None:
        return (
            "No preferences stored yet. Pay attention to any preferences "
            "the user mentions and save them using the save_user_preference tool."
        )

    return profile.to_prompt_context()
