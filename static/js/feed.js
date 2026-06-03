/**
 * ShopSage AI — For You Discovery Feed
 * TikTok-style infinite scroll product discovery
 */

const FeedApp = (() => {
    // ─── State ──────────────────────────────────────────────────
    let products = [];
    let page = 0;
    let loading = false;
    let savedItems = new Set(JSON.parse(localStorage.getItem('shopsage_saved') || '[]'));

    // ─── DOM References ─────────────────────────────────────────
    const feedContainer = document.getElementById('feed-container');
    const feedTabs = document.querySelectorAll('.feed-tab');

    // ─── Sample Product Data (used when API unavailable) ────────
    const sampleProducts = [
        {
            id: 'fp1', title: 'Oversized Linen Blazer', description: 'Relaxed fit, breathable linen blend — perfect for summer layering',
            price: '₹3,499', originalPrice: '₹5,999', discount: '42% OFF', store: 'Myntra',
            image: 'https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=800&h=1200&fit=crop', affiliate: '#'
        },
        {
            id: 'fp2', title: 'Vintage Washed Denim Jacket', description: 'Stone-washed finish with authentic distressed detailing',
            price: '₹2,799', originalPrice: '₹4,499', discount: '38% OFF', store: 'Amazon',
            image: 'https://images.unsplash.com/photo-1576995853123-5a10305d93c0?w=800&h=1200&fit=crop', affiliate: '#'
        },
        {
            id: 'fp3', title: 'Minimalist Leather Crossbody', description: 'Genuine leather, adjustable strap, magnetic closure',
            price: '₹1,899', originalPrice: '₹3,299', discount: '42% OFF', store: 'Flipkart',
            image: 'https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=800&h=1200&fit=crop', affiliate: '#'
        },
        {
            id: 'fp4', title: 'Cotton Crew Neck Tee', description: 'Premium 180GSM cotton, pre-shrunk, relaxed fit',
            price: '₹899', originalPrice: '₹1,499', discount: '40% OFF', store: 'Myntra',
            image: 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&h=1200&fit=crop', affiliate: '#'
        },
        {
            id: 'fp5', title: 'Retro Running Sneakers', description: 'Suede and mesh upper, EVA cushioned sole, vintage colorway',
            price: '₹4,299', originalPrice: '₹6,999', discount: '39% OFF', store: 'Amazon',
            image: 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&h=1200&fit=crop', affiliate: '#'
        },
        {
            id: 'fp6', title: 'Tailored Chino Pants', description: 'Stretch twill, slim taper fit, ankle length',
            price: '₹1,699', originalPrice: '₹2,999', discount: '43% OFF', store: 'Flipkart',
            image: 'https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=800&h=1200&fit=crop', affiliate: '#'
        },
        {
            id: 'fp7', title: 'Polarized Aviator Sunglasses', description: 'UV400 protection, metal frame, gradient lenses',
            price: '₹1,299', originalPrice: '₹2,499', discount: '48% OFF', store: 'Amazon',
            image: 'https://images.unsplash.com/photo-1572635196237-14b3f281503f?w=800&h=1200&fit=crop', affiliate: '#'
        },
        {
            id: 'fp8', title: 'Silk Blend Wrap Dress', description: 'Flowing silhouette, adjustable waist tie, midi length',
            price: '₹3,999', originalPrice: '₹6,499', discount: '38% OFF', store: 'Myntra',
            image: 'https://images.unsplash.com/photo-1595777457583-95e059d581b8?w=800&h=1200&fit=crop', affiliate: '#'
        },
    ];

    // ─── Initialize ─────────────────────────────────────────────
    function init() {
        loadFeed();
        setupInfiniteScroll();
        setupTabs();
        setupNavigation();
    }

    // ─── Load Feed ──────────────────────────────────────────────
    async function loadFeed() {
        if (loading) return;
        loading = true;
        showSkeletons();

        try {
            const res = await fetch(`/api/feed?page=${page}`);
            if (res.ok) {
                const data = await res.json();
                if (data.products && data.products.length > 0) {
                    products = [...products, ...data.products];
                    renderProducts(data.products);
                    page++;
                }
            } else {
                throw new Error('API unavailable');
            }
        } catch {
            // Fallback to sample data
            const start = page * 3;
            const batch = sampleProducts.slice(start, start + 3);
            if (batch.length > 0) {
                products = [...products, ...batch];
                renderProducts(batch);
                page++;
            }
        }

        removeSkeletons();
        loading = false;
    }

    // ─── Render Products ────────────────────────────────────────
    function renderProducts(items) {
        items.forEach((product, i) => {
            const card = document.createElement('div');
            card.className = 'feed-card';
            card.style.animationDelay = `${i * 0.1}s`;
            const isSaved = savedItems.has(product.id);

            card.innerHTML = `
                <img class="feed-card-image" src="${product.image}" alt="${product.title}" loading="lazy" />
                <div class="feed-card-content">
                    <div class="feed-card-info">
                        <div class="feed-store-badge">
                            <span class="store-dot"></span>
                            ${product.store}
                        </div>
                        <h3 class="feed-product-title">${product.title}</h3>
                        <p class="feed-product-desc">${product.description}</p>
                        <div class="feed-price-row">
                            <span class="feed-price">${product.price}</span>
                            ${product.originalPrice ? `<span class="feed-price-original">${product.originalPrice}</span>` : ''}
                            ${product.discount ? `<span class="feed-discount-badge">${product.discount}</span>` : ''}
                        </div>
                        <a href="${product.affiliate || '#'}" target="_blank" rel="noopener" class="feed-shop-btn">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4zM3 6h18M16 10a4 4 0 01-8 0" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            Shop Now
                        </a>
                    </div>
                    <div class="feed-actions">
                        <button class="feed-action-btn ${isSaved ? 'saved' : ''}" data-action="save" data-id="${product.id}" aria-label="Save product">
                            <div class="action-icon">
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="${isSaved ? 'currentColor' : 'none'}"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            </div>
                            <span class="action-label">${isSaved ? 'Saved' : 'Save'}</span>
                        </button>
                        <button class="feed-action-btn" data-action="compare" data-id="${product.id}" aria-label="Compare product">
                            <div class="action-icon">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            </div>
                            <span class="action-label">Compare</span>
                        </button>
                        <button class="feed-action-btn" data-action="share" data-id="${product.id}" aria-label="Share product">
                            <div class="action-icon">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none"><circle cx="18" cy="5" r="3" stroke="currentColor" stroke-width="2"/><circle cx="6" cy="12" r="3" stroke="currentColor" stroke-width="2"/><circle cx="18" cy="19" r="3" stroke="currentColor" stroke-width="2"/><path d="M8.59 13.51l6.83 3.98M15.41 6.51l-6.82 3.98" stroke="currentColor" stroke-width="2"/></svg>
                            </div>
                            <span class="action-label">Share</span>
                        </button>
                    </div>
                </div>
            `;

            // Attach event listeners
            card.querySelectorAll('.feed-action-btn').forEach(btn => {
                btn.addEventListener('click', handleAction);
            });

            feedContainer.appendChild(card);
            
            // Add GSAP and VanillaTilt
            if (typeof gsap !== 'undefined') {
                gsap.fromTo(card, 
                    { opacity: 0, y: 50, scale: 0.95 }, 
                    { opacity: 1, y: 0, scale: 1, duration: 0.6, ease: "power3.out", delay: i * 0.1 }
                );
            }
            if (typeof VanillaTilt !== 'undefined') {
                VanillaTilt.init(card, {
                    max: 8,
                    speed: 400,
                    glare: true,
                    "max-glare": 0.1,
                    scale: 1.02
                });
            }
        });
    }

    // ─── Action Handlers ────────────────────────────────────────
    function handleAction(e) {
        const btn = e.currentTarget;
        const action = btn.dataset.action;
        const id = btn.dataset.id;

        switch(action) {
            case 'save':
                toggleSave(btn, id);
                break;
            case 'compare':
                navigateToChat(`Compare this product: ${findProduct(id)?.title}`);
                break;
            case 'share':
                shareProduct(id);
                break;
        }
    }

    function toggleSave(btn, id) {
        if (savedItems.has(id)) {
            savedItems.delete(id);
            btn.classList.remove('saved');
            btn.querySelector('.action-label').textContent = 'Save';
            btn.querySelector('svg').setAttribute('fill', 'none');
        } else {
            savedItems.add(id);
            btn.classList.add('saved');
            btn.querySelector('.action-label').textContent = 'Saved';
            btn.querySelector('svg').setAttribute('fill', 'currentColor');
            // Heart pop animation
            btn.querySelector('.action-icon').animate([
                { transform: 'scale(1)' },
                { transform: 'scale(1.3)' },
                { transform: 'scale(1)' }
            ], { duration: 300, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' });
        }
        localStorage.setItem('shopsage_saved', JSON.stringify([...savedItems]));
    }

    function shareProduct(id) {
        const product = findProduct(id);
        if (!product) return;
        if (navigator.share) {
            navigator.share({ title: product.title, text: `Check out ${product.title} for ${product.price}!`, url: window.location.href });
        } else {
            navigator.clipboard.writeText(`${product.title} — ${product.price}`);
            showToast('Link copied!');
        }
    }

    function findProduct(id) {
        return products.find(p => p.id === id);
    }

    function navigateToChat(query) {
        window.location.href = `/?q=${encodeURIComponent(query)}`;
    }

    // ─── Infinite Scroll ────────────────────────────────────────
    function setupInfiniteScroll() {
        const observer = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting && !loading) {
                loadFeed();
            }
        }, { threshold: 0.5 });

        // Create sentinel element
        const sentinel = document.createElement('div');
        sentinel.id = 'feed-sentinel';
        sentinel.style.height = '1px';
        feedContainer.appendChild(sentinel);
        observer.observe(sentinel);
    }

    // ─── Feed Tabs ──────────────────────────────────────────────
    function setupTabs() {
        feedTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                feedTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                // Reset and reload feed with new filter
                products = [];
                page = 0;
                feedContainer.innerHTML = '';
                loadFeed();
            });
        });
    }

    // ─── Bottom Navigation ──────────────────────────────────────
    function setupNavigation() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                const target = item.dataset.nav;
                if (target === 'search') {
                    window.location.href = '/';
                } else if (target === 'feed') {
                    window.location.href = '/feed';
                } else if (target === 'style') {
                    window.location.href = '/?q=Give me style advice';
                } else if (target === 'collections') {
                    showToast('Collections coming soon!');
                } else if (target === 'profile') {
                    showToast('Profile coming soon!');
                }
            });
        });
    }

    // ─── Skeleton Loading ───────────────────────────────────────
    function showSkeletons() {
        for (let i = 0; i < 2; i++) {
            const skel = document.createElement('div');
            skel.className = 'feed-skeleton skeleton-loading';
            skel.innerHTML = `
                <div style="width:100%;padding:24px 20px">
                    <div class="skeleton-pulse" style="width:80px;height:24px;margin-bottom:12px"></div>
                    <div class="skeleton-pulse" style="width:70%;height:28px;margin-bottom:8px"></div>
                    <div class="skeleton-pulse" style="width:50%;height:18px;margin-bottom:16px"></div>
                    <div class="skeleton-pulse" style="width:120px;height:36px"></div>
                </div>
            `;
            feedContainer.appendChild(skel);
        }
    }

    function removeSkeletons() {
        feedContainer.querySelectorAll('.skeleton-loading').forEach(s => s.remove());
    }

    // ─── Toast ──────────────────────────────────────────────────
    function showToast(message) {
        const toast = document.createElement('div');
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed; bottom: 90px; left: 50%; transform: translateX(-50%);
            padding: 10px 24px; border-radius: 999px; background: rgba(139,92,246,0.9);
            color: white; font-size: 13px; font-weight: 600; z-index: 999;
            backdrop-filter: blur(12px); animation: toastIn 0.3s ease-out;
        `;
        document.body.appendChild(toast);
        setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s'; setTimeout(() => toast.remove(), 300); }, 2000);
    }

    // ─── Init on DOM Ready ──────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { loadFeed, products };
})();
