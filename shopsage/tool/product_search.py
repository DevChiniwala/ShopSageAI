"""Product Search Tool - SQLite-based product search for the shopping agent."""
from langchain_core.tools import tool
from shopsage.utils.data_loader import ProductDataLoader


_loader = ProductDataLoader()


@tool
def product_search(query: str) -> str:
    """
    Search for products in the ShopSage inventory database.

    Use this tool when the user asks about products, availability,
    prices, colors, sizes, brands, or any product-related query.

    Examples of when to use this tool:
    - "Show me red shirts"
    - "What jackets do you have?"
    - "Nike products under 5000"
    - "Blue dresses in size M"
    - "What's in stock?"

    Args:
        query: The product search query. Can include color, brand,
               size, material, gender, or product type.

    Returns:
        Formatted list of matching products with details including
        name, price, color, size, brand, material, and stock quantity.
    """
    return _loader.search_products(query)


@tool
def product_search_by_price(min_price: float, max_price: float) -> str:
    """
    Search for products within a specific price range.

    Use this tool when the user specifies a budget or price range.

    Examples:
    - "Products under 2000"
    - "Shirts between 1000 and 3000"
    - "Cheap options under 500"

    Args:
        min_price: Minimum price in rupees (₹). Use 0 if no minimum.
        max_price: Maximum price in rupees (₹).

    Returns:
        Formatted list of products within the specified price range.
    """
    return _loader.search_by_price_range(min_price, max_price)
