"""ProductDataLoader - handles SQLite queries for product search."""
import sqlite3
from typing import Optional
from shopsage.config import DB_PATH


class ProductDataLoader:
    """Loads and queries product data from the SQLite database."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def search_products(self, query: str) -> str:
        """
        Search products using case-insensitive partial matching across
        product_name, color, brand, material, and gender fields.

        Args:
            query: Natural language search query.

        Returns:
            Formatted string of matching products, or a 'no results' message.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        search_term = f"%{query}%"
        sql = """
            SELECT * FROM products
            WHERE product_name LIKE ? COLLATE NOCASE
               OR color LIKE ? COLLATE NOCASE
               OR brand LIKE ? COLLATE NOCASE
               OR material LIKE ? COLLATE NOCASE
               OR gender LIKE ? COLLATE NOCASE
            ORDER BY price ASC
            LIMIT 10
        """
        cursor.execute(sql, (search_term,) * 5)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "No products found matching your search criteria."

        return self._format_results(rows)

    def search_by_field(self, field: str, value: str) -> str:
        """
        Search products by a specific field with case-insensitive matching.

        Args:
            field: Column name to search (e.g., 'color', 'brand').
            value: Value to search for.

        Returns:
            Formatted string of matching products.
        """
        allowed_fields = [
            "product_name", "color", "brand", "material",
            "gender", "size", "product_code"
        ]
        if field not in allowed_fields:
            return f"Invalid search field: {field}"

        conn = self._get_connection()
        cursor = conn.cursor()

        sql = f"""
            SELECT * FROM products
            WHERE {field} LIKE ? COLLATE NOCASE
            ORDER BY price ASC
            LIMIT 10
        """
        cursor.execute(sql, (f"%{value}%",))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return f"No products found with {field} matching '{value}'."

        return self._format_results(rows)

    def search_by_price_range(
        self, min_price: float = 0, max_price: float = 999999
    ) -> str:
        """Search products within a price range."""
        conn = self._get_connection()
        cursor = conn.cursor()

        sql = """
            SELECT * FROM products
            WHERE price BETWEEN ? AND ?
            ORDER BY price ASC
            LIMIT 10
        """
        cursor.execute(sql, (min_price, max_price))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return f"No products found between ₹{min_price} and ₹{max_price}."

        return self._format_results(rows)

    def get_all_products(self) -> str:
        """Retrieve all products from the database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products ORDER BY brand, price ASC")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "The product database is empty."

        return self._format_results(rows)

    def _format_results(self, rows: list) -> str:
        """Format database rows into a readable string for the LLM."""
        results = []
        for row in rows:
            product = (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  Product: {row['product_name']}\n"
                f"  Code: {row['product_code']}\n"
                f"  Brand: {row['brand']}\n"
                f"  Price: ₹{row['price']:,.2f}\n"
                f"  Color: {row['color']}\n"
                f"  Size: {row['size']}\n"
                f"  Material: {row['material']}\n"
                f"  Gender: {row['gender']}\n"
                f"  In Stock: {row['stock_quantity']} units"
            )
            results.append(product)

        header = f"Found {len(rows)} product(s):\n"
        return header + "\n".join(results)
