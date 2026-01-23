"""
State models for the Order Processing workflow.
These Pydantic models define the data structure for workflow state.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class OrderItem(BaseModel):
    """Individual item in an order"""
    product_id: str
    name: str
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)


class OrderState(BaseModel):
    """State for the order processing workflow"""
    order_id: Optional[str] = None
    customer_id: str
    customer_email: str
    items: List[OrderItem]
    total_amount: Optional[float] = None

    # Processing steps
    inventory_reserved: Optional[bool] = None
    payment_processed: Optional[bool] = None
    payment_transaction_id: Optional[str] = None

    # Fulfillment
    shipment_id: Optional[str] = None
    tracking_number: Optional[str] = None

    # Status
    order_status: Optional[str] = None  # PENDING, PROCESSING, SHIPPED, DELIVERED, CANCELLED

    # Timestamps
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ApprovalInput(BaseModel):
    """Input model for manual approval step"""
    approved: bool
    approver_id: str
    notes: Optional[str] = None
