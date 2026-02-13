"""
Analytics & Greeks Calculation — Black-Scholes, risk metrics, payoffs.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from typing import Dict, Tuple
import app_config as C


def calculate_greeks(spot, strike, time_to_expiry, volatility, option_type, risk_free_rate=C.RISK_FREE_RATE):
    if time_to_expiry <= 0:
        if option_type == 'CE':
            return {'delta': 1.0 if spot > strike else 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0}
        else:
            return {'delta': -1.0 if spot < strike else 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0}

    d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * np.sqrt(time_to_expiry))
    d2 = d1 - volatility * np.sqrt(time_to_expiry)
    n_d1 = norm.pdf(d1)
    N_d1 = norm.cdf(d1)
    N_d2 = norm.cdf(d2)

    if option_type == 'CE':
        delta = N_d1
        theta = (-spot * n_d1 * volatility / (2 * np.sqrt(time_to_expiry)) - risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * N_d2)
        rho = strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * N_d2
    else:
        delta = N_d1 - 1
        theta = (-spot * n_d1 * volatility / (2 * np.sqrt(time_to_expiry)) + risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2))
        rho = -strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2)

    gamma = n_d1 / (spot * volatility * np.sqrt(time_to_expiry))
    vega = spot * n_d1 * np.sqrt(time_to_expiry)

    return {
        'delta': round(delta, 4),
        'gamma': round(gamma, 6),
        'theta': round(theta / C.DAYS_PER_YEAR, 4),
        'vega': round(vega / 100, 4),
        'rho': round(rho / 100, 6)
    }


def estimate_implied_volatility(option_price, spot, strike, time_to_expiry, option_type, risk_free_rate=C.RISK_FREE_RATE):
    if time_to_expiry <= 0 or option_price <= 0 or spot <= 0 or strike <= 0:
        return 0.25
    vol = 0.25
    for _ in range(100):
        d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * vol ** 2) * time_to_expiry) / (vol * np.sqrt(time_to_expiry))
        d2 = d1 - vol * np.sqrt(time_to_expiry)
        if option_type == 'CE':
            price = spot * norm.cdf(d1) - strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(d2)
        else:
            price = strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)
        vega = spot * norm.pdf(d1) * np.sqrt(time_to_expiry)
        diff = price - option_price
        if abs(diff) < 0.0001:
            return vol
        if vega < 1e-10:
            break
        vol = max(vol - diff / vega, 0.01)
    return vol


def calculate_portfolio_greeks(positions: pd.DataFrame) -> Dict[str, float]:
    if positions.empty:
        return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0}
    result = {}
    for g in ['delta', 'gamma', 'theta', 'vega', 'rho']:
        if g in positions.columns:
            result[g] = (positions[g] * positions['quantity']).sum()
        else:
            result[g] = 0.0
    return result


def calculate_var(returns: pd.Series, confidence_level=0.95):
    return returns.quantile(1 - confidence_level) if not returns.empty else 0.0


def calculate_max_drawdown(equity_curve: pd.Series) -> Tuple[float, int]:
    if equity_curve.empty:
        return 0.0, 0
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return abs(drawdown.min()), 0


def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate=C.RISK_FREE_RATE):
    if returns.empty or returns.std() == 0:
        return 0.0
    return (returns.mean() * 252 - risk_free_rate) / (returns.std() * np.sqrt(252))


def calculate_win_rate(trades: pd.DataFrame) -> Dict[str, float]:
    if trades.empty or 'pnl' not in trades.columns:
        return {'win_rate': 0, 'avg_win': 0, 'avg_loss': 0, 'profit_factor': 0, 'total_trades': 0}
    wins = trades[trades['pnl'] > 0]
    losses = trades[trades['pnl'] < 0]
    total_wins = wins['pnl'].sum() if not wins.empty else 0
    total_losses = abs(losses['pnl'].sum()) if not losses.empty else 0
    return {
        'win_rate': round(len(wins) / len(trades) * 100, 2) if len(trades) > 0 else 0,
        'avg_win': round(wins['pnl'].mean(), 2) if not wins.empty else 0,
        'avg_loss': round(abs(losses['pnl'].mean()), 2) if not losses.empty else 0,
        'profit_factor': round(total_wins / total_losses, 2) if total_losses > 0 else float('inf'),
        'total_trades': len(trades)
    }


def calculate_strategy_payoff(positions: pd.DataFrame, spot_range: np.ndarray) -> pd.DataFrame:
    payoffs = pd.DataFrame({'spot': spot_range, 'payoff': 0.0})
    for _, pos in positions.iterrows():
        strike = pos['strike']
        option_type = pos['option_type']
        quantity = pos['quantity']
        entry_price = pos['entry_price']
        position_type = pos['position_type']
        if option_type == 'CE':
            intrinsic = np.maximum(spot_range - strike, 0)
        else:
            intrinsic = np.maximum(strike - spot_range, 0)
        if position_type == 'short':
            payoffs['payoff'] += (entry_price - intrinsic) * quantity
        else:
            payoffs['payoff'] += (intrinsic - entry_price) * quantity
    return payoffs
