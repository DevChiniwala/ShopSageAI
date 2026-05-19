/**
 * ShopSage AI — Price Comparison Card Renderer
 * Renders glassmorphism price cards in the chat from compare_prices results.
 */
'use strict';

/**
 * Parse a price comparison text block and render rich cards.
 * Called from addBotMsg when route includes price data.
 *
 * @param {string} text - The formatted comparison text from the scraper.
 * @returns {string} HTML string with price cards grid.
 */
function renderPriceCards(text) {
    // Try to extract structured data from the comparison text
    const lines = text.split('\n');
    const entries = [];
    let bestStore = '';

    for (const line of lines) {
        // Detect best deal line
        const bestMatch = line.match(/BEST DEAL:\s*(\w+)/);
        if (bestMatch) bestStore = bestMatch[1];

        // Parse table rows: "Store     | ₹price | ₹MRP | 30% | 4.2★ (123)"
        const rowMatch = line.match(
            /^(\w[\w\s]*?)\s*\|\s*₹([\d,]+)\s*\|\s*(₹?[\d,]+|N\/A)\s*\|\s*([\d.]+%|N\/A)\s*\|\s*(.+)$/
        );
        if (rowMatch) {
            const [, store, price, mrp, discount, rating] = rowMatch;
            entries.push({
                store: store.trim(),
                price: price.trim(),
                mrp: mrp.trim(),
                discount: discount.trim(),
                rating: rating.trim(),
                isBest: store.trim() === bestStore,
            });
        }
    }

    // If we couldn't parse cards, return plain formatted text
    if (entries.length === 0) return null;

    // Extract savings line
    const savingsMatch = text.match(/💡 (.+)/);
    const savingsText = savingsMatch ? savingsMatch[1] : '';

    // Extract links
    const links = [];
    const linkRegex = /(\w+):\s*(https?:\/\/\S+)/g;
    let lm;
    while ((lm = linkRegex.exec(text)) !== null) {
        links.push({ store: lm[1], url: lm[2] });
    }

    // Build cards HTML
    let html = '<div class="price-cards-grid">';

    entries.forEach((entry, i) => {
        const bestBadge = entry.isBest
            ? '<div class="price-best-badge">🏆 Best Deal</div>'
            : '';
        const discountBadge = entry.discount !== 'N/A'
            ? `<span class="price-discount-badge">${entry.discount} off</span>`
            : '';
        const mrpHtml = entry.mrp !== 'N/A'
            ? `<span class="price-mrp">${entry.mrp}</span>`
            : '';
        const ratingHtml = entry.rating !== 'N/A'
            ? `<div class="price-rating">${entry.rating}</div>`
            : '';

        // Find matching link
        const link = links.find(l => l.store === entry.store);
        const buyBtn = link
            ? `<a href="${link.url}" target="_blank" rel="noopener" class="price-buy-btn">Buy Now →</a>`
            : '';

        html += `
            <div class="price-card${entry.isBest ? ' best' : ''}" style="animation-delay: ${i * 150}ms">
                ${bestBadge}
                <div class="price-store-name">${entry.store}</div>
                <div class="price-amount">₹${entry.price} ${discountBadge}</div>
                <div class="price-mrp-row">${mrpHtml}</div>
                ${ratingHtml}
                ${buyBtn}
            </div>`;
    });

    html += '</div>';

    // Savings note
    if (savingsText) {
        html += `<div class="price-savings">💡 ${savingsText}</div>`;
    }

    return html;
}

// Export for use in chat.js
window.renderPriceCards = renderPriceCards;
