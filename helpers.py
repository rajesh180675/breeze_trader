"""
Helper Functions & Utilities
=============================
Position detection, P&L, option chain processing, formatting.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import pytz
import logging

import app_config as C
from analytics import calculate_greeks, estimate_implied_volatility

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SAFE TYPE CONVERTERS
# ═══════════════════════════════════════════════════════════════════

def safe_int(value: Any, default: int = 0) -> int:
    """
    Safely convert value to integer.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
    
    Returns:
        Integer value
    """
    if value is None:
        return default
    
    try:
        # Handle string with commas or spaces
        if isinstance(value, str):
            value = value.replace(',', '').replace(' ', '').strip()
        return int(float(value))
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safely convert value to float.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
    
    Returns:
        Float value
    """
    if value is None:
        return default
    
    try:
        # Handle string with commas or spaces
        if isinstance(value, str):
            value = value.replace(',', '').replace(' ', '').strip()
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """
    Safely convert value to string.
    
    Args:
        value: Value to convert
        default: Default value if None
    
    Returns:
        String value
    """
    if value is None:
        return default
    return str(value).strip()


# ═══════════════════════════════════════════════════════════════════
# API RESPONSE PARSER
# ═══════════════════════════════════════════════════════════════════

class APIResponse:
    """
    Normalized API response handler.
    Handles both dict and list responses from Breeze API.
    """
    
    def __init__(self, raw_response: Dict[str, Any]):
        """
        Initialize response parser.
        
        Args:
            raw_response: Raw API response dictionary
        """
        self.raw = raw_response
        self.success = raw_response.get("success", False)
        self.message = raw_response.get("message", "Unknown error")
        self.error_code = raw_response.get("error_code")
        
        # Parse data
        self._data = raw_response.get("data", {})
        
        # Extract Success field (can be dict or list)
        if isinstance(self._data, dict):
            self._success_data = self._data.get("Success")
        else:
            self._success_data = None
    
    @property
    def data(self) -> Dict[str, Any]:
        """
        Get first record as dictionary.
        
        Returns:
            Dictionary of first record, or empty dict
        """
        if not self.success:
            return {}
        
        # If Success is a dict, return it
        if isinstance(self._success_data, dict):
            return self._success_data
        
        # If Success is a list with items, return first
        if isinstance(self._success_data, list) and self._success_data:
            if isinstance(self._success_data[0], dict):
                return self._success_data[0]
        
        # If no Success field, return raw data
        if isinstance(self._data, dict):
            return self._data
        
        return {}
    
    @property
    def items(self) -> List[Dict[str, Any]]:
        """
        Get all records as list of dictionaries.
        
        Returns:
            List of record dictionaries
        """
        if not self.success:
            return []
        
        # If Success is a list, return it
        if isinstance(self._success_data, list):
            return [item for item in self._success_data if isinstance(item, dict)]
        
        # If Success is a dict, wrap in list
        if isinstance(self._success_data, dict):
            return [self._success_data]
        
        return []
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get value from first record.
        
        Args:
            key: Key to retrieve
            default: Default value if key not found
        
        Returns:
            Value or default
        """
        return self.data.get(key, default)
    
    def is_empty(self) -> bool:
        """Check if response contains no data."""
        return not self.items and not self.data


# ═══════════════════════════════════════════════════════════════════
# POSITION DETECTION & ANALYSIS
# ═══════════════════════════════════════════════════════════════════

def detect_position_type(position: Dict[str, Any]) -> str:
    """
    Detect if position is LONG or SHORT.
    
    Breeze API returns positive quantity for both long and short.
    Must check action field and other indicators.
    
    Priority:
        1. action field (most reliable)
        2. sell_quantity vs buy_quantity comparison
        3. open_sell_qty vs open_buy_qty comparison
        4. position_type or segment fields
        5. quantity sign (fallback)
    
    Args:
        position: Position dictionary from API
    
    Returns:
        'long' or 'short'
    """
    # Check action field first (most reliable)
    action = safe_str(position.get("action")).lower()
    if action == "sell":
        return "short"
    if action == "buy":
        return "long"
    
    # Check position_type or segment fields
    for field in ("position_type", "segment"):
        value = safe_str(position.get(field)).lower()
        if "short" in value or "sell" in value:
            return "short"
        if "long" in value or "buy" in value:
            return "long"
    
    # Compare sell vs buy quantities
    sell_qty = safe_int(position.get("sell_quantity", 0))
    buy_qty = safe_int(position.get("buy_quantity", 0))
    
    if sell_qty > 0 and buy_qty == 0:
        return "short"
    if buy_qty > 0 and sell_qty == 0:
        return "long"
    if sell_qty > buy_qty:
        return "short"
    if buy_qty > sell_qty:
        return "long"
    
    # Compare open quantities
    open_sell = safe_int(position.get("open_sell_qty", 0))
    open_buy = safe_int(position.get("open_buy_qty", 0))
    
    if open_sell > open_buy:
        return "short"
    if open_buy > open_sell:
        return "long"
    
    # Check quantity sign (fallback)
    qty = safe_int(position.get("quantity", 0))
    if qty < 0:
        return "short"
    
    # Default to long if uncertain (log warning)
    log.warning(f"Position type unclear, defaulting to LONG: {position.get('stock_code')} "
                f"{position.get('strike_price')} {position.get('right')}")
    return "long"


def get_closing_action(position_type: str) -> str:
    """
    Get action needed to close position.
    
    Args:
        position_type: 'long' or 'short'
    
    Returns:
        'buy' or 'sell'
    """
    return "buy" if position_type == "short" else "sell"


def calculate_pnl(
    position_type: str,
    avg_price: float,
    current_price: float,
    quantity: int
) -> float:
    """
    Calculate P&L for position.
    
    Args:
        position_type: 'long' or 'short'
        avg_price: Average entry price
        current_price: Current market price (LTP)
        quantity: Position quantity (always use absolute value)
    
    Returns:
        P&L amount
    
    Formula:
        Long:  (Current - Avg) × Qty
        Short: (Avg - Current) × Qty
    """
    qty = abs(quantity)
    
    if position_type == "short":
        pnl = (avg_price - current_price) * qty
    else:  # long
        pnl = (current_price - avg_price) * qty
    
    return pnl


def calculate_unrealized_pnl(positions: List[Dict[str, Any]]) -> float:
    """
    Calculate total unrealized P&L across all positions.
    
    Args:
        positions: List of position dictionaries
    
    Returns:
        Total unrealized P&L
    """
    total_pnl = 0.0
    
    for pos in positions:
        qty = safe_int(pos.get("quantity", 0))
        if qty == 0:
            continue
        
        pos_type = detect_position_type(pos)
        avg = safe_float(pos.get("average_price", 0))
        ltp = safe_float(pos.get("ltp", avg))
        
        pnl = calculate_pnl(pos_type, avg, ltp, qty)
        total_pnl += pnl
    
    return total_pnl


def calculate_margin_used(positions: List[Dict[str, Any]]) -> float:
    """
    Estimate margin used by positions.
    
    Args:
        positions: List of position dictionaries
    
    Returns:
        Estimated margin used
    """
    margin = 0.0
    
    for pos in positions:
        # Use margin field if available
        pos_margin = safe_float(pos.get("margin", 0))
        if pos_margin > 0:
            margin += pos_margin
        else:
            # Estimate based on position value
            qty = abs(safe_int(pos.get("quantity", 0)))
            avg_price = safe_float(pos.get("average_price", 0))
            
            # Rough estimate: 20% of position value for options
            margin += qty * avg_price * 0.20
    
    return margin


# ═══════════════════════════════════════════════════════════════════
# OPTION CHAIN PROCESSING
# ═══════════════════════════════════════════════════════════════════

def process_option_chain(raw_data: Dict[str, Any]) -> pd.DataFrame:
    """
    Parse raw option chain API response into clean DataFrame.
    
    Args:
        raw_data: Raw API response data
    
    Returns:
        Clean DataFrame with option chain data
    """
    if not raw_data or "Success" not in raw_data:
        return pd.DataFrame()
    
    records = raw_data.get("Success", [])
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    
    if df.empty:
        return df
    
    # Convert numeric columns
    numeric_cols = [
        "strike_price", "ltp", "best_bid_price", "best_offer_price",
        "open", "high", "low", "close", "previous_close",
        "volume", "open_interest", "ltp_percent_change",
        "oi_change", "iv"
    ]
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    # Normalize option type field
    if "right" in df.columns:
        df["right"] = df["right"].str.strip().str.capitalize()
    
    return df


def create_pivot_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create traditional option chain pivot table.
    
    Layout:
        Call OI | Call Vol | Call LTP | Call Bid | Call Ask | 
        STRIKE | 
        Put Ask | Put Bid | Put LTP | Put Vol | Put OI
    
    Args:
        df: Processed option chain DataFrame
    
    Returns:
        Pivoted DataFrame
    """
    if df.empty:
        return df
    
    required_cols = ["strike_price", "right"]
    if not all(col in df.columns for col in required_cols):
        return df
    
    # Define columns to pivot
    pivot_fields = {
        "open_interest": "OI",
        "volume": "Vol",
        "ltp": "LTP",
        "best_bid_price": "Bid",
        "best_offer_price": "Ask",
        "iv": "IV"
    }
    
    # Keep only available fields
    available_fields = {k: v for k, v in pivot_fields.items() if k in df.columns}
    
    if not available_fields:
        return df
    
    # Separate calls and puts
    calls = df[df["right"] == "Call"].set_index("strike_price")
    puts = df[df["right"] == "Put"].set_index("strike_price")
    
    # Get all unique strikes
    all_strikes = sorted(df["strike_price"].dropna().unique())
    
    # Create result DataFrame
    result = pd.DataFrame({"Strike": all_strikes})
    result = result.set_index("Strike")
    
    # Add call columns (left side)
    for field, label in available_fields.items():
        col_name = f"C_{label}"
        if field in calls.columns:
            result[col_name] = calls[field]
    
    # Add put columns (right side)
    for field, label in available_fields.items():
        col_name = f"P_{label}"
        if field in puts.columns:
            result[col_name] = puts[field]
    
    # Fill NaN with 0
    result = result.fillna(0)
    
    # Reset index to make Strike a column
    result = result.reset_index()
    
    # Reorder columns: Calls | Strike | Puts
    call_cols = [c for c in result.columns if c.startswith("C_")]
    put_cols = [c for c in result.columns if c.startswith("P_")]
    
    result = result[call_cols + ["Strike"] + put_cols]
    
    return result


def calculate_pcr(df: pd.DataFrame) -> float:
    """
    Calculate Put-Call Ratio from open interest.
    
    PCR = Total Put OI / Total Call OI
    
    Args:
        df: Option chain DataFrame
    
    Returns:
        PCR value
    """
    if df.empty or "right" not in df.columns or "open_interest" not in df.columns:
        return 0.0
    
    call_oi = df[df["right"] == "Call"]["open_interest"].sum()
    put_oi = df[df["right"] == "Put"]["open_interest"].sum()
    
    if call_oi == 0:
        return 0.0
    
    return put_oi / call_oi


def calculate_max_pain(df: pd.DataFrame) -> int:
    """
    Calculate Max Pain strike.
    
    Max Pain = Strike where total option writer loss is minimized.
    
    Args:
        df: Option chain DataFrame
    
    Returns:
        Max pain strike price
    """
    if df.empty or "strike_price" not in df.columns or "right" not in df.columns:
        return 0
    
    if "open_interest" not in df.columns:
        return 0
    
    strikes = df["strike_price"].dropna().unique()
    
    if len(strikes) == 0:
        return 0
    
    pain_values = {}
    
    for strike in strikes:
        # ITM calls: strikes below current
        itm_calls = df[(df["right"] == "Call") & (df["strike_price"] < strike)]
        call_pain = ((strike - itm_calls["strike_price"]) * itm_calls["open_interest"]).sum()
        
        # ITM puts: strikes above current
        itm_puts = df[(df["right"] == "Put") & (df["strike_price"] > strike)]
        put_pain = ((itm_puts["strike_price"] - strike) * itm_puts["open_interest"]).sum()
        
        pain_values[strike] = call_pain + put_pain
    
    if not pain_values:
        return 0
    
    # Strike with minimum pain
    max_pain_strike = min(pain_values, key=pain_values.get)
    
    return int(max_pain_strike)


def estimate_atm_strike(df: pd.DataFrame) -> float:
    """
    Estimate ATM strike from option chain.
    
    Uses the strike where Call LTP ≈ Put LTP.
    
    Args:
        df: Option chain DataFrame
    
    Returns:
        Estimated ATM strike
    """
    if df.empty or "strike_price" not in df.columns:
        return 0.0
    
    if "right" not in df.columns or "ltp" not in df.columns:
        # Fallback to middle strike
        strikes = sorted(df["strike_price"].unique())
        return strikes[len(strikes) // 2] if strikes else 0.0
    
    # Get call and put LTPs
    calls = df[df["right"] == "Call"][["strike_price", "ltp"]].set_index("strike_price")
    puts = df[df["right"] == "Put"][["strike_price", "ltp"]].set_index("strike_price")
    
    # Join and find where difference is minimum
    combined = calls.join(puts, lsuffix="_call", rsuffix="_put").dropna()
    
    if combined.empty:
        strikes = sorted(df["strike_price"].unique())
        return strikes[len(strikes) // 2] if strikes else 0.0
    
    combined["diff"] = abs(combined["ltp_call"] - combined["ltp_put"])
    atm = combined["diff"].idxmin()
    
    return float(atm)


def add_greeks_to_chain(
    df: pd.DataFrame,
    spot_price: float,
    expiry_date: str
) -> pd.DataFrame:
    """
    Add Greeks to option chain DataFrame.
    
    Args:
        df: Option chain DataFrame
        spot_price: Current spot price
        expiry_date: Expiry date (YYYY-MM-DD)
    
    Returns:
        DataFrame with Greeks columns added
    """
    if df.empty:
        return df
    
    # Calculate time to expiry
    try:
        expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
        now = datetime.now(C.IST)
        time_to_expiry = (expiry - now).days / C.DAYS_PER_YEAR
        
        if time_to_expiry < 0:
            time_to_expiry = 0
    except Exception:
        time_to_expiry = 0.1  # Default to ~36 days
    
    # Add Greeks for each row
    greeks_list = []
    
    for _, row in df.iterrows():
        strike = row["strike_price"]
        option_type = C.normalize_option_type(row["right"])
        ltp = row["ltp"]
        
        # Estimate IV if not available
        if "iv" in row and row["iv"] > 0:
            iv = row["iv"] / 100  # Convert from percentage
        else:
            # Estimate IV from LTP
            try:
                iv = estimate_implied_volatility(
                    ltp, spot_price, strike, time_to_expiry, option_type
                )
            except Exception:
                iv = 0.25  # Default 25%
        
        # Calculate Greeks
        try:
            greeks = calculate_greeks(
                spot_price, strike, time_to_expiry, iv, option_type
            )
        except Exception:
            greeks = {
                'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0
            }
        
        greeks_list.append(greeks)
    
    # Add Greeks as new columns
    greeks_df = pd.DataFrame(greeks_list)
    df = pd.concat([df.reset_index(drop=True), greeks_df], axis=1)
    
    return df


# ═══════════════════════════════════════════════════════════════════
# MARKET STATUS & UTILITIES
# ═══════════════════════════════════════════════════════════════════

def get_market_status() -> str:
    """
    Get current market status with emoji indicator.
    
    Returns:
        Status string with emoji
    """
    now = datetime.now(C.IST)
    
    # Weekend check
    if now.weekday() >= 5:
        return "🔴 Closed (Weekend)"
    
    # Define market hours
    pre_market_start = now.replace(
        hour=C.MARKET_PRE_OPEN_START[0],
        minute=C.MARKET_PRE_OPEN_START[1],
        second=0,
        microsecond=0
    )
    
    market_open = now.replace(
        hour=C.MARKET_OPEN[0],
        minute=C.MARKET_OPEN[1],
        second=0,
        microsecond=0
    )
    
    market_close = now.replace(
        hour=C.MARKET_CLOSE[0],
        minute=C.MARKET_CLOSE[1],
        second=0,
        microsecond=0
    )
    
    # Determine status
    if now < pre_market_start:
        return "🟡 Pre-Market (Opens 9:00 AM)"
    elif now < market_open:
        return "🟠 Pre-Open (Opens 9:15 AM)"
    elif now <= market_close:
        return "🟢 Market Open"
    else:
        return "🔴 Closed (Opens Tomorrow 9:15 AM)"


def format_currency(value: float) -> str:
    """
    Format currency in Indian notation.
    
    Args:
        value: Amount to format
    
    Returns:
        Formatted string (e.g., "₹5.23L", "₹1.25Cr")
    """
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    
    if abs_val >= C.CURRENCY_FORMATS['crore']:
        return f"{sign}₹{abs_val / C.CURRENCY_FORMATS['crore']:.2f}Cr"
    elif abs_val >= C.CURRENCY_FORMATS['lakh']:
        return f"{sign}₹{abs_val / C.CURRENCY_FORMATS['lakh']:.2f}L"
    elif abs_val >= C.CURRENCY_FORMATS['thousand']:
        return f"{sign}₹{abs_val / C.CURRENCY_FORMATS['thousand']:.1f}K"
    else:
        return f"{sign}₹{abs_val:.2f}"


def format_expiry(expiry_date: str) -> str:
    """
    Format expiry date for display.
    
    Args:
        expiry_date: Date string (YYYY-MM-DD or DD-Mon-YYYY)
    
    Returns:
        Formatted string (e.g., "17 Feb 2026 (Tuesday)")
    """
    formats_to_try = ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"]
    
    for fmt in formats_to_try:
        try:
            dt = datetime.strptime(expiry_date, fmt)
            return dt.strftime("%d %b %Y (%A)")
        except ValueError:
            continue
    
    # Return as-is if parsing fails
    return expiry_date


def format_percentage(value: float, decimals: int = 2) -> str:
    """
    Format percentage with color indicator.
    
    Args:
        value: Percentage value
        decimals: Decimal places
    
    Returns:
        Formatted string with sign
    """
    return f"{value:+.{decimals}f}%"


def calculate_days_to_expiry(expiry_date: str) -> int:
    """
    Calculate days remaining to expiry.
    
    Args:
        expiry_date: Expiry date (YYYY-MM-DD)
    
    Returns:
        Number of days
    """
    try:
        expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
        now = datetime.now(C.IST)
        delta = (expiry - now).days
        return max(0, delta)
    except Exception:
        return 0
