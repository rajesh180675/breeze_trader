"""Input validation with Pydantic."""

from pydantic import BaseModel, validator, Field
from typing import Literal
from datetime import date
import app_config as C


class OrderRequest(BaseModel):
    instrument: str
    strike: int = Field(gt=0)
    option_type: Literal['CE', 'PE']
    action: Literal['buy', 'sell']
    quantity: int = Field(gt=0)
    order_type: Literal['market', 'limit'] = 'market'
    price: float = Field(default=0, ge=0)

    @validator('instrument')
    def validate_instrument(cls, v):
        if v not in C.INSTRUMENTS:
            raise ValueError(f"Unknown: {v}")
        return v

    @validator('strike')
    def validate_strike(cls, v, values):
        if 'instrument' in values and not C.validate_strike(values['instrument'], v):
            raise ValueError(f"Invalid strike {v}")
        return v

    @validator('price')
    def validate_price(cls, v, values):
        if values.get('order_type') == 'limit' and v <= 0:
            raise ValueError("Price required for limit orders")
        return v


def validate_date_range(from_date: date, to_date: date) -> bool:
    if from_date > to_date:
        raise ValueError("From date cannot be after To date")
    if (to_date - from_date).days > 90:
        raise ValueError("Range cannot exceed 90 days")
    return True
