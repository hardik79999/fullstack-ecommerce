// ============================================
// E-Commerce Pro - REFACTORED State Management
// Professional Architecture with Proper Syncing
// ============================================

const CONFIG = {
    API_BASE_URL: 'http://127.0.0.1:5000/api',
    TOKEN_KEY: 'authToken',
    USER_KEY: 'user',
    CART_KEY: 'cart',
    DEBOUNCE_DELAY: 300,
};

// ============================================
// ✅ GLOBAL STATE OBJECT - Single Source of Truth
// ============================================
const AppState = {
    user: null,
    token: null,
    cart: [],
    selectedAddress: null,
    selectedAddresses: [],
    currentProduct: null,
    currentOrder: null,
    isLoading: false,
    isPendingCart: false,  // NEW: Prevent spam clicks
    isInitialized: false,  // NEW: Track if app is ready
    
    // ✅ Methods for safe state updates
    setUser(user, token) {
        this.user = user;
        this.token = token;
        console.log('[STATE] User set:', user?.username || 'anonymous');
    },
    
    setCart(cartItems) {
        this.cart = Array.isArray(cartItems) ? cartItems : [];
        console.log('[STATE] Cart synced:', this.cart.length, 'items');
    },
    
    updateCartBadge() {
        const badge = document.getElementById('cart-badge');
        if (badge) {
            badge.textContent = this.cart.reduce((sum, item) => sum + (item.quantity || 0), 0);
        }
    },
    
    persist() {
        try {
            if (this.token) localStorage.setItem(CONFIG.TOKEN_KEY, this.token);
            if (this.user) localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(this.user));
            if (this.cart.length > 0) localStorage.setItem(CONFIG.CART_KEY, JSON.stringify(this.cart));
            else localStorage.removeItem(CONFIG.CART_KEY);
        } catch (e) {
            console.error('[STATE] Persist failed:', e);
        }
    },
    
    clear() {
        this.user = null;
        this.token = null;
        this.cart = [];
        this.selectedAddress = null;
        localStorage.removeItem(CONFIG.TOKEN_KEY);
        localStorage.removeItem(CONFIG.USER_KEY);
        localStorage.removeItem(CONFIG.CART_KEY);
        console.log('[STATE] Cleared');
    },
};

// ============================================
// ✅ INITIALIZATION - Run on page load
// ============================================
document.addEventListener('DOMContentLoaded', async () => {
    console.log('[INIT] Starting application...');
    
    // Load persisted state
    loadStateFromStorage();
    
    // Set up event listeners
    window.addEventListener('hashchange', router);
    
    // Update UI based on auth state
    updateUIBasedOnAuth();
    
    // CRITICAL: Initialize app (fetch fresh data if authenticated)
    await initializeApp();
    
    // Route to current hash
    router();
});

// ============================================
// ✅ APP INITIALIZATION - Sync with backend
// ============================================
async function initializeApp() {
    console.log('[INIT] initializeApp() called, token:', !!AppState.token);
    
    if (!AppState.token) {
        AppState.isInitialized = true;
        return;
    }
    
    // If user is logged in, fetch their data from backend
    const userProfile = await API.fetchProfile();
    if (userProfile) {
        // User data is already set in API response
        
        // CRITICAL: If customer, fetch cart from backend
        if (AppState.user?.role === 'customer') {
            console.log('[INIT] Customer detected, syncing cart from backend...');
            const cartData = await API.fetchCart();
            if (cartData && cartData.items) {
                AppState.setCart(cartData.items);
                AppState.updateCartBadge();
            } else {
                AppState.setCart([]);
                AppState.updateCartBadge();
            }
        }
    }
    
    AppState.isInitialized = true;
    console.log('[INIT] App initialized:', AppState);
}

function loadStateFromStorage() {
    try {
        const token = localStorage.getItem(CONFIG.TOKEN_KEY);
        const user = localStorage.getItem(CONFIG.USER_KEY);
        const cart = localStorage.getItem(CONFIG.CART_KEY);
        
        if (token) AppState.token = token;
        if (user) AppState.user = JSON.parse(user);
        if (cart) AppState.cart = JSON.parse(cart) || [];
        
        console.log('[STORAGE] Loaded:', { token: !!token, user: !!user, cart: AppState.cart.length });
    } catch (error) {
        console.error('[STORAGE] Load failed:', error);
        AppState.clear();
    }
}

// ============================================
// ✅ API ABSTRACTION LAYER - Professional HTTP wrapper
// ============================================

const API = {
    /**
     * Base API call with comprehensive error handling
     */
    async call(endpoint, method = 'GET', body = null) {
        try {
            // Prevent loading state from blocking GET requests
            if (AppState.isLoading && method !== 'GET') {
                console.warn('[API] Request blocked: already loading');
                showToast('Please wait, request in progress...', 'warning');
                return null;
            }

            AppState.isLoading = true;
            const url = `${CONFIG.API_BASE_URL}${endpoint}`;
            
            const options = {
                method,
                headers: {
                    'Content-Type': 'application/json',
                },
            };

            // Add token if available
            if (AppState.token) {
                options.headers['Authorization'] = `Bearer ${AppState.token}`;
            }

            // Handle FormData (file uploads)
            if (body instanceof FormData) {
                delete options.headers['Content-Type'];
                options.body = body;
            } else if (body) {
                options.body = JSON.stringify(body);
            }

            console.log(`[API] ${method} ${endpoint}`, body || '');

            const response = await fetch(url, options);
            let data;

            try {
                data = await response.json();
            } catch (e) {
                console.error('[API] JSON parse failed:', e);
                showToast('Invalid server response', 'error');
                return null;
            }

            // Handle 401 - Session expired
            if (response.status === 401) {
                console.warn('[API] 401 - Session expired');
                AppState.clear();
                updateUIBasedOnAuth();
                showToast('Session expired. Please login again.', 'warning');
                navigateTo('#login');
                return null;
            }

            // Handle other errors
            if (!response.ok) {
                const msg = data?.error || data?.message || `Error ${response.status}`;
                console.error(`[API] ${response.status}:`, msg);
                showToast(msg, 'error');
                return null;
            }

            console.log('[API] Response:', data);
            return data;

        } catch (error) {
            console.error('[API] Fetch failed:', error);
            showToast('Network error. Please try again.', 'error');
            return null;
        } finally {
            AppState.isLoading = false;
        }
    },

    // ✅ Authentication
    async login(email, password) {
        const response = await this.call('/auth/login', 'POST', { email, password });
        if (response) {
            AppState.setUser(response.user || { email, role: response.role }, response.access_token);
            AppState.persist();
            return response;
        }
        return null;
    },

    async signup(username, email, password, role) {
        return this.call('/auth/signup', 'POST', { username, email, password, role });
    },

    // ✅ Profile & Cart
    async fetchProfile() {
        const response = await this.call('/user/profile', 'GET');
        if (response?.user) {
            AppState.setUser(response.user, AppState.token);
            AppState.persist();
        }
        return response;
    },

    async fetchCart() {
        return this.call('/user/cart', 'GET');
    },

    async addToCart(product_uuid, quantity) {
        if (AppState.isPendingCart) {
            console.warn('[API] Add to cart already pending');
            return null;
        }

        AppState.isPendingCart = true;
        try {
            const response = await this.call('/user/cart', 'POST', { product_uuid, quantity });
            if (response) {
                // Fetch updated cart from backend to ensure sync
                const cart = await this.fetchCart();
                if (cart?.items) {
                    AppState.setCart(cart.items);
                    AppState.updateCartBadge();
                }
            }
            return response;
        } finally {
            AppState.isPendingCart = false;
        }
    },

    // ✅ Products
    async fetchProducts() {
        return this.call('/user/products', 'GET');
    },

    async fetchProductDetail(uuid) {
        return this.call(`/user/product/${uuid}`, 'GET');
    },

    // ✅ Checkout
    async saveAddress(addressData) {
        return this.call('/user/address', 'POST', addressData);
    },

    async checkout(address_uuid) {
        return this.call('/user/checkout', 'POST', { address_uuid });
    },

    async processPayment(order_uuid, payment_method) {
        return this.call('/user/payment', 'POST', { order_uuid, payment_method });
    },

    // ✅ Orders
    async fetchOrders() {
        return this.call('/user/orders', 'GET');
    },

    async trackOrder(order_uuid) {
        return this.call(`/user/order/${order_uuid}/track`, 'GET');
    },
};

// ============================================
// ✅ UI UTILITIES
// ============================================

function showToast(message, type = 'info', duration = 3000) {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
    
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || '●'}</span>
        <span>${escapeHtml(message)}</span>
    `;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

function escapeHtml(text) {
    if (!text) return '';
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function navigateTo(path) {
    window.location.hash = path;
}
        
        // Always try to parse JSON, but handle errors gracefully
        let data;
        try {
            data = await response.json();
        } catch (jsonError) {
            console.error('Failed to parse JSON response:', jsonError);
            showToast('Invalid server response. Please try again.', 'error');
            return null;
        }

        if (!response.ok) {
            // Handle 401 - Token expired or invalid
            if (response.status === 401) {
                clearAuthState();
                updateUIBasedOnAuth();
                showToast('Session expired. Please login again.', 'warning');
                navigateTo('#login');
                return null;
            }

            // Handle 403 - Access denied
            if (response.status === 403) {
                const errorMessage = data.error || data.message || 'Access denied';
                showToast(errorMessage, 'error');
                return null;
            }

            // Handle 404 - Not found
            if (response.status === 404) {
                const errorMessage = data.error || data.message || 'Resource not found';
                showToast(errorMessage, 'error');
                return null;
            }

            // Handle 400 - Bad request
            if (response.status === 400) {
                const errorMessage = data.error || data.message || 'Invalid request';
                showToast(errorMessage, 'error');
                return null;
            }

            // Handle 409 - Conflict
            if (response.status === 409) {
                const errorMessage = data.error || data.message || 'Resource already exists';
                showToast(errorMessage, 'error');
                return null;
            }

            // Handle 500+ server errors
            if (response.status >= 500) {
                showToast('Server error. Please try again later.', 'error');
                return null;
            }

            // Generic error message
            const errorMessage = data.error || data.message || `Error: ${response.status} ${response.statusText}`;
            showToast(errorMessage, 'error');
            return null;
        }

        return data;
    } catch (error) {
        console.error('API Call Error:', error);
        
        // Network errors
        if (error instanceof TypeError) {
            showToast('Network error. Please check your connection.', 'error');
        } else if (error.name === 'AbortError') {
            showToast('Request cancelled.', 'warning');
        } else {
            showToast('An unexpected error occurred. Please try again.', 'error');
        }
        
        return null;
    } finally {
        appState.isLoading = false;
    }
}

function clearAuthState() {
    appState.token = null;
    appState.user = null;
    appState.cart = [];
    appState.selectedAddress = null;
    appState.selectedAddresses = [];
    appState.currentProduct = null;
    appState.currentOrder = null;
    
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(CART_KEY);
}

// ============================================
// Authentication
// ============================================

async function handleLogin(event) {
    event.preventDefault();
    
    const email = document.getElementById('login-email')?.value;
    const password = document.getElementById('login-password')?.value;

    if (!email || !password) {
        showToast('Email and password are required', 'warning');
        return;
    }

    const response = await apiCall('/auth/login', 'POST', { email, password });
    
    if (response) {
        appState.token = response.access_token;
        appState.user = response.user || { email, role: response.role };
        saveStateToLocalStorage();
        showToast('Login successful!', 'success');
        
        // Sync cart for customers immediately after login
        if (appState.user?.role === 'customer') {
            await syncCartAfterLogin();
        }
        
        updateUIBasedOnAuth();
        navigateTo('#home');
    }
}

async function syncCartAfterLogin() {
    try {
        // Optionally fetch cart from server if needed
        // For now, use client-side cart
        updateCartBadge();
    } catch (error) {
        console.error('Cart sync error:', error);
    }
}

async function handleSignup(event) {
    event.preventDefault();
    
    const username = document.getElementById('signup-username')?.value;
    const email = document.getElementById('signup-email')?.value;
    const password = document.getElementById('signup-password')?.value;
    const role = document.getElementById('signup-role')?.value;

    if (!username || !email || !password || !role) {
        showToast('All fields are required', 'warning');
        return;
    }

    const response = await apiCall('/auth/signup', 'POST', { 
        username, 
        email, 
        password, 
        role 
    });
    
    if (response) {
        showToast('Account created! Please login.', 'success');
        switchAuthTab('login');
        const loginEmailField = document.getElementById('login-email');
        if (loginEmailField) {
            loginEmailField.value = email;
        }
    }
}

function logout() {
    appState.token = null;
    appState.user = null;
    appState.cart = [];
    appState.selectedAddress = null;
    appState.selectedAddresses = [];
    appState.currentProduct = null;
    appState.currentOrder = null;
    
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(CART_KEY);
    updateUIBasedOnAuth();
    // Explicitly clear cart DOM
    const cartItemsDiv = document.getElementById('cart-items');
    if (cartItemsDiv) {
        cartItemsDiv.innerHTML = '';
    }
    updateCartBadge();
    showToast('Logged out successfully', 'info');
    navigateTo('#home');
}

// ============================================
// UI Updates Based on Authentication
// ============================================

function updateUIBasedOnAuth() {
    const isLoggedIn = !!appState.token;
    const role = appState.user?.role;

    // Render navbar based on auth state
    renderNavbar(isLoggedIn, role);
}

function renderNavbar(isLoggedIn, role) {
    // Get all navbar elements
    const navLogin = document.getElementById('nav-login');
    const navLogout = document.getElementById('nav-logout');
    const navProducts = document.getElementById('nav-products');
    const navCart = document.getElementById('nav-cart');
    const navProfile = document.getElementById('nav-profile');
    const navSeller = document.getElementById('nav-seller');
    const navAdmin = document.getElementById('nav-admin');

    // Reset all to hidden first
    [navLogin, navLogout, navProducts, navCart, navProfile, navSeller, navAdmin].forEach(el => {
        if (el) el.style.display = 'none';
    });

    // Show/hide based on login state
    if (!isLoggedIn) {
        // Unauthenticated: Show login only (Home is always visible)
        if (navLogin) navLogin.style.display = 'block';
    } else {
        // All logged-in users: Show logout and profile
        if (navLogout) navLogout.style.display = 'block';
        if (navProfile) navProfile.style.display = 'block';

        // Role-based navbar
        if (role === 'customer') {
            // Customers: Show cart and products
            if (navCart) navCart.style.display = 'block';
            if (navProducts) navProducts.style.display = 'block';
        } else if (role === 'seller') {
            // Sellers: Show seller dashboard only (NO cart, NO products browsing)
            if (navSeller) navSeller.style.display = 'block';
        } else if (role === 'admin') {
            // Admins: Show admin dashboard only (NO cart, NO products browsing)
            if (navAdmin) navAdmin.style.display = 'block';
        }
    }
}

// ============================================
// Router (Hash-based)
// ============================================

function router() {
    const hash = window.location.hash.slice(1) || 'home';
    const [page, ...params] = hash.split('/');
    const isLoggedIn = !!appState.token;
    const role = appState.user?.role;

    // Hide all sections
    document.querySelectorAll('.page-section').forEach(section => {
        section.classList.add('hidden');
    });

    // ========== STRICT ROLE-BASED ACCESS CONTROL ==========
    
    // Pages that require login
    const requiresLogin = ['cart', 'checkout', 'profile', 'seller-dash', 'admin-dash', 'order-tracking'];
    if (requiresLogin.includes(page) && !isLoggedIn) {
        showToast('Please login first', 'warning');
        navigateTo('#login');
        return;
    }

    // CUSTOMER-ONLY pages
    if (['cart', 'checkout', 'order-tracking'].includes(page)) {
        if (role !== 'customer') {
            showToast('Access denied: This page is for customers only', 'error');
            if (role === 'seller') navigateTo('#seller-dash');
            else if (role === 'admin') navigateTo('#admin-dash');
            else navigateTo('#home');
            return;
        }
    }

    // SELLER-ONLY pages
    if (page === 'seller-dash' && role !== 'seller') {
        showToast('Access denied: Seller dashboard is for sellers only', 'error');
        if (role === 'customer') navigateTo('#home');
        else if (role === 'admin') navigateTo('#admin-dash');
        else navigateTo('#login');
        return;
    }

    // ADMIN-ONLY pages
    if (page === 'admin-dash' && role !== 'admin') {
        showToast('Access denied: Admin dashboard is for admins only', 'error');
        if (role === 'seller') navigateTo('#seller-dash');
        else if (role === 'customer') navigateTo('#home');
        else navigateTo('#login');
        return;
    }

    // CUSTOMER/UNAUTHENTICATED pages
    if (page === 'products' && isLoggedIn && (role === 'seller' || role === 'admin')) {
        showToast('Sellers and Admins cannot browse products', 'error');
        if (role === 'seller') navigateTo('#seller-dash');
        else if (role === 'admin') navigateTo('#admin-dash');
        return;
    }

    // Render pages
    switch (page) {
        case 'home':
            showSection('home');
            break;
        case 'login':
            if (appState.token) navigateTo('#home');
            else showSection('login');
            break;
        case 'signup':
            if (appState.token) navigateTo('#home');
            else showSection('signup');
            break;
        case 'products':
            showSection('products');
            loadProducts();
            break;
        case 'product':
            // Product detail page: customers and unauthenticated can view, sellers/admins get redirected
            if (isLoggedIn && (role === 'seller' || role === 'admin')) {
                showToast('Sellers and Admins cannot browse products', 'error');
                if (role === 'seller') navigateTo('#seller-dash');
                else if (role === 'admin') navigateTo('#admin-dash');
                return;
            }
            showSection('product-detail');
            loadProductDetail(params[0]);
            break;
        case 'cart':
            showSection('cart');
            loadCart();
            break;
        case 'checkout':
            showSection('checkout');
            loadCheckout();
            break;
        case 'order-tracking':
            showSection('order-tracking');
            loadOrderTracking(params[0]);
            break;
        case 'profile':
            showSection('profile');
            loadProfile();
            break;
        case 'seller-dash':
            showSection('seller-dash');
            loadSellerDashboard();
            break;
        case 'admin-dash':
            showSection('admin-dash');
            loadAdminDashboard();
            break;
        default:
            navigateTo('#home');
    }
}

function showSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
        section.classList.remove('hidden');
        window.scrollTo(0, 0);
    }
}

function navigateTo(path) {
    window.location.hash = path;
}

// ============================================
// Products
// ============================================

async function loadProducts() {
    const response = await apiCall('/user/products');
    
    if (!response) {
        document.getElementById('products-grid').innerHTML = '<div class="col-span-full text-center text-gray-500">Failed to load products</div>';
        return;
    }

    const products = response.products || [];
    const grid = document.getElementById('products-grid');

    if (products.length === 0) {
        grid.innerHTML = '<div class="col-span-full text-center text-gray-500">No products available</div>';
        return;
    }

    grid.innerHTML = products.map(product => {
        // Build image sources with fallback
        const imageUrl = buildImageUrl(product.primary_image);
        
        return `
        <div class="product-card" onclick="navigateTo('#product/${product.uuid}')">
            <div class="product-image-container">
                <img src="${imageUrl}" 
                     alt="${product.name}" 
                     class="product-image" 
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                     onload="this.classList.remove('skeleton')">
                <div class="product-image-error" style="display: none;">📦</div>
            </div>
            <div class="product-info">
                <h3 class="product-name">${escapeHtml(product.name)}</h3>
                <p class="product-description">${escapeHtml(product.description)}</p>
                <p class="product-price">₹${parseFloat(product.price).toFixed(2)}</p>
                <p class="product-stock ${product.stock > 0 ? 'in-stock' : 'out-of-stock'}">
                    ${product.stock > 0 ? `✓ ${product.stock} in stock` : '✕ Out of stock'}
                </p>
                <div class="product-actions">
                    <button class="bg-blue-600 text-white hover:bg-blue-700 btn-primary" onclick="event.stopPropagation(); navigateTo('#product/${product.uuid}')">View</button>
                </div>
            </div>
        </div>
    `}).join('');
}

function buildImageUrl(imageUrl) {
    // If image URL is already complete, use it
    if (!imageUrl) {
        return 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="300" height="260"%3E%3Crect fill="%23e2e8f0" width="300" height="260"/%3E%3Ctext x="50%25" y="50%25" font-size="48" fill="%2364748b" text-anchor="middle" dominant-baseline="middle"%3E%F0%9F%93%A6%3C/text%3E%3C/svg%3E';
    }
    
    // If already has protocol, return as is
    if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
        return imageUrl;
    }
    
    // If it's a relative path, prepend the API base URL
    if (imageUrl.startsWith('/')) {
        return `${API_BASE_URL.replace('/api', '')}${imageUrl}`;
    }
    
    // Otherwise construct it relative to the upload directory
    return `${API_BASE_URL.replace('/api', '')}/static/uploads/products/${imageUrl}`;
}

function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function filterProducts() {
    const searchTerm = document.getElementById('search-products')?.value.toLowerCase() || '';
    document.querySelectorAll('.product-card').forEach(card => {
        const name = card.querySelector('.product-name')?.textContent.toLowerCase() || '';
        const desc = card.querySelector('.product-description')?.textContent.toLowerCase() || '';
        card.style.display = (name.includes(searchTerm) || desc.includes(searchTerm)) ? '' : 'none';
    });
}

async function loadProductDetail(uuid) {
    if (!uuid) {
        showToast('Invalid product', 'error');
        navigateTo('#products');
        return;
    }

    const response = await apiCall(`/user/product/${uuid}`);
    
    if (!response) {
        showToast('Failed to load product', 'error');
        navigateTo('#products');
        return;
    }

    const product = response.product || response;
    appState.currentProduct = product;

    document.getElementById('detail-name').textContent = product.name || 'Product';
    document.getElementById('detail-description').textContent = product.description || '';
    document.getElementById('detail-price').textContent = `₹${parseFloat(product.price || 0).toFixed(2)}`;
    document.getElementById('detail-stock').textContent = product.stock > 0 ? `${product.stock} in stock` : 'Out of stock';

    // Display specifications
    const specsDiv = document.getElementById('detail-specs');
    if (product.specifications && product.specifications.length > 0) {
        specsDiv.innerHTML = '<h4 class="font-semibold mb-2">Specifications</h4>' + 
            product.specifications.map(spec => 
                `<div class="flex justify-between text-sm mb-1">
                    <span class="text-gray-600">${escapeHtml(spec.key)}:</span>
                    <span class="font-semibold">${escapeHtml(spec.value)}</span>
                </div>`
            ).join('');
    } else {
        specsDiv.innerHTML = '';
    }

    // Display images - primary image
    const primaryImage = document.getElementById('detail-primary-image');
    const primaryImageUrl = buildImageUrl(product.primary_image);
    primaryImage.src = primaryImageUrl;
    primaryImage.onerror = function() {
        this.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="500" height="400"%3E%3Crect fill="%23e2e8f0" width="500" height="400"/%3E%3Ctext x="50%25" y="50%25" font-size="48" fill="%2364748b" text-anchor="middle" dominant-baseline="middle"%3E%F0%9F%93%A6%3C/text%3E%3C/svg%3E';
    };

    // Apply dynamic theme color based on product image
    applyDynamicTheme(primaryImageUrl);

    // Display all images in proper grid
    const imagesGrid = document.getElementById('detail-images-grid');
    if (product.images && product.images.length > 0) {
        imagesGrid.innerHTML = product.images.map((img, idx) => `
            <img src="${buildImageUrl(img)}" alt="Image ${idx + 1}" class="image-thumbnail cursor-pointer hover:opacity-80 transition" onclick="swapImages(this)" 
                 onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22%3E%3Crect fill=%22%23e2e8f0%22 width=%22100%22 height=%22100%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 font-size=%2224%22 fill=%22%2364748b%22 text-anchor=%22middle%22 dominant-baseline=%22middle%22%3E%F0%9F%93%A6%3C/text%3E%3C/svg%3E'">
        `).join('');
    }
    
    // ========== STRICT ROLE CHECK: Only customers can see Add to Cart ==========
    const addToCartBtn = document.querySelector('button[onclick="addToCart()"]');
    if (addToCartBtn) {
        // Only show Add to Cart button for customers and unauthenticated users
        const role = appState.user?.role;
        const isCustomer = !appState.user || role === 'customer';
        addToCartBtn.style.display = isCustomer ? 'block' : 'none';
    }
}

function swapImages(imageElement) {
    const primaryImage = document.getElementById('detail-primary-image');
    const temp = primaryImage.src;
    primaryImage.src = imageElement.src;
    imageElement.src = temp;
}

async function addToCart() {
    // CRITICAL FIX: Only customers can buy
    if (!appState.user || appState.user.role !== 'customer') {
        showToast('Only customers can purchase products', 'error');
        return;
    }
    
    if (!appState.currentProduct) {
        showToast('Product not found', 'error');
        return;
    }

    const quantity = parseInt(document.getElementById('detail-quantity')?.value || 1);

    const response = await apiCall('/user/cart', 'POST', {
        product_uuid: appState.currentProduct.uuid,
        quantity
    });

    if (response) {
        const existingItem = appState.cart.find(item => item.product_uuid === appState.currentProduct.uuid);
        if (existingItem) {
            existingItem.quantity += quantity;
        } else {
            appState.cart.push({
                product_uuid: appState.currentProduct.uuid,
                product_name: appState.currentProduct.name,
                product_price: appState.currentProduct.price,
                product_image: appState.currentProduct.primary_image,
                quantity
            });
        }
        saveStateToLocalStorage();
        updateCartBadge();
        showToast(`Added to cart!`, 'success');
    }
}

function updateCartBadge() {
    const badge = document.getElementById('cart-badge');
    if (badge) {
        badge.textContent = appState.cart.reduce((total, item) => total + (item.quantity || 0), 0);
    }
}

// ============================================
// Cart Management
// ============================================

function loadCart() {
    const cartItemsDiv = document.getElementById('cart-items');
    
    if (appState.cart.length === 0) {
        cartItemsDiv.innerHTML = `
            <div class="p-8 text-center text-gray-500">
                <p>Your cart is empty</p>
                <button onclick="navigateTo('#products')" class="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">Continue Shopping</button>
            </div>
        `;
        updateCartSummary();
        return;
    }

    cartItemsDiv.innerHTML = appState.cart.map((item, idx) => `
        <div class="p-4 border-b flex gap-4 last:border-b-0">
            <img src="${buildImageUrl(item.product_image)}" alt="${item.product_name}" class="w-24 h-24 object-cover rounded" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2296%22 height=%2296%22%3E%3Crect fill=%22%23e2e8f0%22 width=%2296%22 height=%2296%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 font-size=%2224%22 fill=%22%2364748b%22 text-anchor=%22middle%22 dominant-baseline=%22middle%22%3E%F0%9F%93%A6%3C/text%3E%3C/svg%3E'">
            <div class="flex-1">
                <h3 class="font-semibold text-lg">${escapeHtml(item.product_name)}</h3>
                <p class="text-gray-600">₹${parseFloat(item.product_price).toFixed(2)} each</p>
                <div class="flex gap-2 mt-2">
                    <button onclick="updateCartQuantity(${idx}, -1)" class="px-2 py-1 bg-gray-300 rounded hover:bg-gray-400">−</button>
                    <span class="px-4 py-1 bg-gray-100 rounded">${item.quantity}</span>
                    <button onclick="updateCartQuantity(${idx}, 1)" class="px-2 py-1 bg-gray-300 rounded hover:bg-gray-400">+</button>
                    <button onclick="removeFromCart(${idx})" class="ml-auto px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600">Remove</button>
                </div>
            </div>
            <p class="font-semibold text-lg">₹${(item.product_price * item.quantity).toFixed(2)}</p>
        </div>
    `).join('');

    updateCartSummary();
}

function updateCartQuantity(index, delta) {
    appState.cart[index].quantity += delta;
    if (appState.cart[index].quantity < 1) {
        appState.cart.splice(index, 1);
    }
    saveStateToLocalStorage();
    updateCartBadge();
    loadCart();
}

function removeFromCart(index) {
    // ========== STRICT ROLE CHECK: Only customers can manage cart ==========
    if (!appState.user || appState.user.role !== 'customer') {
        showToast('Only customers can manage cart', 'error');
        return;
    }

    appState.cart.splice(index, 1);
    saveStateToLocalStorage();
    updateCartBadge();
    loadCart();
}

function updateCartSummary() {
    const subtotal = appState.cart.reduce((total, item) => total + (item.product_price * item.quantity), 0);
    const shipping = subtotal > 500 ? 0 : 50;
    const total = subtotal + shipping;

    document.getElementById('cart-subtotal').textContent = `₹${subtotal.toFixed(2)}`;
    document.getElementById('cart-shipping').textContent = `₹${shipping.toFixed(2)}`;
    document.getElementById('cart-total').textContent = `₹${total.toFixed(2)}`;
}

function proceedToCheckout() {
    // ========== STRICT ROLE CHECK: Only customers can checkout ==========
    if (!appState.user || appState.user.role !== 'customer') {
        showToast('Only customers can access checkout', 'error');
        return;
    }

    if (appState.cart.length === 0) {
        showToast('Your cart is empty', 'warning');
        return;
    }
    navigateTo('#checkout');
}

// ============================================
// Checkout & Orders
// ============================================

async function loadCheckout() {
    // Load saved addresses
    const response = await apiCall('/user/profile');
    if (response && response.user) {
        appState.selectedAddresses = response.user.addresses || [];
    }

    // Render saved addresses
    const addressesDiv = document.getElementById('saved-addresses');
    if (appState.selectedAddresses.length > 0) {
        addressesDiv.innerHTML = `
            <h4 class="font-semibold text-gray-900 mb-3">Select Saved Address</h4>
            ${appState.selectedAddresses.map(addr => `
                <label class="option-card" onclick="selectAddress('${addr.uuid}')">
                    <input type="radio" name="address" value="${addr.uuid}" class="cursor-pointer">
                    <div class="flex-1">
                        <div class="font-semibold">${addr.full_name}</div>
                        <div class="text-sm text-gray-600">${addr.street}, ${addr.city}, ${addr.state} - ${addr.pincode}</div>
                        <div class="text-sm text-gray-600">${addr.phone_number}</div>
                    </div>
                </label>
            `).join('')}
        `;
    }

    updateCheckoutSummary();
}

function selectAddress(addressUuid) {
    appState.selectedAddress = addressUuid;
}

async function handleAddAddress(event) {
    event.preventDefault();

    const addressData = {
        full_name: document.getElementById('addr-name')?.value || '',
        phone_number: document.getElementById('addr-phone')?.value || '',
        street: document.getElementById('addr-street')?.value || '',
        city: document.getElementById('addr-city')?.value || '',
        state: document.getElementById('addr-state')?.value || '',
        pincode: document.getElementById('addr-pincode')?.value || ''
    };

    // Validate
    if (!addressData.full_name || !addressData.phone_number || !addressData.street || !addressData.city || !addressData.state || !addressData.pincode) {
        showToast('Please fill in all address fields', 'warning');
        return;
    }

    const response = await apiCall('/user/address', 'POST', addressData);

    if (response && response.address_uuid) {
        showToast('Address saved successfully!', 'success');
        appState.selectedAddress = response.address_uuid;
        document.getElementById('payment-section').classList.remove('hidden');
        // Clear form
        event.target.reset();
    }
}

function updateCheckoutSummary() {
    const subtotal = appState.cart.reduce((total, item) => total + (item.product_price * item.quantity), 0);
    const shipping = subtotal > 500 ? 0 : 50;
    const total = subtotal + shipping;

    document.getElementById('checkout-summary').innerHTML = `
        ${appState.cart.map(item => `
            <div class="flex justify-between text-sm border-b pb-2 mb-2">
                <span class="text-gray-700">${escapeHtml(item.product_name)} <span class="text-gray-500">x ${item.quantity}</span></span>
                <span class="font-semibold">₹${(item.product_price * item.quantity).toFixed(2)}</span>
            </div>
        `).join('')}
        <div class="space-y-1 mt-3 pt-3 border-t">
            <div class="flex justify-between text-sm">
                <span class="text-gray-600">Subtotal</span>
                <span class="font-semibold">₹${subtotal.toFixed(2)}</span>
            </div>
            <div class="flex justify-between text-sm">
                <span class="text-gray-600">Shipping</span>
                <span class="font-semibold">${shipping === 0 ? 'FREE' : '₹' + shipping.toFixed(2)}</span>
            </div>
        </div>
    `;
    document.getElementById('checkout-total').textContent = `₹${total.toFixed(2)}`;
}

async function handlePayment(event) {
    event.preventDefault();

    // CRITICAL FIX: Role check
    if (!appState.user || appState.user.role !== 'customer') {
        showToast('Only customers can complete payment', 'error');
        return;
    }

    // CRITICAL FIX: Proper address selection validation
    if (!appState.selectedAddress) {
        showToast('Please select or add an address first', 'warning');
        return;
    }

    // Create order
    const checkoutResponse = await apiCall('/user/checkout', 'POST', {
        address_uuid: appState.selectedAddress
    });

    if (!checkoutResponse) return;

    const orderUuid = checkoutResponse.order_uuid;
    appState.currentOrder = orderUuid;

    // Process payment
    const paymentMethod = document.querySelector('input[name="payment_method"]:checked')?.value;
    if (!paymentMethod) {
        showToast('Please select a payment method', 'warning');
        return;
    }

    const paymentResponse = await apiCall('/user/payment', 'POST', {
        order_uuid: orderUuid,
        payment_method: paymentMethod
    });

    if (paymentResponse) {
        showPaymentSuccessNotification(orderUuid);
        appState.cart = [];
        appState.selectedAddress = null;
        saveStateToLocalStorage();
        updateCartBadge();
        setTimeout(() => {
            navigateTo(`#order-tracking/${orderUuid}`);
        }, 2000);
    }
}

async function loadOrderTracking(orderUuid) {
    if (!orderUuid) {
        showToast('Invalid order', 'error');
        navigateTo('#profile');
        return;
    }

    const response = await apiCall(`/user/order/${orderUuid}/track`);

    if (!response) {
        showToast('Failed to load order tracking', 'error');
        navigateTo('#profile');
        return;
    }

    document.getElementById('tracking-order-id').textContent = `Order #${orderUuid.slice(0, 8)}`;

    const timelineDiv = document.getElementById('tracking-timeline');
    const timeline = response.tracking_history || response.timeline || response.tracking || [];

    if (timeline.length === 0) {
        timelineDiv.innerHTML = '<div class="text-center text-gray-500">No tracking information available</div>';
        return;
    }

    timelineDiv.innerHTML = timeline.map((event, idx) => {
        return `
            <div class="timeline-item">
                <div class="timeline-marker">
                    <div class="timeline-icon ${event.status === 'completed' ? 'completed' : 'pending'}">
                        ${event.status === 'completed' ? '✓' : '●'}
                    </div>
                </div>
                <div class="timeline-content">
                    <h3 class="timeline-title">${escapeHtml(event.status || event.title || '')}</h3>
                    <p class="timeline-description">${escapeHtml(event.message || event.description || '')}</p>
                    <p class="timeline-time">${event.timestamp ? new Date(event.timestamp).toLocaleString() : 'N/A'}</p>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================
// User Profile
// ============================================

async function loadProfile() {
    loadProfileWithFallback();
}

// ============================================
// Seller Dashboard
// ============================================

async function loadSellerDashboard() {
    // Load seller categories
    const categoriesResponse = await apiCall('/seller/my-categories');
    if (categoriesResponse) {
        const categories = categoriesResponse.categories || [];
        const approved = categories.filter(c => c.status === 'approved');
        const pending = categories.filter(c => c.status === 'pending');
        const available = categories.filter(c => c.status === 'available');

        document.getElementById('seller-categories-count').textContent = categories.length;
        document.getElementById('seller-pending-count').textContent = pending.length;
        document.getElementById('seller-approved-count').textContent = approved.length;

        // Populate category dropdown with ONLY APPROVED categories for product creation
        const select = document.getElementById('product-category');
        select.innerHTML = '<option value="">Select Category</option>' +
            approved.map(cat => `<option value="${cat.uuid}">${escapeHtml(cat.name)}</option>`).join('');

        // Display category request section
        displayCategoryRequestSection(available, pending);
    }

    // Load seller products
    const productsResponse = await apiCall('/seller/products');
    if (productsResponse) {
        const products = productsResponse.products || [];
        document.getElementById('seller-products-count').textContent = products.length;

        const productsDiv = document.getElementById('seller-products');
        productsDiv.innerHTML = products.map(product => `
            <div class="bg-white rounded-lg shadow p-4">
                <div style="width: 100%; height: 180px; overflow: hidden; border-radius: 8px; margin-bottom: 12px; background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);">
                    <img src="${buildImageUrl(product.primary_image)}" alt="${product.name}" class="w-full h-full object-cover" onerror="this.style.display='none'">
                </div>
                <h3 class="font-semibold text-lg">${escapeHtml(product.name)}</h3>
                <p class="text-gray-600 text-sm mb-2">${escapeHtml(product.description)}</p>
                <p class="text-blue-600 font-bold text-lg">₹${parseFloat(product.price).toFixed(2)}</p>
                <p class="text-sm text-gray-600">Stock: ${product.stock}</p>
            </div>
        `).join('');
    }
}

function displayCategoryRequestSection(available, pending) {
    // Find or create the category request section
    let categorySection = document.getElementById('seller-category-requests');
    if (!categorySection) {
        const form = document.getElementById('seller-product-form');
        if (form) {
            categorySection = document.createElement('div');
            categorySection.id = 'seller-category-requests';
            form.parentElement.insertBefore(categorySection, form);
        }
    }

    if (categorySection) {
        let html = '<div class="bg-blue-50 rounded-lg p-6 mb-8 border-l-4 border-blue-500">';
        html += '<h3 class="text-lg font-bold text-gray-900 mb-4">📋 Category Management</h3>';

        if (pending.length > 0) {
            html += '<div class="mb-4"><h4 class="font-semibold text-orange-600 mb-2">⏳ Pending Approval:</h4>';
            html += '<div class="flex flex-wrap gap-2">';
            pending.forEach(cat => {
                html += `<span class="px-3 py-1 bg-orange-200 text-orange-800 rounded-full text-sm">${escapeHtml(cat.name)}</span>`;
            });
            html += '</div></div>';
        }

        if (available.length > 0) {
            html += '<div><h4 class="font-semibold text-green-600 mb-2">✨ Available Categories:</h4>';
            html += '<div class="space-y-2">';
            available.forEach(cat => {
                html += `
                    <div class="flex justify-between items-center bg-white p-3 rounded border border-gray-200">
                        <span class="font-medium">${escapeHtml(cat.name)}</span>
                        <button type="button" onclick="requestCategoryApproval('${cat.uuid}', '${cat.name}')" class="px-3 py-1 bg-green-500 text-white rounded text-sm hover:bg-green-600">Request Approval</button>
                    </div>
                `;
            });
            html += '</div></div>';
        } else {
            html += '<p class="text-gray-700">No new categories available. Wait for admin to create more categories.</p>';
        }

        html += '</div>';
        categorySection.innerHTML = html;
    }
}

async function requestCategoryApproval(categoryUuid, categoryName) {
    const response = await apiCall('/seller/category-request', 'POST', {
        category_uuid: categoryUuid
    });
    
    if (response) {
        showToast(`Request submitted for "${categoryName}"!`, 'success');
        loadSellerDashboard();
    }
}

async function handleAddProduct(event) {
    event.preventDefault();

    const formData = new FormData();
    formData.append('name', document.getElementById('product-name').value);
    formData.append('description', document.getElementById('product-description').value);
    formData.append('price', document.getElementById('product-price').value);
    formData.append('stock', document.getElementById('product-stock').value);
    formData.append('category_uuid', document.getElementById('product-category').value);

    // Handle images
    const imageFiles = document.getElementById('product-images').files;
    for (let i = 0; i < imageFiles.length; i++) {
        formData.append('images', imageFiles[i]);
    }

    // Handle specifications
    const specs = [];
    document.querySelectorAll('.spec-row').forEach(row => {
        const key = row.querySelector('.spec-key').value;
        const value = row.querySelector('.spec-value').value;
        if (key && value) {
            specs.push({ key, value });
        }
    });
    formData.append('specifications', JSON.stringify(specs));

    const response = await apiCall('/seller/product', 'POST', formData, false);

    if (response) {
        showToast('Product added successfully!', 'success');
        document.getElementById('seller-product-form').reset();
        document.querySelectorAll('.spec-row:not(:first-child)').forEach(el => el.remove());
        loadSellerDashboard();
    }
}

function addSpec() {
    const container = document.getElementById('specs-container');
    const newRow = document.createElement('div');
    newRow.className = 'spec-row flex gap-2 mb-2';
    newRow.innerHTML = `
        <input type="text" placeholder="Key (e.g., RAM)" class="flex-1 spec-key px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
        <input type="text" placeholder="Value (e.g., 16GB)" class="flex-1 spec-value px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
        <button type="button" onclick="removeSpec(this)" class="px-3 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition">Remove</button>
    `;
    container.appendChild(newRow);
}

function removeSpec(button) {
    button.parentElement.remove();
}

// ============================================
// Admin Dashboard
// ============================================

async function loadAdminDashboard() {
    // Load category requests
    const requestsResponse = await apiCall('/admin/category-requests');
    if (requestsResponse) {
        const requests = requestsResponse.requests || [];
        document.getElementById('admin-pending-requests').textContent = requests.length;
        displayCategoryRequests(requests);
    }

    // Load sellers
    const sellersResponse = await apiCall('/admin/sellers');
    if (sellersResponse) {
        const sellers = sellersResponse.sellers || [];
        document.getElementById('admin-sellers-count').textContent = sellers.length;
        document.getElementById('admin-active-sellers').textContent = sellers.filter(s => s.is_active).length;
        displaySellers(sellers);
    }
    
    // Load orders
    const ordersResponse = await apiCall('/admin/orders');
    if (ordersResponse) {
        const orders = ordersResponse.orders || [];
        displayAdminOrders(orders);
    }
}

function displayCategoryRequests(requests) {
    const requestsList = document.getElementById('admin-requests-list');
    
    if (requests.length === 0) {
        requestsList.innerHTML = '<p class="text-gray-500">No pending requests</p>';
        return;
    }

    requestsList.innerHTML = requests.map(req => `
        <div class="bg-gray-50 p-4 rounded-lg flex justify-between items-center">
            <div>
                <h3 class="font-semibold">${req.seller_name || 'Seller'}</h3>
                <p class="text-sm text-gray-600">Category: ${req.category_name || 'Unknown'}</p>
                <p class="text-sm text-gray-500">Requested: ${req.requested_at}</p>
            </div>
            <div class="flex gap-2">
                <button onclick="approveCategoryRequest('${req.request_uuid}')" class="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 transition font-semibold">✓ Approve</button>
                <button onclick="declineCategoryRequest('${req.request_uuid}')" class="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 transition font-semibold">✕ Decline</button>
            </div>
        </div>
    `).join('');
}

async function approveCategoryRequest(requestUuid) {
    const response = await apiCall(`/admin/category-request/${requestUuid}/approve`, 'PUT', {});
    if (response) {
        showToast('Request approved!', 'success');
        loadAdminDashboard();
    }
}

async function declineCategoryRequest(requestUuid) {
    if (confirm('Are you sure you want to decline this request?')) {
        const response = await apiCall(`/admin/category-request/${requestUuid}/decline`, 'PUT', {});
        if (response) {
            showToast('Request declined!', 'warning');
            loadAdminDashboard();
        }
    }
}

async function handleCreateCategory(event) {
    event.preventDefault();
    
    const name = document.getElementById('category-name').value;
    const description = document.getElementById('category-description').value;
    
    if (!name.trim()) {
        showToast('Category name is required', 'error');
        return;
    }
    
    const response = await apiCall('/admin/category', 'POST', {
        name: name.trim(),
        description: description.trim()
    });
    
    if (response) {
        showToast('Category created successfully!', 'success');
        document.getElementById('category-name').value = '';
        document.getElementById('category-description').value = '';
        loadAdminDashboard();
    }
}

function displaySellers(sellers) {
    const sellersList = document.getElementById('admin-sellers-list');

    if (sellers.length === 0) {
        sellersList.innerHTML = '<p class="text-gray-500">No sellers</p>';
        return;
    }

    sellersList.innerHTML = sellers.map(seller => `
        <div class="bg-gray-50 p-4 rounded-lg flex justify-between items-center">
            <div>
                <h3 class="font-semibold">${seller.username}</h3>
                <p class="text-sm text-gray-600">${seller.email}</p>
                <span class="badge ${seller.is_active ? 'badge-success' : 'badge-warning'}">
                    ${seller.is_active ? 'Active' : 'Inactive'}
                </span>
            </div>
            <button onclick="toggleSellerStatus('${seller.uuid}')" class="px-4 py-2 ${seller.is_active ? 'bg-red-500 hover:bg-red-600' : 'bg-green-500 hover:bg-green-600'} text-white rounded">
                ${seller.is_active ? 'Deactivate' : 'Activate'}
            </button>
        </div>
    `).join('');
}

async function toggleSellerStatus(sellerUuid) {
    const response = await apiCall(`/admin/seller/${sellerUuid}/status`, 'PUT', {});
    if (response) {
        showToast('Seller status updated!', 'success');
        loadAdminDashboard();
    }
}

function displayAdminOrders(orders) {
    const ordersList = document.getElementById('admin-orders-list');
    
    if (!ordersList) return;
    
    document.getElementById('admin-orders-count').textContent = orders.length;
    
    if (orders.length === 0) {
        ordersList.innerHTML = '<p class="text-gray-500">No orders yet</p>';
        return;
    }

    ordersList.innerHTML = orders.map(order => `
        <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
            <div class="flex justify-between items-start mb-2">
                <div>
                    <p class="font-semibold text-gray-900">Order #${order.order_uuid.slice(0, 8)}</p>
                    <p class="text-sm text-gray-600">Customer: ${order.customer_username}</p>
                    <p class="text-sm text-gray-600">${order.created_at}</p>
                </div>
                <span class="px-3 py-1 rounded-full text-sm font-semibold ${
                    order.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                    order.status === 'processing' ? 'bg-blue-100 text-blue-800' :
                    order.status === 'shipped' ? 'bg-purple-100 text-purple-800' :
                    order.status === 'delivered' ? 'bg-green-100 text-green-800' :
                    'bg-gray-100 text-gray-800'
                }">
                    ${order.status.toUpperCase()}
                </span>
            </div>
            <div class="text-sm text-gray-600 mb-3">
                <p>${order.item_count} item(s) - Total: ₹${order.total_amount}</p>
                <p class="text-xs text-gray-500 mt-1">${order.items.map(item => `${item.product_name} (x${item.quantity})`).join(', ')}</p>
            </div>
            <div class="flex gap-2">
                <button onclick="navigateTo('#order-tracking/${order.order_uuid}')" class="text-blue-500 hover:text-blue-700 text-sm font-semibold">View Tracking</button>
                <select onchange="updateOrderStatus('${order.order_uuid}', this.value)" class="text-sm px-2 py-1 border rounded">
                    <option value="">Change Status...</option>
                    <option value="pending">Pending</option>
                    <option value="processing">Processing</option>
                    <option value="shipped">Shipped</option>
                    <option value="delivered">Delivered</option>
                </select>
            </div>
        </div>
    `).join('');
}

async function updateOrderStatus(orderUuid, newStatus) {
    if (!newStatus) return;
    
    const response = await apiCall(`/admin/order/${orderUuid}/status`, 'PUT', {
        status: newStatus,
        message: `Order status updated to ${newStatus.toUpperCase()}`
    });
    
    if (response) {
        showToast('Order status updated!', 'success');
        loadAdminDashboard();
    }
}

function switchAdminTab(tab) {
    // Hide all tabs
    document.getElementById('admin-category-tab-content').classList.add('hidden');
    document.getElementById('admin-requests-tab-content').classList.add('hidden');
    document.getElementById('admin-sellers-tab-content').classList.add('hidden');
    document.getElementById('admin-orders-tab-content').classList.add('hidden');

    // Reset button styles
    document.getElementById('admin-category-tab').className = 'px-6 py-2 bg-gray-300 text-gray-900 rounded-lg font-semibold';
    document.getElementById('admin-requests-tab').className = 'px-6 py-2 bg-gray-300 text-gray-900 rounded-lg font-semibold';
    document.getElementById('admin-sellers-tab').className = 'px-6 py-2 bg-gray-300 text-gray-900 rounded-lg font-semibold';
    document.getElementById('admin-orders-tab').className = 'px-6 py-2 bg-gray-300 text-gray-900 rounded-lg font-semibold';

    // Show selected tab
    switch (tab) {
        case 'category':
            document.getElementById('admin-category-tab-content').classList.remove('hidden');
            document.getElementById('admin-category-tab').className = 'px-6 py-2 bg-blue-500 text-white rounded-lg font-semibold';
            break;
        case 'requests':
            document.getElementById('admin-requests-tab-content').classList.remove('hidden');
            document.getElementById('admin-requests-tab').className = 'px-6 py-2 bg-blue-500 text-white rounded-lg font-semibold';
            break;
        case 'sellers':
            document.getElementById('admin-sellers-tab-content').classList.remove('hidden');
            document.getElementById('admin-sellers-tab').className = 'px-6 py-2 bg-blue-500 text-white rounded-lg font-semibold';
            break;
        case 'orders':
            document.getElementById('admin-orders-tab-content').classList.remove('hidden');
            document.getElementById('admin-orders-tab').className = 'px-6 py-2 bg-blue-500 text-white rounded-lg font-semibold';
            break;
    }
}

// ============================================
// Utility Functions
// ============================================

function switchAuthTab(tab) {
    if (tab === 'login') {
        document.getElementById('login-form').style.display = 'block';
        document.getElementById('signup-form').style.display = 'none';
        document.getElementById('login-tab').className = 'flex-1 py-2 px-4 bg-blue-500 text-white rounded-lg font-semibold';
        document.getElementById('signup-tab').className = 'flex-1 py-2 px-4 bg-gray-200 text-gray-900 rounded-lg font-semibold';
    } else {
        document.getElementById('login-form').style.display = 'none';
        document.getElementById('signup-form').style.display = 'block';
        document.getElementById('login-tab').className = 'flex-1 py-2 px-4 bg-gray-200 text-gray-900 rounded-lg font-semibold';
        document.getElementById('signup-tab').className = 'flex-1 py-2 px-4 bg-blue-500 text-white rounded-lg font-semibold';
    }
}

function toggleMobileMenu() {
    const navMenu = document.querySelector('nav');
    navMenu.classList.toggle('mobile-open');
}

// ============================================
// IMAGE SLIDER - Product Detail Page
// ============================================

let currentSlideIndex = 0;
let totalSlides = 0;

function initializeImageSlider(images) {
    totalSlides = images.length;
    if (totalSlides === 0) return;
    
    showSlide(0);
    
    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft') previousSlide();
        if (e.key === 'ArrowRight') nextSlide();
    });
}

function showSlide(index) {
    if (totalSlides === 0) return;
    
    currentSlideIndex = (index + totalSlides) % totalSlides;
    const slider = document.getElementById('product-slider');
    const dots = document.querySelectorAll('.slider-dot');
    
    if (slider) {
        slider.style.transform = `translateX(-${currentSlideIndex * 100}%)`;
    }
    
    dots.forEach((dot, i) => {
        dot.classList.toggle('active', i === currentSlideIndex);
    });
}

function nextSlide() {
    showSlide(currentSlideIndex + 1);
}

function previousSlide() {
    showSlide(currentSlideIndex - 1);
}

function goToSlide(index) {
    showSlide(index);
}

// ============================================
// DOMINANT COLOR EXTRACTION - Dynamic Theme
// ============================================

async function extractDominantColor(imageUrl) {
    return new Promise((resolve) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
            const canvas = document.createElement('canvas');
            canvas.width = 1;
            canvas.height = 1;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, 1, 1);
            
            const imageData = ctx.getImageData(0, 0, 1, 1);
            const data = imageData.data;
            
            const rgb = `rgb(${data[0]}, ${data[1]}, ${data[2]})`;
            const hex = '#' + [data[0], data[1], data[2]].map(x => {
                const hex = x.toString(16);
                return hex.length === 1 ? '0' + hex : hex;
            }).join('');
            
            resolve(hex);
        };
        img.onerror = () => resolve('#2563eb');
        img.src = imageUrl;
    });
}

async function applyDynamicTheme(imageUrl) {
    try {
        const dominantColor = await extractDominantColor(imageUrl);
        document.documentElement.style.setProperty('--theme-color', dominantColor);
    } catch (e) {
        console.log('Color extraction failed, using default theme');
    }
}

// ============================================
// ORDER NOTIFICATION POPUP
// ============================================

function showOrderNotification(order) {
    const modal = document.createElement('div');
    modal.className = 'modal show';
    modal.innerHTML = `
        <div class="modal-content">
            <div style="font-size: 48px; margin-bottom: 16px;">
                ${order.status === 'pending' ? '⏳' :
                  order.status === 'processing' ? '📦' :
                  order.status === 'shipped' ? '🚚' :
                  order.status === 'delivered' ? '✅' : '❓'}
            </div>
            <h2 style="font-size: 24px; font-weight: bold; margin-bottom: 12px;">Order ${order.status.toUpperCase()}!</h2>
            <p style="color: #666; margin-bottom: 8px;">Order #${order.order_uuid.slice(0, 8)}</p>
            <p style="color: #666; margin-bottom: 16px; font-size: 14px;">₹${order.total_amount}</p>
            <p style="color: #999; margin-bottom: 24px; font-size: 13px;">${order.item_count} items • ${new Date(order.created_at).toLocaleDateString()}</p>
            <button onclick="this.parentElement.parentElement.remove()" class="btn btn-primary" style="width: 100%;">View Details</button>
        </div>
    `;
    
    modal.style.cssText = `
        display: flex;
        align-items: center;
        justify-content: center;
        animation: fadeIn 0.3s ease;
    `;
    
    document.body.appendChild(modal);
    
    setTimeout(() => {
        modal.remove();
    }, 5000);
}

// ============================================
// IMPROVED PROFILE LOADING WITH ERROR HANDLING
// ============================================

async function loadProfileWithFallback() {
    try {
        const role = appState.user?.role;

        // Load profile info - this endpoint is generic
        const response = await apiCall('/user/profile');

        if (response && response.user) {
            const user = response.user;
            const usernameEl = document.getElementById('profile-username');
            const emailEl = document.getElementById('profile-email');
            const roleEl = document.getElementById('profile-role');
            
            if (usernameEl) usernameEl.textContent = user.username || user.email;
            if (emailEl) emailEl.textContent = user.email;
            if (roleEl) roleEl.textContent = user.role || 'Unknown';
        }

        // ========== CRITICAL FIX: ROLE-BASED API CALLS ==========
        // Only load customer-specific data if user is a customer
        if (role === 'customer') {
            // Load orders
            const ordersDiv = document.getElementById('profile-orders');
            if (ordersDiv) {
                const ordersResponse = await apiCall('/user/orders');
                
                if (ordersResponse && ordersResponse.orders && ordersResponse.orders.length > 0) {
                    ordersDiv.innerHTML = ordersResponse.orders.map(order => `
                        <div class="bg-white p-4 rounded-lg border-l-4 border-blue-500 shadow-sm hover:shadow-md transition">
                            <div class="flex justify-between items-start mb-2">
                                <div class="flex-1">
                                    <p class="font-semibold text-gray-900">Order #${order.order_uuid.slice(0, 8)}</p>
                                    <p class="text-xs text-gray-500">${order.created_at}</p>
                                </div>
                                <span class="px-3 py-1 rounded-full text-xs font-semibold ${
                                    order.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                                    order.status === 'processing' ? 'bg-blue-100 text-blue-800' :
                                    order.status === 'shipped' ? 'bg-purple-100 text-purple-800' :
                                    order.status === 'delivered' ? 'bg-green-100 text-green-800' :
                                    'bg-gray-100 text-gray-800'
                                }">
                                    ${order.status.toUpperCase()}
                                </span>
                            </div>
                            <p class="text-sm text-gray-700 mb-3">₹${order.total_amount} • ${order.item_count} item(s)</p>
                            <button onclick="navigateTo('#order-tracking/${order.order_uuid}')" class="text-blue-600 hover:text-blue-800 text-sm font-semibold transition">
                                Track Order →
                            </button>
                        </div>
                    `).join('');
                } else {
                    ordersDiv.innerHTML = '<p class="text-gray-500 text-center py-8">📦 No orders yet. Start shopping!</p>';
                }
            }

            // Load addresses
            const addressesDiv = document.getElementById('profile-addresses');
            if (response && response.user && response.user.addresses && addressesDiv) {
                if (response.user.addresses.length > 0) {
                    addressesDiv.innerHTML = response.user.addresses.map(addr => `
                        <div class="bg-blue-50 p-3 rounded-lg text-sm border border-blue-200">
                            <p class="font-semibold text-gray-900">${escapeHtml(addr.full_name)}</p>
                            <p class="text-gray-600 text-xs">${escapeHtml(addr.street)}</p>
                            <p class="text-gray-600 text-xs">${escapeHtml(addr.city)}, ${escapeHtml(addr.state)} - ${escapeHtml(addr.pincode)}</p>
                            <p class="text-gray-700 text-xs mt-1">📞 ${escapeHtml(addr.phone_number)}</p>
                        </div>
                    `).join('');
                } else {
                    addressesDiv.innerHTML = '<p class="text-gray-500 text-sm text-center">No addresses saved yet</p>';
                }
            }
        } else if (role === 'seller' || role === 'admin') {
            // For non-customers, hide the customer-specific sections
            const ordersDiv = document.getElementById('profile-orders');
            const addressesDiv = document.getElementById('profile-addresses');
            
            if (ordersDiv) ordersDiv.style.display = 'none';
            if (addressesDiv) addressesDiv.style.display = 'none';
        }
    } catch (error) {
        console.error('Profile loading error:', error);
        showToast('Unable to load profile. Please refresh.', 'error');
    }
}

// ============================================
// PAYMENT SUCCESS NOTIFICATION
// ============================================

function showPaymentSuccessNotification(order) {
    const modal = document.createElement('div');
    modal.className = 'modal show';
    modal.innerHTML = `
        <div class="modal-content" style="text-align: center;">
            <div style="font-size: 64px; margin-bottom: 20px; animation: bounce 0.6s;">✅</div>
            <h2 style="font-size: 28px; font-weight: bold; margin-bottom: 12px; color: #16a34a;">Payment Successful!</h2>
            <p style="color: #666; margin-bottom: 8px;">Your order has been placed successfully.</p>
            <p style="color: #999; margin-bottom: 20px; font-size: 14px;">OrderID: ${order}</p>
            <div style="background: #f0fdf4; padding: 12px; border-radius: 8px; margin-bottom: 20px;">
                <p style="color: #15803d; font-size: 13px;">✓ Order confirmation sent to your email</p>
            </div>
            <button onclick="navigateTo('#profile'); this.parentElement.parentElement.remove();" class="btn btn-primary" style="width: 100%;">View My Orders</button>
        </div>
    `;
    
    document.body.appendChild(modal);
}

// Initialize profile loading
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('profile-orders')) {
        loadProfileWithFallback();
    }
});
