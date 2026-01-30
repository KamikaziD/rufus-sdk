/**
 * Apply discount codes with TypeScript type safety.
 *
 * This script demonstrates:
 * - TypeScript interfaces for type safety
 * - Complex discount logic
 * - Conditional calculations
 */

// Define types for our data structures
interface Pricing {
  subtotal: number;
  tax_amount: number;
  shipping_cost: number;
  pre_discount_total: number;
}

interface DiscountRule {
  type: 'percentage' | 'fixed' | 'shipping';
  value: number;
  min_purchase?: number;
}

// Discount code database (in real app, this would come from API)
const discountCodes: Record<string, DiscountRule> = {
  'SAVE10': { type: 'percentage', value: 10 },
  'SAVE20': { type: 'percentage', value: 20, min_purchase: 100 },
  'FLAT15': { type: 'fixed', value: 15, min_purchase: 50 },
  'FREESHIP': { type: 'shipping', value: 100 },
};

// Get pricing from previous step
const pricing = (state as any).pricing as Pricing;
const discountCode = (state as any).discount_code as string | undefined;

// Start with base values
let discountAmount = 0;
let discountApplied: string | null = null;
let discountMessage = 'No discount applied';

// Apply discount if code is valid
if (discountCode && discountCodes[discountCode.toUpperCase()]) {
  const rule = discountCodes[discountCode.toUpperCase()];

  // Check minimum purchase requirement
  if (rule.min_purchase && pricing.subtotal < rule.min_purchase) {
    discountMessage = `Discount code ${discountCode} requires minimum purchase of $${rule.min_purchase}`;
  } else {
    discountApplied = discountCode.toUpperCase();

    switch (rule.type) {
      case 'percentage':
        discountAmount = (pricing.subtotal * rule.value) / 100;
        discountMessage = `${rule.value}% discount applied`;
        break;

      case 'fixed':
        discountAmount = Math.min(rule.value, pricing.subtotal);
        discountMessage = `$${rule.value} discount applied`;
        break;

      case 'shipping':
        discountAmount = (pricing.shipping_cost * rule.value) / 100;
        discountMessage = 'Free shipping applied';
        break;
    }
  }
} else if (discountCode) {
  discountMessage = `Invalid discount code: ${discountCode}`;
}

// Round discount amount
discountAmount = Math.round(discountAmount * 100) / 100;

// Calculate final total
const total = Math.round((pricing.pre_discount_total - discountAmount) * 100) / 100;

// Return final pricing
return {
  subtotal: pricing.subtotal,
  tax_amount: pricing.tax_amount,
  shipping_cost: pricing.shipping_cost,
  discount_code: discountApplied,
  discount_amount: discountAmount,
  discount_message: discountMessage,
  total: total
};
