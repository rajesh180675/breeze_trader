"""Strategy Builder — predefined strategies, leg generation, payoff."""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd


@dataclass
class StrategyLeg:
    strike: int
    option_type: str
    action: str
    quantity: int
    premium: float = 0.0


PREDEFINED_STRATEGIES: Dict[str, Dict[str, Any]] = {
    "Short Straddle": {
        "description": "Sell ATM Call + ATM Put. Max profit when underlying stays at ATM.",
        "legs": [
            {"offset": 0, "type": "CE", "action": "sell"},
            {"offset": 0, "type": "PE", "action": "sell"},
        ],
        "view": "Neutral", "risk": "Unlimited", "reward": "Limited (premium)"
    },
    "Short Strangle": {
        "description": "Sell OTM Call + OTM Put. Wider profit zone than straddle.",
        "legs": [
            {"offset": 2, "type": "CE", "action": "sell"},
            {"offset": -2, "type": "PE", "action": "sell"},
        ],
        "view": "Neutral/Range", "risk": "Unlimited", "reward": "Limited (premium)"
    },
    "Iron Condor": {
        "description": "Sell OTM call spread + put spread. Limited risk neutral strategy.",
        "legs": [
            {"offset": -3, "type": "PE", "action": "buy"},
            {"offset": -1, "type": "PE", "action": "sell"},
            {"offset": 1, "type": "CE", "action": "sell"},
            {"offset": 3, "type": "CE", "action": "buy"},
        ],
        "view": "Neutral", "risk": "Limited", "reward": "Limited (premium)"
    },
    "Iron Butterfly": {
        "description": "Sell ATM straddle + buy OTM strangle.",
        "legs": [
            {"offset": -2, "type": "PE", "action": "buy"},
            {"offset": 0, "type": "PE", "action": "sell"},
            {"offset": 0, "type": "CE", "action": "sell"},
            {"offset": 2, "type": "CE", "action": "buy"},
        ],
        "view": "Neutral", "risk": "Limited", "reward": "Limited (premium)"
    },
    "Bull Call Spread": {
        "description": "Buy lower call + sell higher call.",
        "legs": [
            {"offset": -1, "type": "CE", "action": "buy"},
            {"offset": 1, "type": "CE", "action": "sell"},
        ],
        "view": "Bullish", "risk": "Limited", "reward": "Limited"
    },
    "Bear Put Spread": {
        "description": "Buy higher put + sell lower put.",
        "legs": [
            {"offset": 1, "type": "PE", "action": "buy"},
            {"offset": -1, "type": "PE", "action": "sell"},
        ],
        "view": "Bearish", "risk": "Limited", "reward": "Limited"
    },
    "Long Straddle": {
        "description": "Buy ATM Call + ATM Put. Profit from big moves.",
        "legs": [
            {"offset": 0, "type": "CE", "action": "buy"},
            {"offset": 0, "type": "PE", "action": "buy"},
        ],
        "view": "Volatile", "risk": "Limited (premium)", "reward": "Unlimited"
    },
}


def generate_strategy_legs(strategy_name: str, atm_strike: int,
                           strike_gap: int, lot_size: int,
                           lots: int = 1) -> List[StrategyLeg]:
    strat = PREDEFINED_STRATEGIES.get(strategy_name)
    if not strat:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    qty = lots * lot_size
    return [
        StrategyLeg(
            strike=atm_strike + leg["offset"] * strike_gap,
            option_type=leg["type"], action=leg["action"], quantity=qty
        )
        for leg in strat["legs"]
    ]


def calculate_strategy_metrics(legs: List[StrategyLeg]) -> Dict[str, Any]:
    net_premium = sum(
        (leg.premium * leg.quantity if leg.action == "sell" else -leg.premium * leg.quantity)
        for leg in legs
    )
    all_strikes = [l.strike for l in legs]
    spread = max(all_strikes) - min(all_strikes) + 100
    low = min(all_strikes) - 10 * spread
    high = max(all_strikes) + 10 * spread
    spots = np.linspace(low, high, 500)
    payoffs = _calc_payoffs(legs, spots)
    breakevens = []
    for i in range(len(payoffs) - 1):
        if payoffs[i] * payoffs[i + 1] < 0:
            be = spots[i] - payoffs[i] * (spots[i + 1] - spots[i]) / (payoffs[i + 1] - payoffs[i])
            breakevens.append(round(float(be), 0))
    return {
        "net_premium": round(net_premium, 2),
        "max_profit": round(float(max(payoffs)), 2),
        "max_loss": round(float(min(payoffs)), 2),
        "breakevens": breakevens,
    }


def generate_payoff_data(legs: List[StrategyLeg], center: float,
                         gap: int, points: int = 200) -> Optional[pd.DataFrame]:
    if not legs:
        return None
    all_strikes = [l.strike for l in legs]
    low = min(all_strikes) - 8 * gap
    high = max(all_strikes) + 8 * gap
    spots = np.linspace(low, high, points)
    payoffs = _calc_payoffs(legs, spots)
    return pd.DataFrame({"Underlying": spots, "P&L": payoffs})


def _calc_payoffs(legs: List[StrategyLeg], spots: np.ndarray) -> np.ndarray:
    payoffs = np.zeros(len(spots))
    for leg in legs:
        if leg.option_type == "CE":
            intrinsic = np.maximum(spots - leg.strike, 0)
        else:
            intrinsic = np.maximum(leg.strike - spots, 0)
        if leg.action == "sell":
            payoffs += (leg.premium - intrinsic) * leg.quantity
        else:
            payoffs += (intrinsic - leg.premium) * leg.quantity
    return payoffs
