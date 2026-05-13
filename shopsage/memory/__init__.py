"""ShopSage AI — User Memory Module.

Provides persistent user profile storage and preference tracking.
The agent uses this to personalize recommendations across sessions.
"""

from shopsage.memory.user_profile import UserProfile, ProfileStore

__all__ = ["UserProfile", "ProfileStore"]
