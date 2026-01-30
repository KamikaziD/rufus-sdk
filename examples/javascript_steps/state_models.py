"""State models for JavaScript steps example."""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class OrderItem(BaseModel):
    """A single item in the order."""
    product_id: str
    name: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)
    category: str = "general"


class OrderState(BaseModel):
    """State for order processing workflow."""

    # Input fields
    customer_id: str
    items: List[OrderItem] = Field(default_factory=list)
    discount_code: Optional[str] = None
    shipping_method: str = "standard"

    # Fields populated by JavaScript steps
    pricing: Optional[Dict[str, Any]] = None
    final_pricing: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None

    # Fields populated by Python steps
    validated: bool = False
    processed: bool = False
    order_id: Optional[str] = None
    status: str = "pending"
