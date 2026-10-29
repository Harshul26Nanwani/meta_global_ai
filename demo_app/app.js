const state = {
  selectedProduct: null,
  selectedPrice: 0,
};

const selectedProductEl = document.getElementById('selected-product');
const cartTotalEl = document.getElementById('cart-total');
const checkoutButton = document.getElementById('checkout-button');

function renderCart() {
  if (!state.selectedProduct) {
    selectedProductEl.textContent = 'No product selected';
    cartTotalEl.textContent = 'Total: ₹0';
    return;
  }

  selectedProductEl.textContent = `Selected: ${state.selectedProduct}`;
  cartTotalEl.textContent = `Total: ₹${state.selectedPrice.toLocaleString('en-IN')}`;
}

document.querySelectorAll('.buy-button').forEach((button) => {
  button.addEventListener('click', () => {
    const productCard = button.closest('.product-card');
    const productName = productCard.querySelector('h2').textContent.trim();
    const price = Number(productCard.dataset.price || 0);
    state.selectedProduct = productName;
    state.selectedPrice = price;
    renderCart();
  });
});

checkoutButton.addEventListener('click', () => {
  if (!state.selectedProduct) {
    selectedProductEl.textContent = 'No product selected';
    return;
  }

  const isValid = state.selectedPrice <= 80000;
  selectedProductEl.textContent = isValid
    ? `Verified product: ${state.selectedProduct}`
    : `Validation failed: ${state.selectedProduct} exceeds budget`;
  cartTotalEl.textContent = `Total: ₹${state.selectedPrice.toLocaleString('en-IN')}`;
});

renderCart();
