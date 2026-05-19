"""
Price Comparison Tool — LangChain tool wrapper for the scraping engine.

Exposes the price scraper as a @tool so the ReAct agent can
autonomously compare prices across Amazon, Flipkart, and Croma.
"""

import asyncio
import logging
from langchain_core.tools import tool
from shopsage.tool.price_scraper import fetch_prices, format_comparison

logger = logging.getLogger("shopsage.tools")


def _run_async(coro):
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Inside an existing event loop (FastAPI/uvicorn)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


@tool
def compare_prices(product_query: str) -> str:
    """
    Compare live prices for a product across Amazon, Flipkart, and Croma.

    Call this tool when the user wants to know where to buy a product
    at the best price, or wants to compare prices across stores.

    Triggers include:
    - "Where can I get the cheapest Nike shoes?"
    - "Compare prices for wireless earbuds"
    - "Is this cheaper on Amazon or Flipkart?"
    - "Find me the best deal on iPhone 15"
    - "Price comparison for Samsung Galaxy S24"

    Args:
        product_query: The product to search for across online stores.

    Returns:
        Formatted comparison table with prices, discounts, and store links.
    """
    try:
        logger.info(f"[PriceCompare] Searching: {product_query}")
        results = _run_async(fetch_prices(product_query))
        return format_comparison(product_query, results)
    except Exception as e:
        logger.error(f"[PriceCompare] Error: {e}", exc_info=True)
        return (
            f"I couldn't fetch live prices for '{product_query}' right now. "
            "The stores might be temporarily unavailable. Please try again."
        )
