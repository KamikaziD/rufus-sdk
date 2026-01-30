/**
 * Calculate pricing for order items.
 *
 * This script demonstrates:
 * - Accessing workflow state
 * - Using rufus utilities
 * - Complex data transformations
 * - Returning structured results
 */

// Get items from workflow state
const items = state.items;

rufus.log(`Calculating pricing for ${items.length} items`);

// Calculate line items with extended pricing
const lineItems = items.map(item => {
  const lineTotal = item.unit_price * item.quantity;
  return {
    product_id: item.product_id,
    name: item.name,
    quantity: item.quantity,
    unit_price: item.unit_price,
    line_total: rufus.round(lineTotal, 2),
    category: item.category
  };
});

// Calculate subtotal
const subtotal = rufus.sum(lineItems.map(li => li.line_total));

// Group items by category for reporting
const byCategory = rufus.groupBy(lineItems, 'category');
const categorySummary = {};
for (const [category, catItems] of Object.entries(byCategory)) {
  categorySummary[category] = {
    count: catItems.length,
    total: rufus.round(rufus.sum(catItems.map(i => i.line_total)), 2)
  };
}

// Calculate shipping based on method
const shippingRates = {
  standard: 5.99,
  express: 12.99,
  overnight: 24.99
};
const shippingCost = shippingRates[state.shipping_method] || shippingRates.standard;

// Calculate tax (simplified: 8% tax rate)
const taxRate = 0.08;
const taxAmount = rufus.round(subtotal * taxRate, 2);

rufus.log(`Subtotal: $${subtotal}, Tax: $${taxAmount}, Shipping: $${shippingCost}`);

// Return pricing breakdown
return {
  line_items: lineItems,
  subtotal: rufus.round(subtotal, 2),
  tax_rate: taxRate,
  tax_amount: taxAmount,
  shipping_method: state.shipping_method,
  shipping_cost: shippingCost,
  category_summary: categorySummary,
  pre_discount_total: rufus.round(subtotal + taxAmount + shippingCost, 2),
  calculated_at: rufus.now()
};
