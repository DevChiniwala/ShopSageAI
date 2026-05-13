"""
Test script for User Memory system.

Verifies ProfileStore CRUD operations and preference merging.

Usage:
    python scripts/test_memory.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shopsage.memory.user_profile import UserProfile, ProfileStore
from shopsage.config import DB_PATH


def test_memory():
    """Run basic memory system tests."""
    print("=" * 50)
    print("  ShopSage AI — User Memory Test Suite")
    print("=" * 50)
    print()

    store = ProfileStore(db_path=DB_PATH)

    # Test 1: Create a new profile
    print("[Test 1] Creating new profile...")
    profile = UserProfile(
        user_id="test-user-001",
        name="Rahul",
        budget_min=2000,
        budget_max=8000,
        preferred_brands=["Nike", "Adidas"],
        preferred_colors=["Black", "Navy"],
        style_tags=["minimal", "streetwear"],
        gender="Men",
        sizes={"shirt": "L", "shoe": "42"},
    )
    store.upsert_profile(profile)
    print("   ✅ Profile created")

    # Test 2: Retrieve the profile
    print("[Test 2] Retrieving profile...")
    loaded = store.get_profile("test-user-001")
    assert loaded is not None, "Profile not found!"
    assert loaded.name == "Rahul"
    assert loaded.budget_max == 8000
    assert "Nike" in loaded.preferred_brands
    print(f"   ✅ Retrieved: {loaded.name}, Budget: ₹{loaded.budget_min}-{loaded.budget_max}")

    # Test 3: Merge new preferences
    print("[Test 3] Merging new preferences...")
    updated = store.merge_preferences("test-user-001", {
        "preferred_brands": ["Puma"],
        "budget_max": 10000,
        "preferred_colors": ["Red"],
        "sizes": {"pants": "32"},
    })
    assert "Puma" in updated.preferred_brands
    assert "Nike" in updated.preferred_brands  # old brands kept
    assert updated.budget_max == 10000
    assert "Red" in updated.preferred_colors
    assert updated.sizes.get("pants") == "32"
    assert updated.sizes.get("shirt") == "L"  # old sizes kept
    print(f"   ✅ Merged: brands={updated.preferred_brands}, budget_max=₹{updated.budget_max}")

    # Test 4: Generate prompt context
    print("[Test 4] Generating prompt context...")
    context = updated.to_prompt_context()
    assert "Nike" in context
    assert "₹10,000" in context
    print(f"   ✅ Prompt context:\n{context}")

    # Test 5: Delete profile
    print("[Test 5] Deleting profile...")
    deleted = store.delete_profile("test-user-001")
    assert deleted is True
    assert store.get_profile("test-user-001") is None
    print("   ✅ Profile deleted")

    print()
    print("🎉 All 5 tests passed! User memory system is working.")


if __name__ == "__main__":
    test_memory()
