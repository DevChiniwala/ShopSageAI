"""
Price Scraper — Async real-time price fetching from multiple Indian e-commerce stores.

Scrapes Amazon India, Flipkart, and Croma in parallel using httpx,
with TTL-based caching and graceful error handling per store.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from shopsage.config import SCRAPER_TIMEOUT, SCRAPER_CACHE_TTL, MAX_RESULTS_PER_STORE

logger = logging.getLogger("shopsage.scraper")

_ua = UserAgent(fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")


# ─── Data Model ────────────────────────────────────────────────────────


@dataclass
class StoreResult:
    """Represents a single product listing from a store."""

    store: str
    product_name: str = ""
    price: float = 0.0
    original_price: Optional[float] = None
    discount_percent: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    url: str = ""
    in_stock: bool = True
    image_url: str = ""
    error: Optional[str] = None


# ─── Cache ─────────────────────────────────────────────────────────────

_cache: dict[str, tuple[list[StoreResult], float]] = {}


def _normalize_query(query: str) -> str:
    """Normalize query for cache key."""
    return re.sub(r"\s+", " ", query.strip().lower())


def _get_cached(query: str) -> Optional[list[StoreResult]]:
    """Return cached results if fresh, else None."""
    key = _normalize_query(query)
    if key in _cache:
        results, timestamp = _cache[key]
        if time.time() - timestamp < SCRAPER_CACHE_TTL:
            logger.info(f"[Cache] HIT for '{key[:30]}'")
            return results
        del _cache[key]
    return None


def _set_cache(query: str, results: list[StoreResult]) -> None:
    """Store results in cache with current timestamp."""
    _cache[_normalize_query(query)] = (results, time.time())


# ─── HTTP Helpers ──────────────────────────────────────────────────────


def _headers() -> dict[str, str]:
    """Generate browser-like request headers."""
    return {
        "User-Agent": _ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _clean_price(text: str) -> float:
    """Extract numeric price from text like '₹1,299.00'."""
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ─── Store Scrapers ────────────────────────────────────────────────────


async def _scrape_amazon(client: httpx.AsyncClient, query: str) -> list[StoreResult]:
    """Scrape Amazon India search results."""
    url = f"https://www.amazon.in/s?k={quote_plus(query)}"
    results = []

    try:
        resp = await client.get(url, headers=_headers(), follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        items = soup.select('[data-component-type="s-search-result"]')[:MAX_RESULTS_PER_STORE]

        for item in items:
            try:
                # Product name
                title_el = item.select_one("h2 a span")
                name = title_el.get_text(strip=True) if title_el else ""
                if not name:
                    continue

                # Product URL
                link_el = item.select_one("h2 a")
                product_url = "https://www.amazon.in" + link_el["href"] if link_el else ""

                # Price
                price_el = item.select_one(".a-price .a-offscreen")
                price = _clean_price(price_el.get_text() if price_el else "")

                # Original price
                orig_el = item.select_one(".a-price.a-text-price .a-offscreen")
                original = _clean_price(orig_el.get_text() if orig_el else "")

                # Rating
                rating_el = item.select_one(".a-icon-star-small .a-icon-alt")
                rating_text = rating_el.get_text() if rating_el else ""
                rating = float(rating_text.split()[0]) if rating_text else None

                # Review count
                review_el = item.select_one('span[aria-label*="stars"] + span a span')
                review_text = review_el.get_text().replace(",", "") if review_el else ""
                reviews = int(review_text) if review_text.isdigit() else None

                # Image
                img_el = item.select_one("img.s-image")
                image = img_el["src"] if img_el else ""

                # Discount
                discount = None
                if price and original and original > price:
                    discount = round((1 - price / original) * 100, 1)

                if price > 0:
                    results.append(StoreResult(
                        store="Amazon",
                        product_name=name[:120],
                        price=price,
                        original_price=original or None,
                        discount_percent=discount,
                        rating=rating,
                        review_count=reviews,
                        url=product_url[:500],
                        image_url=image,
                    ))
            except Exception:
                continue

    except httpx.HTTPStatusError as e:
        logger.warning(f"[Amazon] HTTP {e.response.status_code}")
        results.append(StoreResult(store="Amazon", error=f"HTTP {e.response.status_code}"))
    except Exception as e:
        logger.warning(f"[Amazon] Error: {e}")
        results.append(StoreResult(store="Amazon", error="unavailable"))

    return results or [StoreResult(store="Amazon", error="no results")]


async def _scrape_flipkart(client: httpx.AsyncClient, query: str) -> list[StoreResult]:
    """Scrape Flipkart search results."""
    url = f"https://www.flipkart.com/search?q={quote_plus(query)}"
    results = []

    try:
        resp = await client.get(url, headers=_headers(), follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Flipkart uses various container classes; try common ones
        items = soup.select('[data-id]')[:MAX_RESULTS_PER_STORE * 2]

        for item in items[:MAX_RESULTS_PER_STORE]:
            try:
                # Product name — try multiple selectors
                title_el = (
                    item.select_one('a[title]') or
                    item.select_one('[class*="title"]') or
                    item.select_one('a div div')
                )
                name = ""
                if title_el:
                    name = title_el.get("title", "") or title_el.get_text(strip=True)
                if not name:
                    continue

                # URL
                link_el = item.select_one("a[href*='/p/']")
                product_url = ""
                if link_el:
                    href = link_el["href"]
                    product_url = f"https://www.flipkart.com{href}" if href.startswith("/") else href

                # Price — look for ₹ symbol
                price = 0.0
                for el in item.select("div"):
                    text = el.get_text(strip=True)
                    if text.startswith("₹") and len(text) < 15:
                        p = _clean_price(text)
                        if p > 0:
                            price = p
                            break

                # Rating
                rating_el = item.select_one('[class*="rating"] div')
                rating = None
                if rating_el:
                    try:
                        rating = float(rating_el.get_text(strip=True))
                    except ValueError:
                        pass

                # Image
                img_el = item.select_one("img[src*='rukminim']")
                image = img_el["src"] if img_el else ""

                if price > 0:
                    results.append(StoreResult(
                        store="Flipkart",
                        product_name=name[:120],
                        price=price,
                        rating=rating,
                        url=product_url[:500],
                        image_url=image,
                    ))
            except Exception:
                continue

    except httpx.HTTPStatusError as e:
        logger.warning(f"[Flipkart] HTTP {e.response.status_code}")
        results.append(StoreResult(store="Flipkart", error=f"HTTP {e.response.status_code}"))
    except Exception as e:
        logger.warning(f"[Flipkart] Error: {e}")
        results.append(StoreResult(store="Flipkart", error="unavailable"))

    return results or [StoreResult(store="Flipkart", error="no results")]


async def _scrape_croma(client: httpx.AsyncClient, query: str) -> list[StoreResult]:
    """Scrape Croma search results."""
    url = f"https://www.croma.com/searchB?q={quote_plus(query)}"
    results = []

    try:
        resp = await client.get(url, headers=_headers(), follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        items = soup.select(".product-item, [class*='product-card']")[:MAX_RESULTS_PER_STORE]

        for item in items:
            try:
                title_el = item.select_one("h3, [class*='product-title'], a[title]")
                name = ""
                if title_el:
                    name = title_el.get("title", "") or title_el.get_text(strip=True)
                if not name:
                    continue

                # Price
                price_el = item.select_one("[class*='price'], span.amount")
                price = _clean_price(price_el.get_text() if price_el else "")

                # URL
                link_el = item.select_one("a[href]")
                product_url = ""
                if link_el:
                    href = link_el["href"]
                    product_url = f"https://www.croma.com{href}" if href.startswith("/") else href

                # Image
                img_el = item.select_one("img")
                image = img_el.get("src", "") or img_el.get("data-src", "") if img_el else ""

                if price > 0:
                    results.append(StoreResult(
                        store="Croma",
                        product_name=name[:120],
                        price=price,
                        url=product_url[:500],
                        image_url=image,
                    ))
            except Exception:
                continue

    except httpx.HTTPStatusError as e:
        logger.warning(f"[Croma] HTTP {e.response.status_code}")
        results.append(StoreResult(store="Croma", error=f"HTTP {e.response.status_code}"))
    except Exception as e:
        logger.warning(f"[Croma] Error: {e}")
        results.append(StoreResult(store="Croma", error="unavailable"))

    return results or [StoreResult(store="Croma", error="no results")]


# ─── Public API ────────────────────────────────────────────────────────


async def fetch_prices(query: str) -> list[StoreResult]:
    """
    Fetch prices from all stores in parallel with caching.

    Args:
        query: Product search query string.

    Returns:
        List of StoreResult from all stores (may include error entries).
    """
    cached = _get_cached(query)
    if cached is not None:
        return cached

    logger.info(f"[Scraper] Fetching prices for: '{query[:40]}'")

    async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, verify=False) as client:
        tasks = [
            _scrape_amazon(client, query),
            _scrape_flipkart(client, query),
            _scrape_croma(client, query),
        ]
        store_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results = []
    for result in store_results:
        if isinstance(result, Exception):
            logger.error(f"[Scraper] Store exception: {result}")
            continue
        all_results.extend(result)

    _set_cache(query, all_results)
    logger.info(f"[Scraper] Found {len([r for r in all_results if not r.error])} products")
    return all_results


def format_comparison(query: str, results: list[StoreResult]) -> str:
    """
    Format scraper results into a readable comparison table for the LLM.

    Args:
        query: Original search query.
        results: List of StoreResult from fetch_prices.

    Returns:
        Formatted string with price comparison table.
    """
    valid = [r for r in results if r.error is None and r.price > 0]
    errors = [r for r in results if r.error is not None]

    if not valid:
        error_stores = ", ".join(r.store for r in errors) if errors else "all stores"
        return (
            f"I couldn't fetch live prices for '{query}' right now. "
            f"Stores unavailable: {error_stores}. Please try again in a moment."
        )

    # Sort by price
    valid.sort(key=lambda r: r.price)
    best = valid[0]

    lines = [
        f"PRICE COMPARISON: {query}",
        "━" * 40,
    ]

    # Best deal
    discount_str = f" ({best.discount_percent:.0f}% off)" if best.discount_percent else ""
    lines.append(f"🏆 BEST DEAL: {best.store} — ₹{best.price:,.0f}{discount_str}")
    lines.append("")

    # Table header
    lines.append(f"{'Store':<12} | {'Price':<10} | {'MRP':<10} | {'Discount':<10} | {'Rating'}")
    lines.append("-" * 65)

    for r in valid:
        mrp = f"₹{r.original_price:,.0f}" if r.original_price else "N/A"
        disc = f"{r.discount_percent:.0f}%" if r.discount_percent else "N/A"
        rating_str = f"{r.rating}★" if r.rating else "N/A"
        if r.review_count:
            rating_str += f" ({r.review_count:,})"
        lines.append(f"{r.store:<12} | ₹{r.price:<9,.0f} | {mrp:<10} | {disc:<10} | {rating_str}")

    # Savings
    if len(valid) >= 2:
        savings = valid[-1].price - valid[0].price
        if savings > 0:
            lines.append(f"\n💡 You save ₹{savings:,.0f} by buying on {valid[0].store} vs {valid[-1].store}.")

    # Links
    link_parts = []
    for r in valid:
        if r.url:
            link_parts.append(f"{r.store}: {r.url}")
    if link_parts:
        lines.append(f"\n🔗 Links:\n" + "\n".join(link_parts))

    # Error notes
    if errors:
        error_notes = ", ".join(f"{r.store} ({r.error})" for r in errors)
        lines.append(f"\n⚠️ Some stores unavailable: {error_notes}")

    return "\n".join(lines)


def results_to_dict(query: str, results: list[StoreResult]) -> dict:
    """
    Convert results to JSON-serializable dict for the REST API.

    Args:
        query: Original search query.
        results: List of StoreResult from fetch_prices.

    Returns:
        Dict with query, best_deal, results array, and metadata.
    """
    valid = [r for r in results if r.error is None and r.price > 0]
    valid.sort(key=lambda r: r.price)

    best = asdict(valid[0]) if valid else None

    return {
        "query": query,
        "best_deal": best,
        "results": [asdict(r) for r in results],
        "result_count": len(valid),
        "stores_checked": 3,
    }
