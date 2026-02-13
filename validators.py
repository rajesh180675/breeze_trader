"""
Input Validation using Pydantic
================================
Validates all user inputs before processing.
"""

from pydantic import BaseModel, validator, Field
from typing import Optional, Literal
from datetime import date
import app_config as C


class OrderRequest(BaseModel):
    """Validate order placement request."""
    
    instrument: str
    strike: int = Field(gt=0)
    option_type: Literal['CE', 'PE']
    action: Literal['buy', 'sell']
    quantity: int = Field(gt=0, le=C.MAX_LOTS_PER_ORDER * 100)
    order_type: Literal['market', 'limit'] = 'market'
    price: float = Field(default=0, ge=0)
    
    @validator('instrument')
    def validate_instrument(cls, v):
        """Ensure instrument exists."""
        if v not in C.INSTRUMENTS:
            raise ValueError(f"Unknown instrument: {v}")
        return v
    
    @validator('strike')
    def validate_strike(cls, v, values):
        """Ensure strike is valid for instrument."""
        if 'instrument' in values:
            if not C.validate_strike(values['instrument'], v):
                raise ValueError(f"Invalid strike {v} for {values['instrument']}")
        return v
    
    @validator('price')
    def validate_price(cls, v, values):
        """Ensure price is valid for limit orders."""
        if values.get('order_type') == 'limit' and v <= 0:
            raise ValueError("Price must be positive for limit orders")
        return v


class QuoteRequest(BaseModel):
    """Validate quote request."""
    
    instrument: str
    strike: int = Field(gt=0)
    option_type: Literal['CE', 'PE']
    expiry: str
    
    @validator('instrument')
    def validate_instrument(cls, v):
        if v not in C.INSTRUMENTS:
            raise ValueError(f"Unknown instrument: {v}")
        return v


class OptionChainRequest(BaseModel):
    """Validate option chain request."""
    
    instrument: str
    expiry: str
    strikes_count: int = Field(default=15, ge=5, le=50)
    
    @validator('instrument')
    def validate_instrument(cls, v):
        if v not in C.INSTRUMENTS:
            raise ValueError(f"Unknown instrument: {v}")
        return v


class SquareOffRequest(BaseModel):
    """Validate square-off request."""
    
    position_id: str
    quantity: int = Field(gt=0)
    order_type: Literal['market', 'limit'] = 'market'
    price: float = Field(default=0, ge=0)
    
    @validator('price')
    def validate_price(cls, v, values):
        if values.get('order_type') == 'limit' and v <= 0:
            raise ValueError("Price required for limit orders")
        return v


def validate_date_range(from_date: date, to_date: date) -> bool:
    """
    Validate date range for order/trade history.
    
    Args:
        from_date: Start date
        to_date: End date
    
    Returns:
        True if valid
    
    Raises:
        ValueError: If invalid date range
    """
    if from_date > to_date:
        raise ValueError("From date cannot be after To date")
    
    if (to_date - from_date).days > 90:
        raise ValueError("Date range cannot exceed 90 days")
    
    return True
