"""
Analytics — Black-Scholes pricing, Greeks, robust IV solver.
Pure math. Imports only app_config and standard libs.

v8.0 changes:
- IV solver uses Newton-Raphson + Brent's fallback
- Convergence reporting (not silent failure)
- Proper deep OTM handling
- Numerical stability guards on d1/d2
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Dict, Tuple
from dataclasses import dataclass
import logging

import app_config as C

log = logging.getLogger(__name__)


def _d1_d2(spot: float, strike: float, tte: float, vol: float,
           r: float) -> Tuple[float, float]:
    """Compute d1, d2 with clamping for numerical stability."""
    if tte < 1e-10 or vol < 1e-10 or spot <= 0 or strike <= 0:
        if spot > strike:
            return 10.0, 10.0
        elif spot < strike:
            return -10.0, -10.0
        return 0.0, 0.0
    sqrt_t = np.sqrt(tte)
    d1 = (np.log(spot / strike) + (r + 0.5 * vol ** 2) * tte) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    return np.clip(d1, -10.0, 10.0), np.clip(d2, -10.0, 10.0)


def bs_price(spot: float, strike: float, tte: float, vol: float,
             option_type: str, r: float = C.RISK_FREE_RATE) -> float:
    """Black-Scholes option price."""
    d1, d2 = _d1_d2(spot, strike, tte, vol, r)
    disc = np.exp(-r * tte)
    if option_type == "CE":
        return max(0.0, spot * norm.cdf(d1) - strike * disc * norm.cdf(d2))
    return max(0.0, strike * disc * norm.cdf(-d2) - spot * norm.cdf(-d1))


def bs_vega_raw(spot: float, strike: float, tte: float, vol: float,
                r: float = C.RISK_FREE_RATE) -> float:
    """Raw vega = S·φ(d1)·√T. Used by IV solver."""
    if tte < 1e-10:
        return 0.0
    d1, _ = _d1_d2(spot, strike, tte, vol, r)
    return spot * norm.pdf(d1) * np.sqrt(tte)


def calculate_greeks(spot: float, strike: float, tte: float, vol: float,
                     option_type: str, r: float = C.RISK_FREE_RATE) -> Dict[str, float]:
    """
    All Greeks for a single option.
    Theta is daily. Vega is per 1% vol move. Rho is per 1% rate move.
    """
    if tte < 1e-10:
        if option_type == "CE":
            d = 1.0 if spot > strike else 0.0
        else:
            d = -1.0 if spot < strike else 0.0
        return {'delta': d, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0}

    d1, d2 = _d1_d2(spot, strike, tte, vol, r)
    sqrt_t = np.sqrt(tte)
    n_d1 = norm.pdf(d1)
    disc = np.exp(-r * tte)

    gamma = n_d1 / (spot * vol * sqrt_t) if (spot * vol * sqrt_t) > 0 else 0.0
    vega = spot * n_d1 * sqrt_t / 100.0

    if option_type == "CE":
        delta = norm.cdf(d1)
        theta = (-spot * n_d1 * vol / (2 * sqrt_t) -
                 r * strike * disc * norm.cdf(d2)) / C.DAYS_PER_YEAR
        rho = strike * tte * disc * norm.cdf(d2) / 100.0
    else:
        delta = norm.cdf(d1) - 1
        theta = (-spot * n_d1 * vol / (2 * sqrt_t) +
                 r * strike * disc * norm.cdf(-d2)) / C.DAYS_PER_YEAR
        rho = -strike * tte * disc * norm.cdf(-d2) / 100.0

    return {
        'delta': round(delta, 4), 'gamma': round(gamma, 6),
        'theta': round(theta, 4), 'vega': round(vega, 4),
        'rho': round(rho, 6)
    }


# ═══════════════════════════════════════════════════════════════
# IMPLIED VOLATILITY SOLVER
# ═══════════════════════════════════════════════════════════════

@dataclass
class IVResult:
    iv: float
    converged: bool
    iterations: int
    method: str
    price_error: float


def solve_iv(option_price: float, spot: float, strike: float,
             tte: float, option_type: str,
             r: float = C.RISK_FREE_RATE) -> IVResult:
    """
    Hybrid IV solver: Newton-Raphson first, Brent's fallback.
    Always returns a result with convergence metadata.
    """
    if option_price <= 0 or spot <= 0 or strike <= 0 or tte <= 0:
        return IVResult(0.20, False, 0, "default", float('inf'))

    # Intrinsic bound check
    if option_type == "CE":
        intrinsic = max(0, spot - strike * np.exp(-r * tte))
    else:
        intrinsic = max(0, strike * np.exp(-r * tte) - spot)
    if option_price < intrinsic * 0.99:
        return IVResult(0.01, False, 0, "sub_intrinsic", abs(option_price - intrinsic))

    # Phase 1: Newton-Raphson
    nr = _newton_raphson_iv(option_price, spot, strike, tte, option_type, r)
    if nr.converged:
        return nr

    # Phase 2: Brent's method
    return _brent_iv(option_price, spot, strike, tte, option_type, r)


def estimate_implied_volatility(option_price: float, spot: float, strike: float,
                                tte: float, option_type: str,
                                r: float = C.RISK_FREE_RATE) -> float:
    """Backward-compatible wrapper. Returns float IV."""
    return solve_iv(option_price, spot, strike, tte, option_type, r).iv


def _newton_raphson_iv(target: float, spot: float, strike: float,
                       tte: float, ot: str, r: float,
                       max_iter: int = 50, tol: float = 1e-8) -> IVResult:
    """Newton-Raphson with Brenner-Subrahmanyam initial guess."""
    vol = np.sqrt(2 * np.pi / tte) * (target / spot)
    vol = np.clip(vol, 0.01, 3.0)
    diff = 0.0

    for i in range(max_iter):
        price = bs_price(spot, strike, tte, vol, ot, r)
        diff = price - target
        if abs(diff) < tol:
            return IVResult(vol, True, i + 1, "newton", abs(diff))
        vega = bs_vega_raw(spot, strike, tte, vol, r)
        if vega < 1e-12:
            return IVResult(vol, False, i + 1, "nr_vega_collapse", abs(diff))
        step = diff / vega
        if abs(step) > vol * 0.5:
            step = np.sign(step) * vol * 0.5
        vol_new = np.clip(vol - step, 0.001, 5.0)
        if abs(vol_new - vol) < 1e-10:
            return IVResult(vol_new, True, i + 1, "newton", abs(diff))
        vol = vol_new

    return IVResult(vol, False, max_iter, "nr_max_iter", abs(diff))


def _brent_iv(target: float, spot: float, strike: float,
              tte: float, ot: str, r: float) -> IVResult:
    """Brent's method — guaranteed convergence within bracket."""
    def obj(vol):
        return bs_price(spot, strike, tte, vol, ot, r) - target

    try:
        lo, hi = 0.001, 5.0
        f_lo, f_hi = obj(lo), obj(hi)
        if f_lo * f_hi > 0:
            for test_hi in [1.0, 2.0, 5.0, 10.0]:
                if obj(lo) * obj(test_hi) < 0:
                    hi = test_hi
                    break
            else:
                best = lo if abs(f_lo) < abs(f_hi) else hi
                return IVResult(best, False, 0, "brent_no_bracket",
                                min(abs(f_lo), abs(f_hi)))

        iv, info = brentq(obj, lo, hi, xtol=1e-8, maxiter=100, full_output=True)
        return IVResult(iv, info.converged, info.iterations, "brent", abs(obj(iv)))
    except (ValueError, RuntimeError) as e:
        log.debug(f"Brent failed: {e}")
        return IVResult(0.20, False, 0, "brent_failed", float('inf'))


# ═══════════════════════════════════════════════════════════════
# PORTFOLIO / STRATEGY HELPERS
# ═══════════════════════════════════════════════════════════════

def calculate_portfolio_greeks_from_df(positions_df) -> Dict[str, float]:
    """Sum Greeks columns in a DataFrame."""
    import pandas as pd
    if positions_df is None or positions_df.empty:
        return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0}
    result = {}
    for g in ('delta', 'gamma', 'theta', 'vega', 'rho'):
        if g in positions_df.columns and 'quantity' in positions_df.columns:
            result[g] = float((positions_df[g] * positions_df['quantity']).sum())
        else:
            result[g] = 0.0
    return result


def calculate_strategy_payoff(positions_df, spot_range) -> 'pd.DataFrame':
    """Payoff at expiry for multi-leg strategy."""
    import pandas as pd
    payoffs = pd.DataFrame({'spot': spot_range, 'payoff': 0.0})
    for _, pos in positions_df.iterrows():
        strike = pos.get('strike', 0)
        ot = pos.get('option_type', 'CE')
        qty = pos.get('quantity', 0)
        entry = pos.get('entry_price', 0)
        pt = pos.get('position_type', 'long')
        if ot == 'CE':
            intrinsic = np.maximum(spot_range - strike, 0)
        else:
            intrinsic = np.maximum(strike - spot_range, 0)
        if pt == 'short':
            payoffs['payoff'] += (entry - intrinsic) * qty
        else:
            payoffs['payoff'] += (intrinsic - entry) * qty
    return payoffs


def calculate_var(returns, confidence=0.95) -> float:
    if returns is None or len(returns) == 0:
        return 0.0
    return float(np.percentile(returns, (1 - confidence) * 100))


def calculate_sharpe(returns, risk_free=C.RISK_FREE_RATE) -> float:
    if returns is None or len(returns) == 0 or np.std(returns) == 0:
        return 0.0
    return float((np.mean(returns) * 252 - risk_free) / (np.std(returns) * np.sqrt(252)))
