(() => {
    const THEME_KEY = 'proshop-theme';
    const WISHLIST_KEY = 'proshop-wishlist';
    const PRODUCT_THEME_DEFAULT = '37, 99, 235';
    const FALLBACK_IMAGE = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="520" height="420"%3E%3Cdefs%3E%3ClinearGradient id="g" x1="0" x2="1" y1="0" y2="1"%3E%3Cstop stop-color="%23dbeafe" /%3E%3Cstop offset="1" stop-color="%23cbd5e1" /%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width="100%25" height="100%25" fill="url(%23g)" rx="28" /%3E%3Ccircle cx="154" cy="144" r="42" fill="%2393c5fd" fill-opacity="0.85" /%3E%3Cpath d="M90 302l88-96 62 68 64-44 126 72H90z" fill="%2394a3b8" /%3E%3C/svg%3E';

    const storefrontState = {
        products: [],
        filteredProducts: [],
        selectedCategory: 'all',
        maxPrice: 50000,
        priceCap: 50000,
        wishlist: new Set(loadStoredArray(WISHLIST_KEY)),
        detailProduct: null,
        detailGalleryImages: [],
        detailGalleryIndex: 0,
        detailGalleryTimer: null,
        detailGalleryStopped: false,
        detailImageTransitionToken: 0,
        detailVariantOptions: {
            colors: [],
            sizes: [],
            requiresSize: false,
            sizeGuide: null,
        },
        detailSelections: {
            colorIndex: 0,
            size: null,
        },
    };

    const defaultEscapeHtml = (value) => {
        if (value === null || value === undefined) return '';
        const text = String(value);
        return text.replace(/[&<>"']/g, (match) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;',
        })[match]);
    };

    const safeHtml = typeof window.escapeHtml === 'function' ? window.escapeHtml : defaultEscapeHtml;

    function loadStoredArray(key) {
        try {
            const value = JSON.parse(localStorage.getItem(key) || '[]');
            return Array.isArray(value) ? value : [];
        } catch (error) {
            return [];
        }
    }

    function persistWishlist() {
        localStorage.setItem(WISHLIST_KEY, JSON.stringify(Array.from(storefrontState.wishlist)));
    }

    function formatCurrency(amount) {
        return `Rs.${Number(amount || 0).toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    function getCurrentTheme() {
        return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    }

    function setTheme(theme, persist = true) {
        const nextTheme = theme === 'dark' ? 'dark' : 'light';
        document.documentElement.dataset.theme = nextTheme;

        if (persist) {
            localStorage.setItem(THEME_KEY, nextTheme);
        }

        const label = document.getElementById('theme-toggle-label');
        const mobileButton = document.getElementById('mobile-theme-toggle');
        if (label) {
            label.textContent = nextTheme === 'dark' ? 'Light Mode' : 'Dark Mode';
        }
        if (mobileButton) {
            mobileButton.textContent = nextTheme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
        }
    }

    function syncStorefrontNav() {
        const showProducts = !AppState?.user || AppState.user.role !== 'seller';
        ['nav-products', 'mobile-nav-products'].forEach((id) => {
            const element = document.getElementById(id);
            if (element) {
                element.style.display = showProducts ? '' : 'none';
            }
        });
    }

    function loadTheme() {
        const storedTheme = localStorage.getItem(THEME_KEY) || document.documentElement.dataset.theme || 'light';
        setTheme(storedTheme, false);
    }

    function spawnRipple(event) {
        const target = event.target.closest('[data-ripple]');
        if (!target) return;

        const rect = target.getBoundingClientRect();
        const ripple = document.createElement('span');
        ripple.className = 'ripple-node';
        ripple.style.left = `${event.clientX - rect.left}px`;
        ripple.style.top = `${event.clientY - rect.top}px`;
        target.appendChild(ripple);
        ripple.addEventListener('animationend', () => ripple.remove(), { once: true });
    }

    function overrideToast() {
        window.showToast = function showToast(message, type = 'info', duration = 3200) {
            const container = document.getElementById('toast-container');
            if (!container) return;

            const icons = {
                success: 'OK',
                error: 'NO',
                warning: '!!',
                info: 'i',
            };

            const toast = document.createElement('div');
            toast.className = `toast toast-${type}`;
            toast.innerHTML = `
                <span class="toast-icon">${safeHtml(icons[type] || 'i')}</span>
                <span>${safeHtml(message)}</span>
            `;

            container.appendChild(toast);

            setTimeout(() => {
                toast.classList.add('removing');
                setTimeout(() => toast.remove(), 280);
            }, duration);
        };
    }

    function getPricing(product) {
        const price = Number(product?.price || 0);
        const explicitOriginal = Number(product?.original_price || product?.compare_at_price || product?.mrp || 0);
        const explicitDiscount = Number(product?.discount_percentage || product?.discount || 0);

        let originalPrice = explicitOriginal > price ? explicitOriginal : 0;
        let discount = 0;

        if (originalPrice > price && price > 0) {
            discount = Math.round((1 - price / originalPrice) * 100);
        } else if (explicitDiscount > 0 && explicitDiscount < 100) {
            discount = Math.round(explicitDiscount);
            originalPrice = Number((price / (1 - discount / 100)).toFixed(2));
        }

        return {
            price,
            originalPrice,
            discount,
        };
    }

    function getDisplayImage(image) {
        if (!image) return FALLBACK_IMAGE;
        try {
            return typeof buildImageUrl === 'function' ? buildImageUrl(image) : image;
        } catch (error) {
            return image;
        }
    }

    function getDerivedDescription(product) {
        if (product?.description) {
            return product.description;
        }

        const specs = Array.isArray(product?.specifications) ? product.specifications.slice(0, 2) : [];
        if (specs.length > 0) {
            return specs.map((item) => `${item.key}: ${item.value}`).join(' • ');
        }

        return `${product?.category || 'Curated'} product from ${product?.seller || 'our marketplace'}.`;
    }

    function getProductRating(product) {
        const seed = (product?.uuid || product?.name || 'product')
            .split('')
            .reduce((total, char) => total + char.charCodeAt(0), 0);
        return (4.2 + (seed % 7) * 0.1).toFixed(1);
    }

    function getProductHighlights(product) {
        const highlights = [];
        if (Number(product?.stock) > 0) highlights.push('Ready to ship');
        if (Array.isArray(product?.specifications) && product.specifications.length) highlights.push('Detailed specs');
        if (product?.category) highlights.push(`${product.category} edit`);
        highlights.push('Smooth returns');
        return highlights.slice(0, 4);
    }

    function resetProductTheme() {
        document.body.classList.remove('has-product-theme');
        document.documentElement.style.setProperty('--store-product-rgb', PRODUCT_THEME_DEFAULT);
    }

    async function extractDominantTheme(imageUrl) {
        return new Promise((resolve) => {
            const image = new Image();
            image.crossOrigin = 'anonymous';
            image.onerror = () => resolve(PRODUCT_THEME_DEFAULT);
            image.onload = () => {
                try {
                    const canvas = document.createElement('canvas');
                    const size = 40;
                    canvas.width = size;
                    canvas.height = size;
                    const context = canvas.getContext('2d', { willReadFrequently: true });
                    context.drawImage(image, 0, 0, size, size);
                    const pixels = context.getImageData(0, 0, size, size).data;
                    const buckets = new Map();

                    for (let index = 0; index < pixels.length; index += 16) {
                        const r = pixels[index];
                        const g = pixels[index + 1];
                        const b = pixels[index + 2];
                        const a = pixels[index + 3];

                        if (a < 180) continue;
                        if (r > 242 && g > 242 && b > 242) continue;

                        const key = [
                            Math.round(r / 16) * 16,
                            Math.round(g / 16) * 16,
                            Math.round(b / 16) * 16,
                        ].join(',');

                        buckets.set(key, (buckets.get(key) || 0) + 1);
                    }

                    const dominant = [...buckets.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || PRODUCT_THEME_DEFAULT;
                    resolve(dominant);
                } catch (error) {
                    resolve(PRODUCT_THEME_DEFAULT);
                }
            };

            image.src = imageUrl;
        });
    }

    async function applyStorefrontDynamicTheme(imageUrl) {
        if (!imageUrl) {
            resetProductTheme();
            return PRODUCT_THEME_DEFAULT;
        }

        const dominant = await extractDominantTheme(imageUrl);
        document.documentElement.style.setProperty('--store-product-rgb', dominant);
        document.body.classList.add('has-product-theme');
        return dominant;
    }

    window.applyDynamicTheme = applyStorefrontDynamicTheme;

    window.toggleThemeMode = function toggleThemeMode() {
        setTheme(getCurrentTheme() === 'dark' ? 'light' : 'dark');
    };

    const baseUpdateUI = window.updateUIBasedOnAuth;
    window.updateUIBasedOnAuth = function updateUIBasedOnAuthWithStorefront() {
        if (typeof baseUpdateUI === 'function') {
            baseUpdateUI();
        }
        syncStorefrontNav();
        setTheme(getCurrentTheme(), false);
    };

    const baseNavigateTo = window.navigateTo;
    window.navigateTo = function navigateToWithTransition(path) {
        const curtain = document.getElementById('page-transition-curtain');
        if (curtain) {
            curtain.classList.add('is-active');
            setTimeout(() => curtain.classList.remove('is-active'), 260);
        }

        const target = String(path || '');
        if (!target.startsWith('#product/')) {
            resetProductTheme();
            resetDetailGalleryAutoplay();
        }

        if (typeof baseNavigateTo === 'function') {
            baseNavigateTo(path);
        } else {
            window.location.hash = path;
        }
    };

    function renderProductSkeletons(count = 8) {
        const grid = document.getElementById('products-grid');
        if (!grid) return;

        grid.innerHTML = Array.from({ length: count }, () => `
            <div class="store-skeleton-card">
                <div class="skeleton-block skeleton-media"></div>
                <div class="product-card-body">
                    <div class="skeleton-block skeleton-line short"></div>
                    <div class="skeleton-block skeleton-line"></div>
                    <div class="skeleton-block skeleton-line"></div>
                    <div class="skeleton-chip-row">
                        <div class="skeleton-block skeleton-line"></div>
                        <div class="skeleton-block skeleton-line"></div>
                    </div>
                    <div class="skeleton-button-row">
                        <div class="skeleton-block skeleton-line"></div>
                        <div class="skeleton-block skeleton-line"></div>
                    </div>
                </div>
            </div>
        `).join('');
    }

    function updateResultsCount(filteredCount) {
        const counter = document.getElementById('products-results-count');
        if (!counter) return;

        if (storefrontState.products.length === 0) {
            counter.textContent = 'No products available';
            return;
        }

        counter.textContent = `${filteredCount} of ${storefrontState.products.length} products visible`;
    }

    function getCategoryIconMarkup(category) {
        const iconMap = {
            all: '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M5 7h14M5 12h14M5 17h14"></path></svg>',
            electronics: '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><rect x="7" y="3.5" width="10" height="17" rx="2.2"></rect><path stroke-linecap="round" d="M10 17.5h4"></path></svg>',
            clothing: '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M9 4l3 2 3-2 4 3-2 5h-2v8H9v-8H7L5 7l4-3z"></path></svg>',
            computers: '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><rect x="4" y="5" width="16" height="11" rx="2"></rect><path stroke-linecap="round" d="M9 19h6M12 16v3"></path></svg>',
            fashion: '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3l1.9 4.6L19 9.5l-4 3.3 1.2 5.2L12 15.2 7.8 18l1.2-5.2-4-3.3 5.1-1.9L12 3z"></path></svg>',
            gadgets: '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M7 10a5 5 0 0 1 10 0v4a5 5 0 0 1-10 0v-4z"></path><path stroke-linecap="round" d="M9 14h.01M15 14h.01"></path></svg>',
            default: '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4l1.4 3.5L17 9l-3 2.5.9 3.5-2.9-1.9-2.9 1.9.9-3.5L7 9l3.6-1.5L12 4z"></path></svg>',
        };

        return iconMap[String(category || '').toLowerCase()] || iconMap.default;
    }

    function updateCategoryIndicator() {
        const container = document.getElementById('category-filter-list');
        const indicator = container?.querySelector('.storefront-category-indicator');
        const activeChip = container?.querySelector('.storefront-category-chip.active');

        if (!container || !indicator || !activeChip) {
            container?.style.setProperty('--category-indicator-opacity', '0');
            return;
        }

        const containerRect = container.getBoundingClientRect();
        const activeRect = activeChip.getBoundingClientRect();

        container.style.setProperty('--category-indicator-left', `${activeRect.left - containerRect.left}px`);
        container.style.setProperty('--category-indicator-top', `${activeRect.top - containerRect.top}px`);
        container.style.setProperty('--category-indicator-width', `${activeRect.width}px`);
        container.style.setProperty('--category-indicator-height', `${activeRect.height}px`);
        container.style.setProperty('--category-indicator-opacity', '1');
    }

    function updateFilterUI() {
        document.querySelectorAll('.storefront-category-chip').forEach((chip) => {
            const isActive = chip.dataset.category === storefrontState.selectedCategory;
            chip.classList.toggle('active', isActive);
            chip.setAttribute('aria-pressed', String(isActive));
        });

        const favoritesOnly = document.getElementById('filter-favorites')?.checked;
        const wishlistToggle = document.getElementById('wishlist-filter-toggle');
        if (wishlistToggle) {
            wishlistToggle.classList.toggle('storefront-toolbar-button-primary', Boolean(favoritesOnly));
        }

        window.requestAnimationFrame(updateCategoryIndicator);
    }

    function renderCategoryFilters() {
        const container = document.getElementById('category-filter-list');
        if (!container) return;

        const categories = Array.from(new Set(
            storefrontState.products
                .map((product) => product.category)
                .filter(Boolean)
        )).sort((left, right) => left.localeCompare(right));

        const items = ['all', ...categories];
        container.innerHTML = `
            <span class="storefront-category-indicator" aria-hidden="true"></span>
            ${items.map((category) => {
            const label = category === 'all' ? 'All Products' : category;
            return `
                <button
                    type="button"
                    class="storefront-category-chip ${storefrontState.selectedCategory === category ? 'active' : ''}"
                    data-category="${safeHtml(category)}"
                    aria-pressed="${storefrontState.selectedCategory === category ? 'true' : 'false'}"
                    onclick='filterByCategory(${JSON.stringify(category)})'
                    data-ripple
                >
                    <span class="storefront-category-chip-icon" aria-hidden="true">${getCategoryIconMarkup(category)}</span>
                    <span class="storefront-category-chip-label">${safeHtml(label)}</span>
                </button>
            `;
        }).join('')}
        `;

        window.requestAnimationFrame(updateCategoryIndicator);
    }

    function updatePriceControls() {
        const prices = storefrontState.products.map((product) => Number(product.price || 0));
        const maxProductPrice = Math.max(0, ...prices);
        storefrontState.maxPrice = Math.max(5000, Math.ceil(maxProductPrice / 500) * 500 || 5000);
        storefrontState.priceCap = Math.min(storefrontState.priceCap, storefrontState.maxPrice);

        const range = document.getElementById('price-range');
        const label = document.getElementById('price-range-label');
        const maxLabel = document.getElementById('price-range-max');

        if (range) {
            range.max = String(storefrontState.maxPrice);
            range.value = String(storefrontState.priceCap || storefrontState.maxPrice);
        }

        if (label) {
            label.textContent = storefrontState.priceCap >= storefrontState.maxPrice
                ? 'Any price'
                : `Up to ${formatCurrency(storefrontState.priceCap)}`;
        }

        if (maxLabel) {
            maxLabel.textContent = formatCurrency(storefrontState.maxPrice);
        }
    }

    function getFilteredProducts() {
        const search = (document.getElementById('search-products')?.value || '').trim().toLowerCase();
        const stockOnly = Boolean(document.getElementById('filter-in-stock')?.checked);
        const favoritesOnly = Boolean(document.getElementById('filter-favorites')?.checked);

        storefrontState.filteredProducts = storefrontState.products.filter((product) => {
            const searchHaystack = [
                product.name,
                product.category,
                product.seller,
                getDerivedDescription(product),
            ].join(' ').toLowerCase();

            const matchesSearch = !search || searchHaystack.includes(search);
            const matchesCategory = storefrontState.selectedCategory === 'all' || product.category === storefrontState.selectedCategory;
            const matchesPrice = Number(product.price || 0) <= storefrontState.priceCap;
            const matchesStock = !stockOnly || Number(product.stock || 0) > 0;
            const matchesWishlist = !favoritesOnly || storefrontState.wishlist.has(product.uuid);

            return matchesSearch && matchesCategory && matchesPrice && matchesStock && matchesWishlist;
        });

        return storefrontState.filteredProducts;
    }

    function renderEmptyProducts() {
        const grid = document.getElementById('products-grid');
        if (!grid) return;

        grid.innerHTML = `
            <div class="storefront-empty-shell">
                <h3 class="storefront-toolbar-title">No products match these filters</h3>
                <p>Try widening the price range, switching categories, or clearing wishlist-only mode.</p>
                <button type="button" class="storefront-refresh-btn mt-4" onclick="resetStorefrontFilters()" data-ripple>Reset Filters</button>
            </div>
        `;
    }

    function renderProductCard(product) {
        const { price, originalPrice, discount } = getPricing(product);
        const isFavorited = storefrontState.wishlist.has(product.uuid);
        const rating = getProductRating(product);
        const image = getDisplayImage(product.primary_image);
        const stockCount = Number(product.stock || 0);
        const ctaLabel = AppState?.user?.role === 'admin' ? 'Preview Only' : 'Add to Cart';

        return `
            <article class="store-product-card" onclick="openProductDetail('${safeHtml(product.uuid)}')">
                <div class="store-product-media">
                    <img src="${image}" alt="${safeHtml(product.name)}" onerror="this.src='${FALLBACK_IMAGE}'">
                    <div class="store-product-overlay"></div>
                    <div class="product-card-topline">
                        <div class="flex items-center gap-2">
                            ${discount > 0 ? `<span class="product-card-badge">${safeHtml(`${discount}% OFF`)}</span>` : ''}
                            <span class="product-card-stock ${stockCount > 0 ? '' : 'out'}">${stockCount > 0 ? safeHtml(`${stockCount} in stock`) : 'Out of stock'}</span>
                        </div>
                        <button type="button" class="product-card-favorite ${isFavorited ? 'is-active' : ''}" onclick="toggleProductWishlist('${safeHtml(product.uuid)}', event)" data-ripple aria-label="Toggle wishlist">
                            ${isFavorited ? '&#9829;' : '&#9825;'}
                        </button>
                    </div>
                </div>
                <div class="product-card-body">
                    <div>
                        <p class="product-card-kicker">${safeHtml(product.category || 'Featured')}</p>
                        <h3 class="product-card-name">${safeHtml(product.name)}</h3>
                        <p class="product-card-description">${safeHtml(getDerivedDescription(product))}</p>
                    </div>
                    <div class="product-card-meta">
                        <span>Seller: ${safeHtml(product.seller || 'Marketplace')}</span>
                        <span class="product-card-rating">${safeHtml(`${rating} rating`)}</span>
                    </div>
                    <div class="product-card-price-row">
                        <div class="product-card-price-stack">
                            <span class="product-card-price">${formatCurrency(price)}</span>
                            ${originalPrice > price ? `<span class="product-card-original">${formatCurrency(originalPrice)}</span>` : ''}
                        </div>
                    </div>
                    <div class="product-card-footer">
                        <button type="button" class="product-card-secondary" onclick="event.stopPropagation(); openProductDetail('${safeHtml(product.uuid)}')" data-ripple>View Details</button>
                        <button
                            type="button"
                            class="product-card-button"
                            onclick="handleCardAddToCart('${safeHtml(product.uuid)}', event)"
                            ${stockCount <= 0 || AppState?.user?.role === 'admin' ? 'disabled' : ''}
                            data-ripple
                        >
                            ${safeHtml(ctaLabel)}
                        </button>
                    </div>
                </div>
            </article>
        `;
    }

    function renderProducts(products) {
        updateResultsCount(products.length);
        updateFilterUI();

        const grid = document.getElementById('products-grid');
        if (!grid) return;

        if (products.length === 0) {
            renderEmptyProducts();
            return;
        }

        grid.innerHTML = products.map(renderProductCard).join('');
    }

    function getProductSnapshot(productUuid) {
        if (!productUuid) {
            return null;
        }

        if (storefrontState.detailProduct?.uuid === productUuid) {
            return storefrontState.detailProduct;
        }

        if (AppState?.currentProduct?.uuid === productUuid) {
            return AppState.currentProduct;
        }

        return storefrontState.products.find((product) => product.uuid === productUuid) || null;
    }

    async function addProductToCart(productUuid, quantity = 1, options = {}) {
        if (AppState?.user && AppState.user.role !== 'customer') {
            showToast('Only customer accounts can purchase products.', 'warning');
            return false;
        }

        const normalizedQuantity = Math.max(1, Number(quantity) || 1);
        const product = getProductSnapshot(productUuid);

        if (!product) {
            showToast('Unable to add this product right now.', 'error');
            return false;
        }

        const existingQuantity = typeof getCartProductQuantity === 'function' ? getCartProductQuantity(productUuid) : 0;
        if (Number(product.stock || 0) > 0 && existingQuantity + normalizedQuantity > Number(product.stock || 0)) {
            showToast(`Only ${product.stock} item(s) available for this product.`, 'warning');
            return false;
        }

        const previousCart = typeof cloneCartItems === 'function' ? cloneCartItems() : [];
        if (typeof addProductToLocalCart === 'function') {
            addProductToLocalCart(product, normalizedQuantity);
        }

        if (typeof ui?.renderCart === 'function' && window.location.hash === '#cart') {
            ui.renderCart();
        }

        if (AppState?.user?.role === 'customer') {
            const response = await API.addToCart(productUuid, normalizedQuantity);
            if (!response) {
                if (typeof restoreCartSnapshot === 'function') {
                    restoreCartSnapshot(previousCart);
                }
                if (typeof ui?.renderCart === 'function' && window.location.hash === '#cart') {
                    ui.renderCart();
                }
                return false;
            }
        }

        showToast(options.successMessage || 'Added to cart.', 'success');

        if (typeof options.afterSuccess === 'function') {
            await options.afterSuccess();
        }

        return true;
    }

    window.loadProducts = async function loadProducts(forceReload = false) {
        if (!forceReload && storefrontState.products.length > 0) {
            renderCategoryFilters();
            updatePriceControls();
            renderProducts(getFilteredProducts());
            return;
        }

        renderProductSkeletons();

        const response = await API.fetchProducts();
        const products = Array.isArray(response?.products) ? response.products : [];

        storefrontState.products = products.map((product) => ({
            ...product,
            price: Number(product.price || 0),
            stock: Number(product.stock || 0),
        }));

        storefrontState.selectedCategory = 'all';
        renderCategoryFilters();
        updatePriceControls();
        renderProducts(getFilteredProducts());
    };

    window.filterProducts = function filterProducts() {
        renderProducts(getFilteredProducts());
    };

    window.filterByCategory = function filterByCategory(category) {
        storefrontState.selectedCategory = category;
        renderProducts(getFilteredProducts());
    };

    window.handlePriceRangeChange = function handlePriceRangeChange(event) {
        storefrontState.priceCap = Number(event?.target?.value || storefrontState.maxPrice);
        updatePriceControls();
        renderProducts(getFilteredProducts());
    };

    window.resetStorefrontFilters = function resetStorefrontFilters() {
        storefrontState.selectedCategory = 'all';
        storefrontState.priceCap = storefrontState.maxPrice;

        const search = document.getElementById('search-products');
        const range = document.getElementById('price-range');
        const stock = document.getElementById('filter-in-stock');
        const favorites = document.getElementById('filter-favorites');

        if (search) search.value = '';
        if (range) range.value = String(storefrontState.maxPrice);
        if (stock) stock.checked = false;
        if (favorites) favorites.checked = false;

        updatePriceControls();
        renderProducts(getFilteredProducts());
    };

    window.toggleWishlistView = function toggleWishlistView() {
        const checkbox = document.getElementById('filter-favorites');
        if (!checkbox) return;
        checkbox.checked = !checkbox.checked;
        renderProducts(getFilteredProducts());
    };

    window.toggleProductWishlist = function toggleProductWishlist(productUuid, event) {
        event?.stopPropagation();

        if (storefrontState.wishlist.has(productUuid)) {
            storefrontState.wishlist.delete(productUuid);
            showToast('Removed from wishlist.', 'info');
        } else {
            storefrontState.wishlist.add(productUuid);
            showToast('Saved to wishlist.', 'success');
        }

        persistWishlist();

        if (storefrontState.detailProduct?.uuid === productUuid) {
            syncDetailWishlistButton();
        }

        renderProducts(getFilteredProducts());
    };

    window.handleCardAddToCart = async function handleCardAddToCart(productUuid, event) {
        event?.stopPropagation();
        await addProductToCart(productUuid, 1);
    };

    window.openProductDetail = function openProductDetail(productUuid) {
        navigateTo(`#product/${productUuid}`);
    };

    function renderDetailSkeleton() {
        const specs = document.getElementById('detail-specs');
        const reviews = document.getElementById('detail-reviews');
        const sellerMeta = document.getElementById('detail-seller-meta');
        const highlights = document.getElementById('detail-highlights');

        const skeletonCards = Array.from({ length: 4 }, () => `
            <div class="detail-spec-item">
                <div class="skeleton-block skeleton-line short"></div>
                <div class="skeleton-block skeleton-line mt-3"></div>
            </div>
        `).join('');

        if (specs) specs.innerHTML = skeletonCards;
        if (reviews) reviews.innerHTML = Array.from({ length: 3 }, () => `
            <div class="detail-review-card">
                <div class="skeleton-block skeleton-line short"></div>
                <div class="skeleton-block skeleton-line mt-3"></div>
                <div class="skeleton-block skeleton-line mt-3"></div>
            </div>
        `).join('');
        if (sellerMeta) sellerMeta.innerHTML = Array.from({ length: 3 }, () => `
            <div class="detail-seller-item">
                <div class="skeleton-block skeleton-line short"></div>
                <div class="skeleton-block skeleton-line mt-3"></div>
            </div>
        `).join('');
        if (highlights) highlights.innerHTML = Array.from({ length: 4 }, () => '<span class="detail-highlight-chip skeleton-block" style="width: 120px;"></span>').join('');
    }

    function getReviewCards(product) {
        const rating = Number(getProductRating(product));
        return [
            {
                author: 'Aria K.',
                score: rating.toFixed(1),
                copy: 'The finish feels premium in hand and the overall presentation is much better than the usual catalog pick.',
                meta: 'Verified buyer • 2 days ago',
            },
            {
                author: 'Dev R.',
                score: Math.max(4.1, rating - 0.1).toFixed(1),
                copy: 'Loved the product detail, quick delivery expectation, and the way the specs matched the listing exactly.',
                meta: 'Repeat customer • 1 week ago',
            },
            {
                author: 'Mina S.',
                score: Math.max(4.0, rating - 0.2).toFixed(1),
                copy: 'Looks great, the value feels strong, and I would keep this on my wishlist even after purchasing.',
                meta: 'Style-focused shopper • Recently',
            },
        ];
    }

    function renderDetailReviews(product) {
        const reviews = document.getElementById('detail-reviews');
        if (!reviews) return;

        reviews.innerHTML = getReviewCards(product).map((review) => `
            <div class="detail-review-card">
                <div class="detail-seller-item">
                    <div>
                        <strong>${safeHtml(review.author)}</strong>
                        <p class="detail-review-meta">${safeHtml(review.meta)}</p>
                    </div>
                    <span class="detail-review-score">${safeHtml(review.score)}</span>
                </div>
                <p class="detail-review-copy">${safeHtml(review.copy)}</p>
            </div>
        `).join('');
    }

    function renderDetailHighlights(product) {
        const highlights = document.getElementById('detail-highlights');
        if (!highlights) return;

        highlights.innerHTML = getProductHighlights(product).map((highlight) => `
            <span class="detail-highlight-chip">${safeHtml(highlight)}</span>
        `).join('');
    }

    function findDetailSpecValue(product, matcher) {
        const specs = Array.isArray(product?.specifications) ? product.specifications : [];
        const matchedSpec = specs.find((spec) => matcher(String(spec?.key || '').toLowerCase()));
        return String(matchedSpec?.value || '').trim();
    }

    function parseDetailVariantValues(rawValue, splitPattern) {
        if (!rawValue) {
            return [];
        }

        return Array.from(new Set(
            String(rawValue)
                .split(splitPattern)
                .map((value) => value.trim())
                .filter(Boolean)
        ));
    }

    function isFashionProduct(product) {
        const haystack = [
            product?.name,
            product?.category,
            product?.description,
        ].join(' ').toLowerCase();

        return /(fashion|clothing|apparel|jacket|blazer|coat|shirt|t-?shirt|hoodie|kurta|jeans|trouser|dress|suit|shoe|sneaker|loafer|boot|wear)/.test(haystack);
    }

    function inferDetailColourOptions(product) {
        const galleryImages = storefrontState.detailGalleryImages.length
            ? storefrontState.detailGalleryImages
            : Array.from(new Set([
                getDisplayImage(product?.primary_image),
                ...(Array.isArray(product?.images) ? product.images.map(getDisplayImage) : []),
            ].filter(Boolean)));
        const colourSpec = findDetailSpecValue(product, (key) => /colou?r|shade|finish|pattern|wash/.test(key));
        const rawLabels = parseDetailVariantValues(colourSpec, /[,;|]+/);

        if (galleryImages.length < 2 && rawLabels.length === 0) {
            return [];
        }

        return galleryImages.map((imageUrl, index) => {
            let label = rawLabels[index] || '';

            if (!label && rawLabels.length === 1) {
                label = index === 0 ? rawLabels[0] : `Look ${index + 1}`;
            }

            if (!label) {
                label = galleryImages.length > 1 ? `Look ${index + 1}` : 'Signature look';
            }

            return {
                label,
                imageUrl,
                galleryIndex: Math.max(0, storefrontState.detailGalleryImages.indexOf(imageUrl)),
            };
        });
    }

    function inferDetailSizeOptions(product) {
        const sizeSpec = findDetailSpecValue(product, (key) => /(^size$|sizes|available size|fit|waist|chest|length)/.test(key));
        const parsedSizes = parseDetailVariantValues(sizeSpec, /[,/;|]+/).map((value) => value.toUpperCase());

        if (parsedSizes.length > 0) {
            return Array.from(new Set(parsedSizes));
        }

        if (!isFashionProduct(product)) {
            return [];
        }

        const haystack = [product?.name, product?.category].join(' ').toLowerCase();

        if (/(jacket|blazer|coat|suit)/.test(haystack)) {
            return ['32R', '34R', '36R', '38R', '40R', '42R', '44R', '46R'];
        }

        if (/(shoe|sneaker|loafer|boot|sandal)/.test(haystack)) {
            return ['6', '7', '8', '9', '10'];
        }

        return ['S', 'M', 'L', 'XL'];
    }

    function buildDetailSizeGuide(sizeOptions = []) {
        if (!sizeOptions.length) {
            return null;
        }

        const jacketGuideLabels = {
            '32R': 'Chest 34-35 in',
            '34R': 'Chest 36-37 in',
            '36R': 'Chest 38-39 in',
            '38R': 'Chest 40-41 in',
            '40R': 'Chest 42-43 in',
            '42R': 'Chest 44-45 in',
            '44R': 'Chest 46-47 in',
            '46R': 'Chest 48-49 in',
        };
        const alphaGuideLabels = {
            S: 'Chest 36-38 in',
            M: 'Chest 38-40 in',
            L: 'Chest 40-42 in',
            XL: 'Chest 42-44 in',
            XXL: 'Chest 44-46 in',
        };

        const hasTailoredSizes = sizeOptions.some((size) => /\d{2}R/i.test(size));
        const isNumericFootwear = sizeOptions.every((size) => /^\d+$/.test(String(size)));

        if (hasTailoredSizes) {
            return {
                title: 'Regular fit guide',
                copy: 'Pick your usual chest size for a clean tailored silhouette. If you prefer extra room for layering, go one size up.',
                items: sizeOptions.map((size) => ({
                    size,
                    copy: jacketGuideLabels[size] || 'Classic tailored fit',
                })),
            };
        }

        if (isNumericFootwear) {
            return {
                title: 'Footwear size guide',
                copy: 'If you are between two sizes, choose the larger size for all-day comfort.',
                items: sizeOptions.map((size) => ({
                    size,
                    copy: `Standard fit ${size}`,
                })),
            };
        }

        return {
            title: 'Apparel size guide',
            copy: 'These measurements reflect a regular fit. For a relaxed silhouette, size up once.',
            items: sizeOptions.map((size) => ({
                size,
                copy: alphaGuideLabels[size] || 'Regular fit',
            })),
        };
    }

    function renderDetailSizeGuidePanel() {
        const panel = document.getElementById('detail-size-guide-panel');
        const trigger = document.getElementById('detail-size-guide-trigger');
        const guide = storefrontState.detailVariantOptions.sizeGuide;

        if (!panel) {
            return;
        }

        if (!guide) {
            panel.innerHTML = '';
            panel.classList.add('hidden');
            trigger?.classList.add('hidden');
            return;
        }

        trigger?.classList.remove('hidden');
        panel.innerHTML = `
            <div>
                <strong>${safeHtml(guide.title)}</strong>
                <p class="detail-size-guide-copy">${safeHtml(guide.copy)}</p>
            </div>
            <div class="detail-size-guide-grid">
                ${guide.items.map((item) => `
                    <div class="detail-size-guide-item">
                        <strong>${safeHtml(item.size)}</strong>
                        <span>${safeHtml(item.copy)}</span>
                    </div>
                `).join('')}
            </div>
        `;
    }

    function updateDetailSelectionMessage() {
        const message = document.getElementById('detail-selection-message');
        if (!message) {
            return;
        }

        const { colors, requiresSize } = storefrontState.detailVariantOptions;
        const { colorIndex, size } = storefrontState.detailSelections;
        const activeColour = colors[colorIndex]?.label;
        const stockCount = Number(storefrontState.detailProduct?.stock || 0);

        if (stockCount <= 0) {
            message.textContent = 'This item is currently out of stock.';
            message.classList.remove('hidden');
            message.classList.add('is-warning');
            return;
        }

        if (requiresSize && !size) {
            message.textContent = 'Choose a size before adding this item to your cart.';
            message.classList.remove('hidden');
            message.classList.add('is-warning');
            return;
        }

        const selections = [];
        if (activeColour) {
            selections.push(activeColour);
        }
        if (size) {
            selections.push(`Size ${size}`);
        }

        if (selections.length === 0) {
            message.classList.add('hidden');
            message.classList.remove('is-warning');
            message.textContent = '';
            return;
        }

        message.textContent = `Selected: ${selections.join(' / ')}`;
        message.classList.remove('hidden', 'is-warning');
    }

    function updateDetailVariantUi() {
        const colourValue = document.getElementById('detail-colour-value');
        const sizeValue = document.getElementById('detail-size-value');
        const activeColour = storefrontState.detailVariantOptions.colors[storefrontState.detailSelections.colorIndex];

        document.querySelectorAll('.detail-colour-swatch').forEach((swatch) => {
            swatch.classList.toggle('is-active', Number(swatch.dataset.colorIndex) === storefrontState.detailSelections.colorIndex);
        });

        document.querySelectorAll('.detail-size-chip').forEach((chip) => {
            chip.classList.toggle('is-active', chip.dataset.size === storefrontState.detailSelections.size);
        });

        if (colourValue) {
            colourValue.textContent = activeColour?.label || 'Selected look';
        }

        if (sizeValue) {
            sizeValue.textContent = storefrontState.detailSelections.size || 'Select your size';
        }

        renderDetailSizeGuidePanel();
        updateDetailSelectionMessage();
    }

    function syncDetailColourSelectionFromImage(imageUrl) {
        const matchedIndex = storefrontState.detailVariantOptions.colors.findIndex((option) => option.imageUrl === imageUrl);

        if (matchedIndex >= 0) {
            storefrontState.detailSelections.colorIndex = matchedIndex;
            updateDetailVariantUi();
        }
    }

    function renderDetailVariants(product) {
        const panel = document.getElementById('detail-variant-panel');
        const colourGroup = document.getElementById('detail-colour-group');
        const colourSwatches = document.getElementById('detail-colour-swatches');
        const sizeGroup = document.getElementById('detail-size-group');
        const sizeGrid = document.getElementById('detail-size-grid');
        const sizeGuidePanel = document.getElementById('detail-size-guide-panel');

        if (!panel || !colourGroup || !colourSwatches || !sizeGroup || !sizeGrid) {
            return;
        }

        const colors = inferDetailColourOptions(product);
        const sizes = inferDetailSizeOptions(product);

        storefrontState.detailVariantOptions = {
            colors,
            sizes,
            requiresSize: sizes.length > 0,
            sizeGuide: buildDetailSizeGuide(sizes),
        };
        storefrontState.detailSelections.colorIndex = 0;
        storefrontState.detailSelections.size = null;

        panel.classList.toggle('hidden', colors.length === 0 && sizes.length === 0);

        colourGroup.classList.toggle('hidden', colors.length === 0);
        if (colors.length > 0) {
            colourSwatches.innerHTML = colors.map((option, index) => `
                <button
                    type="button"
                    class="detail-colour-swatch ${index === storefrontState.detailSelections.colorIndex ? 'is-active' : ''}"
                    data-color-index="${index}"
                    onclick="selectDetailColour(${index})"
                    data-ripple
                >
                    <img src="${safeHtml(option.imageUrl)}" alt="${safeHtml(option.label)}" onerror="this.src='${FALLBACK_IMAGE}'">
                    <span class="detail-colour-swatch-title">${safeHtml(option.label)}</span>
                </button>
            `).join('');
        } else {
            colourSwatches.innerHTML = '';
        }

        sizeGroup.classList.toggle('hidden', sizes.length === 0);
        sizeGrid.innerHTML = sizes.map((size) => `
            <button
                type="button"
                class="detail-size-chip"
                data-size="${safeHtml(size)}"
                onclick='selectDetailSize(${JSON.stringify(size)})'
                data-ripple
            >
                ${safeHtml(size)}
            </button>
        `).join('');

        if (sizeGuidePanel) {
            sizeGuidePanel.classList.add('hidden');
        }

        updateDetailVariantUi();
    }

    function getSelectedDetailVariantLabel() {
        const parts = [];
        const activeColour = storefrontState.detailVariantOptions.colors[storefrontState.detailSelections.colorIndex];

        if (activeColour?.label) {
            parts.push(activeColour.label);
        }

        if (storefrontState.detailSelections.size) {
            parts.push(`Size ${storefrontState.detailSelections.size}`);
        }

        return parts.join(' / ');
    }

    function renderDetailSellerMeta(product) {
        const sellerMeta = document.getElementById('detail-seller-meta');
        if (!sellerMeta) return;

        const blocks = [
            {
                title: 'Seller',
                body: product.seller || 'Marketplace',
                note: 'Trusted storefront partner',
            },
            {
                title: 'Category',
                body: product.category || 'Curated',
                note: 'Organized for fast discovery',
            },
            {
                title: 'Availability',
                body: Number(product.stock || 0) > 0 ? `${product.stock} units ready` : 'Currently unavailable',
                note: 'Live inventory sync',
            },
        ];

        sellerMeta.innerHTML = blocks.map((block) => `
            <div class="detail-seller-item">
                <div>
                    <strong>${safeHtml(block.title)}</strong>
                    <p>${safeHtml(block.body)}</p>
                </div>
                <p>${safeHtml(block.note)}</p>
            </div>
        `).join('');
    }

    function renderDetailSpecs(product) {
        const specs = document.getElementById('detail-specs');
        if (!specs) return;

        const specList = Array.isArray(product.specifications) && product.specifications.length
            ? product.specifications
            : [
                { key: 'Category', value: product.category || 'Curated' },
                { key: 'Seller', value: product.seller || 'Marketplace' },
                { key: 'Stock', value: Number(product.stock || 0) > 0 ? `${product.stock} available` : 'Sold out' },
                { key: 'Wishlist', value: storefrontState.wishlist.has(product.uuid) ? 'Saved' : 'Not saved yet' },
            ];

        specs.innerHTML = specList.slice(0, 6).map((spec) => `
            <div class="detail-spec-item">
                <strong>${safeHtml(spec.key)}</strong>
                <span>${safeHtml(spec.value)}</span>
            </div>
        `).join('');
    }

    function syncDetailWishlistButton() {
        const button = document.getElementById('detail-wishlist-toggle');
        if (!button || !storefrontState.detailProduct) return;

        const isSaved = storefrontState.wishlist.has(storefrontState.detailProduct.uuid);
        button.classList.toggle('is-active', isSaved);
        button.textContent = isSaved ? 'Saved to Wishlist' : 'Save to Wishlist';
    }

    function clearDetailGalleryTimer() {
        if (storefrontState.detailGalleryTimer) {
            window.clearInterval(storefrontState.detailGalleryTimer);
            storefrontState.detailGalleryTimer = null;
        }
    }

    function updateDetailGalleryStatus() {
        const status = document.getElementById('detail-gallery-status');
        if (!status) return;

        const totalImages = storefrontState.detailGalleryImages.length || 1;
        const currentIndex = Math.min(storefrontState.detailGalleryIndex + 1, totalImages);
        status.textContent = `${currentIndex} / ${totalImages}`;
    }

    function startDetailGalleryAutoplay() {
        clearDetailGalleryTimer();

        if (storefrontState.detailGalleryStopped || !window.location.hash.startsWith('#product/')) {
            return;
        }

        if (storefrontState.detailGalleryImages.length < 2) {
            return;
        }

        storefrontState.detailGalleryTimer = window.setInterval(() => {
            const nextIndex = (storefrontState.detailGalleryIndex + 1) % storefrontState.detailGalleryImages.length;
            setDetailPrimaryImage(storefrontState.detailGalleryImages[nextIndex], {
                index: nextIndex,
            });
        }, 3000);
    }

    function syncDetailGalleryAutoplay(resetStopped = false) {
        if (resetStopped) {
            storefrontState.detailGalleryStopped = false;
        }

        window.setTimeout(() => {
            startDetailGalleryAutoplay();
        }, 120);
    }

    function stopDetailGalleryAutoplay() {
        storefrontState.detailGalleryStopped = true;
        clearDetailGalleryTimer();
    }

    function resetDetailGalleryAutoplay() {
        storefrontState.detailGalleryStopped = false;
        clearDetailGalleryTimer();
    }

    function setDetailPrimaryImage(imageUrl, options = {}) {
        const primaryImage = document.getElementById('detail-primary-image');
        if (!primaryImage) return;

        const nextImageUrl = imageUrl || FALLBACK_IMAGE;
        const nextIndex = typeof options.index === 'number'
            ? options.index
            : storefrontState.detailGalleryImages.findIndex((galleryImage) => galleryImage === nextImageUrl);
        const currentImage = primaryImage.dataset.currentImage || '';
        const shouldAnimate = options.animate !== false && currentImage && currentImage !== nextImageUrl;
        const transitionToken = storefrontState.detailImageTransitionToken + 1;

        storefrontState.detailImageTransitionToken = transitionToken;
        storefrontState.detailGalleryIndex = nextIndex >= 0 ? nextIndex : 0;

        document.querySelectorAll('.detail-thumb').forEach((thumb) => {
            thumb.classList.toggle('is-active', thumb.dataset.imageUrl === nextImageUrl);
        });

        updateDetailGalleryStatus();
        syncDetailColourSelectionFromImage(nextImageUrl);

        const applyNextImage = () => {
            if (storefrontState.detailImageTransitionToken !== transitionToken) {
                return;
            }

            primaryImage.src = nextImageUrl;
            primaryImage.dataset.currentImage = nextImageUrl;
            primaryImage.onerror = function handleImageError() {
                this.src = FALLBACK_IMAGE;
            };

            const finalizeTransition = () => {
                if (storefrontState.detailImageTransitionToken !== transitionToken) {
                    return;
                }

                primaryImage.classList.remove('is-fading');
                applyStorefrontDynamicTheme(primaryImage.src);
            };

            if (primaryImage.complete) {
                window.requestAnimationFrame(finalizeTransition);
            } else {
                primaryImage.addEventListener('load', finalizeTransition, { once: true });
                primaryImage.addEventListener('error', finalizeTransition, { once: true });
            }
        };

        if (shouldAnimate) {
            primaryImage.classList.add('is-fading');
            window.setTimeout(applyNextImage, 140);
        } else {
            primaryImage.classList.remove('is-fading');
            applyNextImage();
        }
    }

    function renderDetailGallery(product) {
        const primary = getDisplayImage(product.primary_image);
        const images = Array.isArray(product.images) && product.images.length
            ? [primary, ...product.images.map(getDisplayImage)]
            : [primary];
        const uniqueImages = Array.from(new Set(images.filter(Boolean)));
        const grid = document.getElementById('detail-images-grid');

        if (!grid) return;

        storefrontState.detailGalleryImages = uniqueImages;
        storefrontState.detailGalleryIndex = 0;
        storefrontState.detailGalleryStopped = false;

        grid.innerHTML = uniqueImages.map((imageUrl, index) => `
            <button
                type="button"
                class="detail-thumb ${index === 0 ? 'is-active' : ''}"
                data-image-url="${safeHtml(imageUrl)}"
                onclick='swapDetailImage(${JSON.stringify(imageUrl)}, event)'
                data-ripple
            >
                <img src="${imageUrl}" alt="Product thumbnail ${index + 1}" onerror="this.src='${FALLBACK_IMAGE}'">
            </button>
        `).join('');

        setDetailPrimaryImage(uniqueImages[0] || primary, { index: 0, animate: false });
        syncDetailGalleryAutoplay(true);
    }

    function setupDetailZoom() {
        const stage = document.getElementById('detail-image-stage');
        if (!stage || stage.dataset.zoomBound === 'true') return;

        stage.dataset.zoomBound = 'true';

        stage.addEventListener('pointermove', (event) => {
            const rect = stage.getBoundingClientRect();
            const x = ((event.clientX - rect.left) / rect.width) * 100;
            const y = ((event.clientY - rect.top) / rect.height) * 100;

            stage.style.setProperty('--zoom-x', `${Math.max(0, Math.min(100, x))}%`);
            stage.style.setProperty('--zoom-y', `${Math.max(0, Math.min(100, y))}%`);
            stage.classList.add('is-zoomed');
        });

        stage.addEventListener('pointerleave', () => {
            stage.classList.remove('is-zoomed');
        });
    }

    function updateDetailPurchaseControls(product) {
        const addButton = document.getElementById('add-to-cart-btn');
        const buyButton = document.getElementById('buy-now-btn');
        const stockCount = Number(product.stock || 0);
        const isCustomer = !AppState?.user || AppState.user.role === 'customer';
        const isAdmin = AppState?.user?.role === 'admin';
        const sizeRequired = storefrontState.detailVariantOptions.requiresSize;
        const sizeSelected = Boolean(storefrontState.detailSelections.size);
        const shouldDisablePurchase = stockCount <= 0 || (sizeRequired && !sizeSelected);

        if (addButton) {
            addButton.style.display = isCustomer && !isAdmin ? '' : 'none';
            addButton.disabled = shouldDisablePurchase;
        }

        if (buyButton) {
            buyButton.style.display = isCustomer && !isAdmin ? '' : 'none';
            buyButton.disabled = shouldDisablePurchase;
        }

        updateDetailSelectionMessage();
    }

    function renderProductDetail(product) {
        storefrontState.detailProduct = product;
        AppState.currentProduct = product;

        const pricing = getPricing(product);
        const detailName = document.getElementById('detail-name');
        const detailDescription = document.getElementById('detail-description');
        const detailCategory = document.getElementById('detail-category-pill');
        const detailStock = document.getElementById('detail-stock');
        const detailPrice = document.getElementById('detail-price');
        const detailOriginal = document.getElementById('detail-original-price');
        const detailInfo = document.getElementById('detail-info');
        const detailRatingCopy = document.getElementById('detail-rating-copy');
        const detailBadge = document.getElementById('detail-discount-badge');

        if (detailName) detailName.textContent = product.name || 'Product';
        if (detailDescription) detailDescription.textContent = getDerivedDescription(product);
        if (detailCategory) detailCategory.textContent = product.category || 'Curated';
        if (detailStock) {
            detailStock.textContent = Number(product.stock || 0) > 0 ? `${product.stock} in stock` : 'Out of stock';
            detailStock.classList.toggle('out', Number(product.stock || 0) <= 0);
        }
        if (detailPrice) detailPrice.textContent = formatCurrency(pricing.price);
        if (detailOriginal) {
            detailOriginal.textContent = pricing.originalPrice > pricing.price ? formatCurrency(pricing.originalPrice) : '';
            detailOriginal.classList.toggle('hidden', !(pricing.originalPrice > pricing.price));
        }
        if (detailInfo) {
            detailInfo.textContent = `Sold by ${product.seller || 'Marketplace'} / ${getProductRating(product)} rating / Secure checkout ready`;
        }
        if (detailRatingCopy) {
            detailRatingCopy.textContent = `${getProductRating(product)} average rating`;
        }
        if (detailBadge) {
            detailBadge.textContent = pricing.discount > 0 ? `${pricing.discount}% OFF` : '';
            detailBadge.classList.toggle('hidden', pricing.discount <= 0);
        }

        renderDetailSpecs(product);
        renderDetailHighlights(product);
        renderDetailSellerMeta(product);
        renderDetailReviews(product);
        renderDetailGallery(product);
        renderDetailVariants(product);
        syncDetailWishlistButton();
        updateDetailPurchaseControls(product);
        setupDetailZoom();
    }

    window.loadProductDetail = async function loadProductDetail(productUuid) {
        if (!productUuid) {
            showToast('Unable to open that product.', 'error');
            navigateTo('#products');
            return;
        }

        renderDetailSkeleton();

        const response = await API.fetchProductDetail(productUuid);
        const rawProduct = response?.product;

        if (!rawProduct) {
            showToast('Unable to load product details.', 'error');
            navigateTo('#products');
            return;
        }

        const listProduct = storefrontState.products.find((product) => product.uuid === productUuid) || {};
        const detailProduct = {
            ...listProduct,
            ...rawProduct,
            price: Number(rawProduct.price ?? listProduct.price ?? 0),
            stock: Number(rawProduct.stock ?? listProduct.stock ?? 0),
            category: rawProduct.category || listProduct.category,
            seller: rawProduct.seller || listProduct.seller,
            primary_image: rawProduct.primary_image || listProduct.primary_image,
            specifications: Array.isArray(rawProduct.specifications) ? rawProduct.specifications : (listProduct.specifications || []),
            images: Array.isArray(rawProduct.images) ? rawProduct.images : [],
        };

        renderProductDetail(detailProduct);
    };

    window.selectDetailColour = function selectDetailColour(index) {
        const nextIndex = Number(index);
        const option = storefrontState.detailVariantOptions.colors[nextIndex];

        if (!option) {
            return;
        }

        storefrontState.detailSelections.colorIndex = nextIndex;
        stopDetailGalleryAutoplay();
        updateDetailVariantUi();
        setDetailPrimaryImage(option.imageUrl, {
            index: option.galleryIndex,
        });
    };

    window.selectDetailSize = function selectDetailSize(size) {
        const nextSize = String(size || '');
        const isSameSize = storefrontState.detailSelections.size === nextSize;
        storefrontState.detailSelections.size = isSameSize ? null : nextSize;
        updateDetailVariantUi();
        updateDetailPurchaseControls(storefrontState.detailProduct || {});
    };

    window.toggleDetailSizeGuide = function toggleDetailSizeGuide() {
        const panel = document.getElementById('detail-size-guide-panel');
        if (!panel || !storefrontState.detailVariantOptions.sizeGuide) {
            return;
        }

        panel.classList.toggle('hidden');
    };

    window.swapDetailImage = function swapDetailImage(imageUrl, event) {
        event?.stopPropagation();
        if (event) {
            stopDetailGalleryAutoplay();
        }
        setDetailPrimaryImage(imageUrl);
    };

    window.syncDetailGalleryAutoplay = syncDetailGalleryAutoplay;
    window.stopDetailGalleryAutoplay = stopDetailGalleryAutoplay;
    window.resetDetailGalleryAutoplay = resetDetailGalleryAutoplay;

    window.toggleDetailWishlist = function toggleDetailWishlist() {
        if (!storefrontState.detailProduct) return;
        const productUuid = storefrontState.detailProduct.uuid;

        if (storefrontState.wishlist.has(productUuid)) {
            storefrontState.wishlist.delete(productUuid);
            showToast('Removed from wishlist.', 'info');
        } else {
            storefrontState.wishlist.add(productUuid);
            showToast('Saved to wishlist.', 'success');
        }

        persistWishlist();
        syncDetailWishlistButton();
        renderProducts(getFilteredProducts());
    };

    window.addToCart = async function addToCart() {
        if (!storefrontState.detailProduct) {
            showToast('No product selected.', 'warning');
            return;
        }

        if (storefrontState.detailVariantOptions.requiresSize && !storefrontState.detailSelections.size) {
            showToast('Please select a size before adding this item to the cart.', 'warning');
            return;
        }

        const quantity = Math.max(1, Number(document.getElementById('detail-quantity')?.value || 1));
        if (Number(storefrontState.detailProduct.stock || 0) < quantity) {
            showToast('Requested quantity exceeds current stock.', 'warning');
            return;
        }

        const variantLabel = getSelectedDetailVariantLabel();
        ui?.setAddToCartLoading?.(true);
        try {
            await addProductToCart(storefrontState.detailProduct.uuid, quantity, {
                successMessage: variantLabel ? `${variantLabel} added to your cart.` : 'Product added to your cart.',
            });
        } finally {
            ui?.setAddToCartLoading?.(false);
        }
    };

    window.buyNowFromDetail = async function buyNowFromDetail() {
        if (!storefrontState.detailProduct) {
            showToast('No product selected.', 'warning');
            return;
        }

        if (storefrontState.detailVariantOptions.requiresSize && !storefrontState.detailSelections.size) {
            showToast('Please select a size before continuing to checkout.', 'warning');
            return;
        }

        const quantity = Math.max(1, Number(document.getElementById('detail-quantity')?.value || 1));
        const variantLabel = getSelectedDetailVariantLabel();

        if (addButton) {
            addButton.disabled = true;
        }

        try {
            await addProductToCart(storefrontState.detailProduct.uuid, quantity, {
                successMessage: variantLabel ? `${variantLabel} selected. Redirecting to checkout.` : 'Product added. Redirecting to checkout.',
                afterSuccess: () => navigateTo('#checkout'),
            });
        } finally {
            updateDetailPurchaseControls(storefrontState.detailProduct || {});
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        overrideToast();
        loadTheme();
        syncStorefrontNav();
        document.addEventListener('click', spawnRipple);
        window.addEventListener('resize', updateCategoryIndicator);

        if (!window.location.hash.startsWith('#product/')) {
            resetProductTheme();
        }

        if (typeof window.updateUIBasedOnAuth === 'function') {
            window.updateUIBasedOnAuth();
        }
    });
})();
