# 🚀 QUICK REFERENCE - POST-FIX CODE STANDARDS

## Critical Functions Reference

### 1. API Calls - ALWAYS USE THIS
```javascript
const response = await apiCall('/endpoint', 'POST', data);

if (!response) {
    // Error already handled, toast shown
    return;
}

// Use response safely
console.log(response);
```

**Key Features:**
- ✅ Automatic token handling
- ✅ Prevents double-submit
- ✅ Safe JSON parsing
- ✅ Comprehensive error handling
- ✅ HTTP status code differentiation

**DO NOT:**
- ❌ Use `fetch()` directly
- ❌ Manually add Authorization header
- ❌ Try-catch around apiCall without checking response

---

### 2. XSS Prevention - ALWAYS ESCAPE USER DATA
```javascript
// GOOD - Escaped
const html = `<p>${escapeHtml(userInput)}</p>`;

// BAD - XSS Vulnerability!
const html = `<p>${userInput}</p>`;
```

**Use escapeHtml() for:**
- Product names/descriptions
- User usernames/emails (in display)
- Address information
- Order details
- Any user-generated content

**Maps:**
```
& → &amp;
< → &lt;
> → &gt;
" → &quot;
' → &#039;
```

---

### 3. Role-Based Access Control
```javascript
function myAction() {
    // Check role FIRST thing
    if (!appState.user || appState.user.role !== 'customer') {
        showToast('Only customers can do this', 'error');
        return;
    }
    
    // Then proceed
    // ...
}
```

**Roles:**
- `'customer'` - Can browse, buy, track orders
- `'seller'` - Can manage products, categories
- `'admin'` - Can manage orders, sellers, categories
- `null` - Unauthenticated user

**Common Checks:**
```javascript
// Customer only (shopping, payments)
if (role !== 'customer') { showToast(...); return; }

// Authenticated only
if (!appState.token) { navigateTo('#login'); return; }

// Not unauthenticated
if (appState.user) { showToast(...); return; }
```

---

### 4. DOM Element Access - USE OPTIONAL CHAINING
```javascript
// GOOD - Safe, won't crash if element missing
const value = document.getElementById('field')?.value;
const text = document.querySelector('.item')?.textContent;

// BAD - Will crash if element not found
const value = document.getElementById('field').value;
```

**Pattern:**
```javascript
// Always check
const element = document.getElementById('id');
if (element) {
    // Safely use element
}

// OR use optional chaining
const text = document.getElementById('id')?.textContent;
```

---

### 5. State Management - USE appState
```javascript
// Update state
appState.user = response.user;
appState.token = response.token;
appState.cart = []; // Reset cart after order

// Always persist
saveStateToLocalStorage();

// Update UI
updateUIBasedOnAuth();
updateCartBadge();
```

**NEVER:**
- ❌ Update global variables outside appState
- ❌ Forget to call saveStateToLocalStorage()
- ❌ Call logout() from apiCall (causes recursion!)

---

### 6. Error Messages - SHOW HELPFUL TOASTS
```javascript
// GOOD - Specific and actionable
showToast('Please select a payment method', 'warning');
showToast('Only customers can complete payment', 'error');
showToast('Cart updated successfully', 'success');

// BAD - Vague
showToast('Error');
showToast('Failed');
```

**Toast Types:**
- `'success'` ✓ - Green checkmark
- `'error'` ✕ - Red X
- `'warning'` ⚠ - Orange warning
- `'info'` ℹ - Blue info

---

### 7. Forms - ALWAYS VALIDATE FIRST
```javascript
// Check all required fields
if (!email || !password) {
    showToast('Email and password are required', 'warning');
    return;
}

// Validate format
const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
if (!emailRegex.test(email)) {
    showToast('Invalid email format', 'error');
    return;
}

// Then submit
const response = await apiCall('/endpoint', 'POST', { email, password });
```

---

### 8. Null/Undefined Safety
```javascript
// GOOD - Safe defaults
const stock = product.stock || 0;
const name = product.name || 'Unknown Product';
const role = appState.user?.role || 'guest';

// Process safely
if (stock > 0) { /* show buy button */ }

// BAD - Could crash
if (product.stock > 0) { /* CRASH if undefined */ }
```

---

### 9. Array Operations - SAFE ITERATION
```javascript
// GOOD - Safe iteration
items.forEach(item => {
    console.log(item.id);
});

// GOOD - Array methods
const total = items.reduce((sum, item) => sum + item.price, 0);

// BAD - Assumes items exist
items[0].id;  // Could crash if empty
```

---

## Common Patterns

### Authentication Flow
```javascript
1. User fills login form
2. handleLogin() validates empty fields
3. apiCall() sends to backend
4. Response received → appState.token = response.access_token
5. saveStateToLocalStorage()
6. updateUIBasedOnAuth() → renders navbar
7. navigateTo('#home')
```

### Product Purchase Flow
```javascript
1. User browses products (@customer, @unauthenticated)
2. Clicks "Add to Cart" → addToCart()
3. addToCart() checks: if (!customer) return ✓
4. Updates appState.cart
5. saveStateToLocalStorage()
6. updateCartBadge()
7. User proceeds to #checkout
```

### Admin Order Management Flow
```javascript
1. Admin logs in (@admin only)
2. Goes to #admin-dash
3. loadAdminDashboard() calls apiCall('/admin/orders')
4. displayAdminOrders() shows order list (with escaping!)
5. Admin clicks "Update Status"
6. updateOrderStatus() calls apiCall()
7. Success → reload dashboard
```

---

## File Locations Map
```
frontend/
├── static/
│   ├── js/
│   │   └── main.js          ← YOU ARE HERE (UPDATED)
│   ├── css/
│   │   └── styles.css
│   ├── uploads/
│   │   └── products/
│   └── images/
├── templates/
│   ├── base.html
│   ├── home.html
│   ├── products.html
│   ├── cart.html
│   ├── checkout.html
│   └── profile.html
└── index.html

backend/
├── app.py
├── config.py
├── requirements.txt
├── models.py              ← Database schemas
├── auth/
├── user/
├── admin/
└── seller/
```

---

## Next Steps for Deployment

### Before Going Live
- [ ] Run full testing checklist (see TESTING_CHECKLIST.md)
- [ ] Clear backend log files (if any)
- [ ] Verify all API endpoints respond
- [ ] Test with real product images
- [ ] Check email notifications work
- [ ] Verify payment gateway (if integrated)

### After Deployment
- [ ] Monitor browser console for errors
- [ ] Check user feedback on error messages
- [ ] Monitor API response times
- [ ] Monitor session timeout behavior

---

## Debugging Tips

### Check appState
```javascript
// In browser console
console.log(appState);
console.log('User:', appState.user);
console.log('Token:', appState.token?.substring(0, 10) + '...');
console.log('Cart:', appState.cart);
```

### Check localStorage
```javascript
# In browser console
localStorage.getItem('user')           # Parse to see user
localStorage.getItem('authToken')      # Check token
localStorage.getItem('cart')           # Check cart

# Clear everything
localStorage.clear()
```

### Check API Calls
```javascript
# In browser DevTools → Network tab
1. Look for Failed or Red requests
2. Click request → Response tab
3. Check error message from backend
4. Check status code (401, 404, 500, etc.)
```

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| "Session expired" | Token in localStorage is invalid or expired | Login again |
| "Only customers can..." | Wrong user role for action | Login with different role |
| "Failed to load" | Backend API error | Check Network tab for actual error |
| "Network error" | Browser offline | Check internet connection |
| "Invalid request" | Missing required fields in form | Fill out all fields |

---

## Code Review Checklist

When adding new features:
- [ ] Add role check first (if needed)
- [ ] Validate all form inputs
- [ ] Escape all user data in HTML
- [ ] Use optional chaining for DOM access
- [ ] Use apiCall() not fetch()
- [ ] Call saveStateToLocalStorage() after state change
- [ ] Show appropriate toast message
- [ ] Test null/undefined edge cases
- [ ] Test with DevTools offline
- [ ] No console errors or warnings

---

## Support & Troubleshooting

### Issue: Element not found error in console
**Fix:** Use optional chaining `?.value` or check if element exists

### Issue: Cart not persisting after refresh
**Fix:** Ensure saveStateToLocalStorage() is called

### Issue: Token not being sent in requests
**Fix:** Ensure appState.token is set after login

### Issue: Toast not showing
**Fix:** Ensure `<div id="toast-container">` exists in HTML

### Issue: XSS vulnerability suspected
**Fix:** Search code for `\${userInput}` without escapeHtml()

---

## Key Takeaways

1. **ALWAYS validate input** before using it
2. **ALWAYS escape output** when displaying user data
3. **ALWAYS check role** before sensitive operations
4. **ALWAYS use apiCall()** for backend communication
5. **ALWAYS save state** after updates
6. **NEVER use fetch()** directly
7. **NEVER call logout()** from error handlers
8. **NEVER trust user input** without escaping
9. **NEVER forget optional chaining** on DOM access
10. **ALWAYS show user feedback** with toasts

---

**Version:** 1.0 (Post-Critical-Fixes)
**Last Updated:** 2024
**Status:** Production Ready ✅
