"""
Strategy Builder Module
=======================
Multi-leg options strategy definitions and calculations.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd


@dataclass
class StrategyLeg:
    """Represents a single leg of an options strategy."""
    strike: int
    option_type: str  # 'CE' or 'PE'
    action: str  # 'buy' or 'sell'
    quantity: int
    premium: float = 0.0
    
    @property
    def is_long(self) -> bool:
        return self.action == 'buy'
    
    @property
    def is_short(self) -> bool:
        return self.action == 'sell'


# ═══════════════════════════════════════════════════════════════════
# PREDEFINED STRATEGIES
# ═══════════════════════════════════════════════════════════════════

PREDEFINED_STRATEGIES: Dict[str, Dict[str, Any]] = {
    "Bull Call Spread": {
        "description": "Buy lower strike call, sell higher strike call. Bullish with limited risk.",
        "legs": [
            {"strike_offset": 0, "option_type": "CE", "action": "buy"},
            {"strike_offset": 1, "option_type": "CE", "action": "sell"}
        ],
        "characteristics": {
            "max_profit": "Strike difference - Net premium",
            "max_loss": "Net premium paid",
            "market_view": "Moderately Bullish"
        }
    },
    "Bear Put Spread": {
        "description": "Buy higher strike put, sell lower strike put. Bearish with limited risk.",
        "legs": [
            {"strike_offset": 0, "option_type": "PE", "action": "buy"},
            {"strike_offset": -1, "option_type": "PE", "action": "sell"}
        ],
        "characteristics": {
            "max_profit": "Strike difference - Net premium",
            "max_loss": "Net premium paid",
            "market_view": "Moderately Bearish"
        }
    },
    "Iron Condor": {
        "description": "Sell OTM call spread and OTM put spread. Profit from low volatility.",
        "legs": [
            {"strike_offset": -2, "option_type": "PE", "action": "buy"},
            {"strike_offset": -1, "option_type": "PE", "action": "sell"},
            {"strike_offset": 1, "option_type": "CE", "action": "sell"},
            {"strike_offset": 2, "option_type": "CE", "action": "buy"}
        ],
        "characteristics": {
            "max_profit": "Net premium received",
            "max_loss": "Strike width - Net premium",
            "market_view": "Neutral / Low Volatility"
        }
    },
    "Short Straddle": {
        "description": "Sell ATM call and ATM put. Maximum profit at ATM at expiry.",
        "legs": [
            {"strike_offset": 0, "option_type": "CE", "action": "sell"},
            {"strike_offset": 0, "option_type": "PE", "action": "sell"}
        ],
        "characteristics": {
            "max_profit": "Total premium received",
            "max_loss": "Unlimited",
            "market_view": "Neutral / Low Volatility"
        }
    },
    "Short Strangle": {
        "description": "Sell OTM call and OTM put. Wider profit zone than straddle.",
        "legs": [
            {"strike_offset": 1, "option_type": "CE", "action": "sell"},
            {"strike_offset": -1, "option_type": "PE", "action": "sell"}
        ],
        "characteristics": {
            "max_profit": "Total premium received",
            "max_loss": "Unlimited",
            "market_view": "Neutral / Range-bound"
        }
    },
    "Long Straddle": {
        "description": "Buy ATM call and ATM put. Profit from large moves in either direction.",
        "legs": [
            {"strike_offset": 0, "option_type": "CE", "action": "buy"},
            {"strike_offset": 0, "option_type": "PE", "action": "buy"}
        ],
        "characteristics": {
            "max_profit": "Unlimited",
            "max_loss": "Total premium paid",
            "market_view": "High Volatility Expected"
        }
    },
    "Iron Butterfly": {
        "description": "Sell ATM straddle, buy OTM strangle. Limited risk neutral strategy.",
        "legs": [
            {"strike_offset": -1, "option_type": "PE", "action": "buy"},
            {"strike_offset": 0, "option_type": "PE", "action": "sell"},
            {"strike_offset": 0, "option_type": "CE", "action": "sell"},
            {"strike_offset": 1, "option_type": "CE", "action": "buy"}
        ],
        "characteristics": {
            "max_profit": "Net premium received",
            "max_loss": "Strike width - Net premium",
            "market_view": "Neutral"
        }
    }
}


def generate_strategy_legs(
    strategy_name: str,
    atm_strike: int,
    strike_gap: int,
    lot_size: int,
    lots: int = 1
) -> List[StrategyLeg]:
    """
    Generate strategy legs based on strategy definition.
    
    Args:
        strategy_name: Name of predefined strategy
        atm_strike: ATM strike price
        strike_gap: Strike gap for instrument
        lot_size: Lot size for instrument
        lots: Number of lots per leg
    
    Returns:
        List of StrategyLeg objects
    """
    strategy = PREDEFINED_STRATEGIES.get(strategy_name)
    if not strategy:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    legs = []
    quantity = lots * lot_size
    
    for leg_def in strategy["legs"]:
        strike = atm_strike + (leg_def["strike_offset"] * strike_gap)
        leg = StrategyLeg(
            strike=strike,
            option_type=leg_def["option_type"],
            action=leg_def["action"],
            quantity=quantity
        )
        legs.append(leg)
    
    return legs


def calculate_strategy_metrics(
    legs: List[StrategyLeg],
    spot_price: float
) -> Dict[str, Any]:
    """
    Calculate strategy metrics including max profit/loss and breakevens.
    
    Args:
        legs: List of strategy legs
        spot_price: Current spot price
    
    Returns:
        Dictionary with strategy metrics
    """
    net_premium = 0.0
    
    for leg in legs:
        if leg.action == "buy":
            net_premium -= leg.premium * leg.quantity
        else:
            net_premium += leg.premium * leg.quantity
    
    # Calculate payoff at various spots
    spot_range = np.linspace(spot_price * 0.8, spot_price * 1.2, 100)
    payoffs = []
    
    for spot in spot_range:
        payoff = net_premium
        for leg in legs:
            if leg.option_type == "CE":
                intrinsic = max(0, spot - leg.strike)
            else:
                intrinsic = max(0, leg.strike - spot)
            
            if leg.action == "buy":
                payoff += intrinsic * leg.quantity
            else:
                payoff -= intrinsic * leg.quantity
        
        payoffs.append(payoff)
    
    max_profit = max(payoffs)
    max_loss = min(payoffs)
    
    # Find breakevens (where payoff crosses zero)
    breakevens = []
    for i in range(len(payoffs) - 1):
        if payoffs[i] * payoffs[i + 1] < 0:
            breakevens.append(spot_range[i])
    
    return {
        "net_premium": net_premium,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven_lower": breakevens[0] if breakevens else None,
        "breakeven_upper": breakevens[-1] if len(breakevens) > 1 else None
    }


def generate_payoff_data(
    legs: List[StrategyLeg],
    spot_price: float,
    strike_gap: int
) -> Optional[pd.DataFrame]:
    """
    Generate payoff diagram data.
    
    Args:
        legs: Strategy legs
        spot_price: Current spot price
        strike_gap: Strike gap
    
    Returns:
        DataFrame with payoff data
    """
    if not legs:
        return None
    
    # Calculate net premium
    net_premium = 0.0
    for leg in legs:
        if leg.action == "buy":
            net_premium -= leg.premium * leg.quantity
        else:
            net_premium += leg.premium * leg.quantity
    
    # Generate spot range
    all_strikes = [leg.strike for leg in legs]
    min_strike = min(all_strikes) - 5 * strike_gap
    max_strike = max(all_strikes) + 5 * strike_gap
    
    spot_range = np.linspace(min_strike, max_strike, 100)
    payoffs = []
    
    for spot in spot_range:
        payoff = net_premium
        for leg in legs:
            if leg.option_type == "CE":
                intrinsic = max(0, spot - leg.strike)
            else:
                intrinsic = max(0, leg.strike - spot)
            
            if leg.action == "buy":
                payoff += intrinsic * leg.quantity
            else:
                payoff -= intrinsic * leg.quantity
        
        payoffs.append(payoff)
    
    return pd.DataFrame({
        "Underlying": spot_range,
        "P&L": payoffs
    })
