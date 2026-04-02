# 🧪 COMPREHENSIVE TESTING CHECKLIST - E-Commerce Frontend

## Pre-Testing Setup
- [ ] Clear browser cache and localStorage: `localStorage.clear()` in console
- [ ] Open browser DevTools (F12)
- [ ] Go to Console tab - watch for any errors
- [ ] Test on Chrome, Firefox, Safari if possible

---

## 🔐 AUTHENTICATION & SESSION MANAGEMENT

### Login Functionality
- [ ] Login with valid credentials
  - ✅ Should show success toast "Login successful!"
  - ✅ Should redirect to #home
  - ✅ Should update navbar (show logout, profile)

- [ ] Login with invalid email/password
  - ✅ Should show error toast with backend message
  - ✅ Should NOT redirect
  - ✅ Should keep username in form

- [ ] Login with missing fields
  - ✅ Should show warning "Email and password are required"
  - ✅ Should NOT make API call

### Signup Functionality
- [ ] Signup as customer
  - ✅ Should show success "Account created! Please login."
  - ✅ Should switch to login tab
  - ✅ Should pre-fill email

- [ ] Signup with missing fields
  - ✅ Should show warning "All fields are required"

- [ ] Signup with duplicate email
  - ✅ Should show error from backend

### Session Expiration
- [ ] Manually expire token: Edit localStorage, remove token
- [ ] Try any API call
  - ✅ Should show "Session expired. Please login again."
  - ✅ Should force redirect to #login
  - ✅ Should clear all user data

### Logout
- [ ] Click logout button
  - ✅ Should clear all state variables
  - ✅ Should clear localStorage
  - ✅ Should hide cart icon
  - ✅ Should show "Logged out successfully"
  - ✅ Should redirect to #home

---

## 🛍️ CUSTOMER - PRODUCT BROWSING

### Products List
- [ ] Load products page
  - ✅ Should display products grid
  - ✅ Images should load (or show fallback 📦)
  - ✅ Prices should display correctly

- [ ] Search products
  - ✅ Filter by product name
  - ✅ Filter by description
  - ✅ Case-insensitive search

- [ ] Product not found API
  - ✅ Should show "No products available" message

### Product Detail Page
- [ ] Click on any product
  - ✅ Should load product details
  - ✅ Should show all images
  - ✅ Should show specifications

- [ ] Invalid product UUID
  - ✅ Should show error "Failed to load product"
  - ✅ Should redirect to #products

- [ ] Click image thumbnail
  - ✅ Should swap primary image

### Add to Cart (Customer)
- [ ] Login as CUSTOMER
- [ ] Go to product detail
  - ✅ Should see "Add to Cart" button visible

- [ ] Add product to cart
  - ✅ Should show "Added to cart!" success
  - ✅ Cart badge should increment
  - ✅ appState.cart should update in console
  - ✅ localStorage should persist cart

- [ ] Add same product again
  - ✅ Should increase quantity, not duplicate entry

- [ ] Add product with custom quantity
  - ✅ Cart summary should calculate correct total

### Seller/Admin Cannot Buy
- [ ] Login as SELLER
- [ ] Go to product detail
  - ✅ Should NOT see "Add to Cart" button
  - ✅ Should NOT be able to call addToCart()

- [ ] Login as ADMIN
- [ ] Repeat above
  - ✅ Same restrictions apply

---

## 🛒 CUSTOMER - CART MANAGEMENT

### View Cart
- [ ] Click cart icon
  - ✅ Should show all items with images
  - ✅ Prices and quantities correct
  - ✅ Individual subtotals correct

- [ ] Empty cart
  - ✅ Should show "Your cart is empty"
  - ✅ Should show "Continue Shopping" button

### Update Cart Quantities
- [ ] Click "+" button
  - ✅ Quantity increases
  - ✅ Total recalculates
  - ✅ localStorage updates

- [ ] Click "-" button
  - ✅ Quantity decreases
  - ✅ Total recalculates

- [ ] Decrease to 0
  - ✅ Item should be removed

### Remove Items
- [ ] Click "Remove" button
  - ✅ Item disappears
  - ✅ Cart badge updates
  - ✅ Total recalculates

- [ ] Try remove as SELLER
  - ✅ Should show error "Only customers can manage cart"

### Cart Summary
- [ ] Subtotal and shipping calculated correctly
  - ✅ Subtotal > ₹500 = FREE shipping
  - ✅ Subtotal ≤ ₹500 = ₹50 shipping

---

## 💳 CUSTOMER - CHECKOUT PROCESS

### Proceed to Checkout
- [ ] Click "Proceed to Checkout" button
  - ✅ Should redirect to #checkout
  - ✅ Should load saved addresses

- [ ] Try checkout with empty cart
  - ✅ Should show "Your cart is empty" warning

- [ ] Try checkout as non-customer
  - ✅ Should show error and redirect

### Address Management
- [ ] View saved addresses
  - ✅ Should display all saved addresses
  - ✅ First address selected by default

- [ ] Select different address
  - ✅ Radio button should check
  - ✅ `appState.selectedAddress` should update

- [ ] Add new address with all fields
  - ✅ Should save successfully
  - ✅ Should show "Address saved successfully!"
  - ✅ Should be auto-selected

- [ ] Add address with missing fields
  - ✅ Should show "Please fill in all address fields"

- [ ] Address form should clear after save
  - ✅ All fields should be empty

### Payment
- [ ] Select payment method
  - ✅ Radio button should check

- [ ] No payment method selected
  - ✅ Should show "Please select a payment method"

- [ ] No address selected
  - ✅ Should show "Please select or add an address first"

- [ ] Complete payment
  - ✅ Should show success notification
  - ✅ Cart should clear
  - ✅ Should redirect to order tracking

---

## 📦 CUSTOMER - ORDER TRACKING

### View Order Tracking
- [ ] After payment, should see order tracking page
  - ✅ Should show order ID
  - ✅ Should show timeline

- [ ] Timeline should display
  - ✅ All events shown
  - ✅ Completed events show ✓
  - ✅ Pending events show ●
  - ✅ Timestamps formatted correctly

- [ ] Invalid order UUID
  - ✅ Should show error
  - ✅ Should redirect to #profile

### Profile Orders List
- [ ] Go to profile page
  - ✅ Should show "My Orders" section
  - ✅ Should list all orders with status badges

- [ ] Click "Track Order"
  - ✅ Should navigate to order tracking page

- [ ] No orders yet
  - ✅ Should show "📦 No orders yet. Start shopping!"

---

## 👤 PROFILE MANAGEMENT

### Customer Profile
- [ ] Login as CUSTOMER
- [ ] Go to profile
  - ✅ Should show username, email, role
  - ✅ Should show orders section
  - ✅ Should show addresses section

### Seller Profile
- [ ] Login as SELLER
- [ ] Go to profile
  - ✅ Should show username, email, role
  - ✅ Orders section should be HIDDEN
  - ✅ Addresses section should be HIDDEN

### Admin Profile
- [ ] Login as ADMIN
- [ ] Go to profile
  - ✅ Same as seller (customer data hidden)

---

## 🏪 SELLER DASHBOARD

### Access Control
- [ ] Login as CUSTOMER
- [ ] Try to access #seller-dash
  - ✅ Should show error "Seller dashboard is for sellers only"
  - ✅ Should redirect to #home

- [ ] Login as SELLER
- [ ] Access #seller-dash
  - ✅ Should display seller dashboard

### Dashboard Display
- [ ] Should show categories count
- [ ] Should show pending categories count
- [ ] Should show approved categories count
- [ ] Should show products list

---

## 👨‍💼 ADMIN DASHBOARD

### Access Control
- [ ] Login as SELLER
- [ ] Try to access #admin-dash
  - ✅ Should show error "Admin dashboard is for admins only"
  - ✅ Should redirect to #seller-dash

- [ ] Login as ADMIN
- [ ] Access #admin-dash
  - ✅ Should display admin dashboard

### Admin Functions
- [ ] Orders list should display
- [ ] Should be able to update order status
- [ ] Customer username should be displayed (and escaped if contains HTML)

---

## ⚠️ ERROR HANDLING & EDGE CASES

### API Error Handling
- [ ] Try API call with invalid endpoint
  - ✅ Should show "Server error. Please try again later."

- [ ] Network offline (DevTools → throttle offline)
  - ✅ Should show "Network error. Please check your connection."

- [ ] Server returns 400
  - ✅ Should show backend error message

- [ ] Server returns 403
  - ✅ Should show "Access denied"

- [ ] Server returns 404
  - ✅ Should show "Resource not found"

### Double-Submission Prevention
- [ ] Click "Add to Cart" twice rapidly
  - ✅ Should show "Please wait, request in progress..."
  - ✅ Should only make one API call

- [ ] Click "Complete Payment" twice
  - ✅ Only one payment should be created

### localStorage Corruption
- [ ] Open console, run: `localStorage.setItem('cart', 'invalid json')`
- [ ] Reload page
  - ✅ Should NOT crash
  - ✅ Should show corrupted data in console
  - ✅ Should auto-cleanup localStorage
  - ✅ Cart should be empty, not corrupted

### Missing DOM Elements
- [ ] Open HTML, temporarily remove `<div id="cart-badge">`
- [ ] Try to add product to cart
  - ✅ Should NOT crash
  - ✅ Should show success toast
  - ✅ Console should log no errors

---

## 🔒 SECURITY CHECKS

### XSS Prevention
- [ ] Create a product name like: `<img src=x onerror=alert('XSS')>`
- [ ] Add to cart, view cart
  - ✅ Should display as plain text, NOT execute
  - ✅ Should NOT show alert popup

- [ ] Same test with admin name, address fields
  - ✅ All should be escaped

### RBAC Enforcement
- [ ] Seller tries to add product to cart
  - ✅ Should show error "Only customers can purchase products"

- [ ] Seller tries to proceed to checkout
  - ✅ Should show error "Only customers can access checkout"

- [ ] Admin tries to remove cart item
  - ✅ Should show error "Only customers can manage cart"

---

## 📊 UI/UX CHECKS

### Toast Notifications
- [ ] Check all success toasts appear correctly
- [ ] Check all error toasts appear correctly
- [ ] Check warning toasts for validation
- [ ] Toasts should auto-dismiss after 3 seconds
- [ ] No duplicate toasts for same error

### Navigation
- [ ] Back button works correctly
- [ ] Deep links work (e.g., #product/uuid)
- [ ] Role-based navbar updates correctly on login

### Responsive Design
- [ ] Test on mobile (DevTools → Device Toggle)
- [ ] Test on tablet
- [ ] Test on desktop

---

## 🔧 CONSOLE CHECKS

After each test section, verify console:
- [ ] No JavaScript errors (red messages)
- [ ] No warnings about null elements
- [ ] No CORS errors
- [ ] appState should match localStorage

---

## ✅ FINAL VERIFICATION

Run these in browser console:

```javascript
// Check appState structure
console.log('appState:', appState);

// Verify token exists when logged in
console.log('token:', appState.token ? '✓ Present' : '✗ Missing');

// Check localStorage
console.log('localStorage user:', localStorage.getItem('user'));
console.log('localStorage cart:', localStorage.getItem('cart'));

// Try escapeHtml function
console.log('XSS Test:', escapeHtml('<img src=x onerror=alert()>'));
// Should output: &lt;img src=x onerror=alert()&gt;
```

---

## 📋 SIGN-OFF

### Test Completion
- [ ] All tests passed
- [ ] No critical errors found
- [ ] No security issues found
- [ ] Performance acceptable
- [ ] UX smooth and intuitive

### Ready for Production?
- **YES** ✅ - All tests pass, no issues found
- **NO** ⚠️ - Issues found (list below):

**Issues Found:**
1. 
2. 
3. 

**Tester Name:** _________________
**Date:** _________________
**Browser/OS:** _________________
