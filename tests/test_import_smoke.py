"""Smoke tests that critical application modules import successfully."""


def test_app_imports():
    from app import app

    assert app.title == "ShopSage AI"


def test_semantic_router_imports():
    from shopsage.router.semantic_router import classify_query

    assert callable(classify_query)
