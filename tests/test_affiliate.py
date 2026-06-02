"""Tests for affiliate link injection."""

from urllib.parse import parse_qs, urlparse

from shopsage.monetise.affiliate import inject_affiliate_link, inject_all_links


def test_inject_amazon_in_tag():
    url = "https://www.amazon.in/dp/B01234567"
    result = inject_affiliate_link(url)
    parsed = urlparse(result)
    params = parse_qs(parsed.query)
    assert params["tag"] == ["shopsageai-21"]


def test_inject_amazon_com_tag():
    url = "https://www.amazon.com/dp/B01234567"
    result = inject_affiliate_link(url)
    params = parse_qs(urlparse(result).query)
    assert params["tag"] == ["shopsageai-20"]


def test_inject_all_links_strips_trailing_period():
    text = "Buy here: https://www.amazon.in/dp/123."
    result = inject_all_links(text)
    assert "https://www.amazon.in/dp/123." in result or "https://www.amazon.in/dp/123?tag=" in result
    assert "tag=shopsageai-21" in result
    assert result.endswith(".")


def test_non_store_url_unchanged():
    url = "https://example.com/product"
    assert inject_affiliate_link(url) == url
