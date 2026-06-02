"""
Affiliate Link Engine — Automatic commission injection for ShopSage AI.

Injects affiliate tracking tags into product URLs so every recommendation
generates commission revenue. Supports Amazon Associates, Flipkart Affiliate,
and Croma partner programs.
"""

import logging
import re
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

logger = logging.getLogger("shopsage.monetise")


# ─── Affiliate Configuration ──────────────────────────────────────────
# Replace these with your actual affiliate IDs after registration

AFFILIATE_TAGS = {
    "amazon.in": {
        "param": "tag",
        "value": "shopsageai-21",
        "program": "Amazon Associates India",
    },
    "amazon.com": {
        "param": "tag",
        "value": "shopsageai-20",
        "program": "Amazon Associates",
    },
    "flipkart.com": {
        "param": "affid",
        "value": "shopsageai",
        "program": "Flipkart Affiliate",
    },
    "croma.com": {
        "param": "ref",
        "value": "shopsageai",
        "program": "Croma Partner",
    },
}

# Revenue tracking (in-memory for now, move to DB for production)
_click_log: list[dict] = []

# Trailing punctuation often captured by \S+ URL matchers in prose
_TRAILING_URL_PUNCT = re.compile(r'[.,;:!?)>\]]+$')


def _normalize_matched_url(url: str) -> str:
    """Strip trailing punctuation accidentally included in URL matches."""
    return _TRAILING_URL_PUNCT.sub("", url)


# ─── Core Functions ────────────────────────────────────────────────────


def inject_affiliate_link(url: str) -> str:
    """
    Inject affiliate tracking parameters into a product URL.

    Preserves existing query parameters and adds the affiliate tag.
    If the URL already has an affiliate tag, it is replaced.

    Args:
        url: The original product URL.

    Returns:
        URL with affiliate tracking parameter appended.
    """
    if not url or not url.startswith("http"):
        return url

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Find matching affiliate config
        affiliate = None
        for store_domain, config in AFFILIATE_TAGS.items():
            if store_domain in domain:
                affiliate = config
                break

        if affiliate is None:
            return url

        # Parse existing query params
        params = parse_qs(parsed.query, keep_blank_values=True)

        # Inject or replace affiliate param
        params[affiliate["param"]] = [affiliate["value"]]

        # Rebuild URL with affiliate tag
        new_query = urlencode(params, doseq=True)
        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))

        logger.debug(f"[Affiliate] Injected {affiliate['program']} tag into {domain}")
        return new_url

    except Exception as e:
        logger.warning(f"[Affiliate] Failed to inject into {url}: {e}")
        return url


def inject_all_links(text: str) -> str:
    """
    Find all URLs in a text block and inject affiliate tags.

    Useful for processing agent responses that contain product links.

    Args:
        text: Text potentially containing product URLs.

    Returns:
        Text with all recognized store URLs tagged with affiliate params.
    """
    url_pattern = re.compile(r'(https?://\S+)')

    def _replace(match):
        raw = match.group(1)
        cleaned = _normalize_matched_url(raw)
        suffix = raw[len(cleaned):]
        return inject_affiliate_link(cleaned) + suffix

    return url_pattern.sub(_replace, text)


def log_click(store: str, product_url: str, session_id: str = "") -> None:
    """
    Log an affiliate click for analytics tracking.

    Args:
        store: Store name (Amazon, Flipkart, Croma).
        product_url: The affiliate-tagged URL clicked.
        session_id: User session ID for attribution.
    """
    from datetime import datetime, timezone

    _click_log.append({
        "store": store,
        "url": product_url[:200],
        "session_id": session_id[:16] if session_id else "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"[Affiliate] Click logged: {store} ({len(_click_log)} total)")


def get_click_stats() -> dict:
    """
    Get aggregate affiliate click statistics.

    Returns:
        Dict with total clicks and per-store breakdown.
    """
    by_store: dict[str, int] = {}
    for entry in _click_log:
        store = entry["store"]
        by_store[store] = by_store.get(store, 0) + 1
    return {"total": len(_click_log), "by_store": by_store}
