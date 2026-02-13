"""
Advanced Analytics & Greeks Calculation
========================================
Option Greeks, risk metrics, portfolio analytics.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime
from typing import Dict, Tuple
import app_config as C


# ═══════════════════════════════════════════════════════════════════
# BLACK-SCHOLES GREEKS
# ═══════════════════════════════════════════════════════════════════

def calculate_greeks(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    option_type: str,
    risk_free_rate: float = C.RISK_FREE_RATE
) -> Dict[str, float]:
    """
    Calculate Black-Scholes Greeks.
    
    Args:
        spot: Current underlying price
        strike: Strike price
        time_to_expiry: Time to expiry in years
        volatility: Implied volatility (as decimal, e.g., 0.20 for 20%)
        option_type: 'CE' or 'PE'
        risk_free_rate: Risk-free rate (annual)
    
    Returns:
        Dictionary with delta, gamma, theta, vega, rho
    """
    if time_to_expiry <= 0:
        # At expiry, return theoretical values
        if option_type == 'CE':
            return {
                'delta': 1.0 if spot > strike else 0.0,
                'gamma': 0.0,
                'theta': 0.0,
                'vega': 0.0,
                'rho': 0.0
            }
        else:  # PE
            return {
                'delta': -1.0 if spot < strike else 0.0,
                'gamma': 0.0,
                'theta': 0.0,
                'vega': 0.0,
                'rho': 0.0
            }
    
    # Calculate d1 and d2
    d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / \
         (volatility * np.sqrt(time_to_expiry))
    d2 = d1 - volatility * np.sqrt(time_to_expiry)
    
    # Standard normal PDF and CDF
    n_d1 = norm.pdf(d1)
    N_d1 = norm.cdf(d1)
    N_d2 = norm.cdf(d2)
    
    if option_type == 'CE':
        delta = N_d1
        theta = (-spot * n_d1 * volatility / (2 * np.sqrt(time_to_expiry)) -
                 risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * N_d2)
        rho = strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * N_d2
    else:  # PE
        delta = N_d1 - 1
        theta = (-spot * n_d1 * volatility / (2 * np.sqrt(time_to_expiry)) +
                 risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2))
        rho = -strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2)
    
    # Gamma and Vega are same for calls and puts
    gamma = n_d1 / (spot * volatility * np.sqrt(time_to_expiry))
    vega = spot * n_d1 * np.sqrt(time_to_expiry)
    
    # Convert theta to per-day (from per-year)
    theta_per_day = theta / C.DAYS_PER_YEAR
    
    # Convert vega to per 1% change (from per 100% change)
    vega_per_percent = vega / 100
    
    return {
        'delta': round(delta, 4),
        'gamma': round(gamma, 6),
        'theta': round(theta_per_day, 4),
        'vega': round(vega_per_percent, 4),
        'rho': round(rho / 100, 6)  # Per 1% change in interest rate
    }


def estimate_implied_volatility(
    option_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    option_type: str,
    risk_free_rate: float = C.RISK_FREE_RATE
) -> float:
    """
    Estimate implied volatility using Newton-Raphson method.
    
    Args:
        option_price: Market price of option
        spot: Current underlying price
        strike: Strike price
        time_to_expiry: Time to expiry in years
        option_type: 'CE' or 'PE'
        risk_free_rate: Risk-free rate
    
    Returns:
        Implied volatility (as decimal)
    """
    # Initial guess
    vol = 0.25
    max_iterations = 100
    tolerance = 0.0001
    
    for _ in range(max_iterations):
        # Calculate option price using Black-Scholes
        d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * vol ** 2) * time_to_expiry) / \
             (vol * np.sqrt(time_to_expiry))
        d2 = d1 - vol * np.sqrt(time_to_expiry)
        
        if option_type == 'CE':
            price = spot * norm.cdf(d1) - strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(d2)
        else:  # PE
            price = strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)
        
        # Calculate vega
        vega = spot * norm.pdf(d1) * np.sqrt(time_to_expiry)
        
        # Newton-Raphson update
        diff = price - option_price
        
        if abs(diff) < tolerance:
            return vol
        
        if vega < 1e-10:  # Avoid division by zero
            break
        
        vol = vol - diff / vega
        
        # Ensure volatility stays positive
        vol = max(vol, 0.01)
    
    return vol


def calculate_portfolio_greeks(positions: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate aggregate Greeks for entire portfolio.
    
    Args:
        positions: DataFrame with position details including greeks
    
    Returns:
        Dictionary with portfolio-level greeks
    """
    if positions.empty:
        return {
            'delta': 0.0,
            'gamma': 0.0,
            'theta': 0.0,
            'vega': 0.0,
            'rho': 0.0
        }
    
    # Aggregate greeks
    portfolio_greeks = {
        'delta': (positions['delta'] * positions['quantity']).sum(),
        'gamma': (positions['gamma'] * positions['quantity']).sum(),
        'theta': (positions['theta'] * positions['quantity']).sum(),
        'vega': (positions['vega'] * positions['quantity']).sum(),
        'rho': (positions['rho'] * positions['quantity']).sum()
    }
    
    return portfolio_greeks


# ═══════════════════════════════════════════════════════════════════
# RISK METRICS
# ═══════════════════════════════════════════════════════════════════

def calculate_var(returns: pd.Series, confidence_level: float = 0.95) -> float:
    """
    Calculate Value at Risk (VaR).
    
    Args:
        returns: Series of returns
        confidence_level: Confidence level (e.g., 0.95 for 95%)
    
    Returns:
        VaR value
    """
    if returns.empty:
        return 0.0
    
    return returns.quantile(1 - confidence_level)


def calculate_max_drawdown(equity_curve: pd.Series) -> Tuple[float, int]:
    """
    Calculate maximum drawdown from equity curve.
    
    Args:
        equity_curve: Series of portfolio values over time
    
    Returns:
        (max_drawdown_percentage, days_to_recovery)
    """
    if equity_curve.empty:
        return 0.0, 0
    
    # Calculate running maximum
    running_max = equity_curve.cummax()
    
    # Calculate drawdown
    drawdown = (equity_curve - running_max) / running_max
    
    # Maximum drawdown
    max_dd = drawdown.min()
    
    # Find recovery period
    max_dd_date = drawdown.idxmin()
    recovery_dates = equity_curve[max_dd_date:][equity_curve >= running_max[max_dd_date]]
    
    if not recovery_dates.empty:
        recovery_date = recovery_dates.index[0]
        days_to_recovery = (recovery_date - max_dd_date).days
    else:
        days_to_recovery = -1  # Not yet recovered
    
    return abs(max_dd), days_to_recovery


def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = C.RISK_FREE_RATE
) -> float:
    """
    Calculate Sharpe ratio.
    
    Args:
        returns: Series of returns
        risk_free_rate: Annual risk-free rate
    
    Returns:
        Sharpe ratio
    """
    if returns.empty or returns.std() == 0:
        return 0.0
    
    # Annualize returns and volatility
    annual_return = returns.mean() * 252  # Assuming daily returns
    annual_vol = returns.std() * np.sqrt(252)
    
    sharpe = (annual_return - risk_free_rate) / annual_vol
    
    return sharpe


def calculate_win_rate(trades: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate trading statistics.
    
    Args:
        trades: DataFrame with trade P&L
    
    Returns:
        Dictionary with win_rate, avg_win, avg_loss, profit_factor
    """
    if trades.empty:
        return {
            'win_rate': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'profit_factor': 0.0,
            'total_trades': 0
        }
    
    winning_trades = trades[trades['pnl'] > 0]
    losing_trades = trades[trades['pnl'] < 0]
    
    win_rate = len(winning_trades) / len(trades) if len(trades) > 0 else 0
    avg_win = winning_trades['pnl'].mean() if not winning_trades.empty else 0
    avg_loss = abs(losing_trades['pnl'].mean()) if not losing_trades.empty else 0
    
    total_wins = winning_trades['pnl'].sum() if not winning_trades.empty else 0
    total_losses = abs(losing_trades['pnl'].sum()) if not losing_trades.empty else 0
    
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf') if total_wins > 0 else 0
    
    return {
        'win_rate': round(win_rate * 100, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': round(profit_factor, 2),
        'total_trades': len(trades)
    }


# ═══════════════════════════════════════════════════════════════════
# STRATEGY PAYOFF CALCULATIONS
# ═══════════════════════════════════════════════════════════════════

def calculate_strategy_payoff(
    positions: pd.DataFrame,
    spot_range: np.ndarray
) -> pd.DataFrame:
    """
    Calculate payoff diagram for multi-leg strategy.
    
    Args:
        positions: DataFrame with position details
        spot_range: Array of spot prices to calculate payoff for
    
    Returns:
        DataFrame with spot prices and corresponding payoffs
    """
    payoffs = pd.DataFrame({'spot': spot_range, 'payoff': 0.0})
    
    for _, pos in positions.iterrows():
        strike = pos['strike']
        option_type = pos['option_type']
        quantity = pos['quantity']
        entry_price = pos['entry_price']
        position_type = pos['position_type']  # 'long' or 'short'
        
        # Calculate intrinsic value at each spot price
        if option_type == 'CE':
            intrinsic = np.maximum(spot_range - strike, 0)
        else:  # PE
            intrinsic = np.maximum(strike - spot_range, 0)
        
        # Adjust for long/short
        if position_type == 'short':
            leg_payoff = (entry_price - intrinsic) * quantity
        else:  # long
            leg_payoff = (intrinsic - entry_price) * quantity
        
        payoffs['payoff'] += leg_payoff
    
    return payoffs
