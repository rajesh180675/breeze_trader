"""
Helpers — type conversion, API response parsing, option chain processing, formatting.
Imports analytics for Greek calculations on chain data.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

import app_config as C
from analytics import calculate_greeks, estimate_implied_volatility

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# SAFE CONVERTERS
# ═══════════════════════════════════════════════════════════════

def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '').strip()
        return int(float(value))
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '').strip()
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


# ═══════════════════════════════════════════════════════════════
# API RESPONSE PARSER
# ═══════════════════════════════════════════════════════════════

class APIResponse:
    """Parse ICICI Breeze response into clean accessors."""

    def __init__(self, raw_response: Dict[str, Any]):
        self.raw = raw_response
        self.success = raw_response.get("success", False)
        self.message = raw_response.get("message", "")
        self._data = raw_response.get("data", {})
        self._success_data = (
            self._data.get("Success") if isinstance(self._data, dict) else None
        )

    @property
    def data(self) -> Dict:
        if not self.success:
            return {}
        if isinstance(self._success_data, dict):
            return self._success_data
        if isinstance(self._success_data, list) and self._success_data:
            return self._success_data[0] if isinstance(self._success_data[0], dict) else {}
        return self._data if isinstance(self._data, dict) else {}

    @property
    def items(self) -> List[Dict]:
        if not self.success:
            return []
        if isinstance(self._success_data, list):
            return [i for i in self._success_data if isinstance(i, dict)]
        if isinstance(self._success_data, dict):
            return [self._success_data]
        return []

    def get(self, key, default=None):
        return self.data.get(key, default)


# ═══════════════════════════════════════════════════════════════
# FUNDS
# ═══════════════════════════════════════════════════════════════

def parse_funds(response: Dict) -> Dict[str, float]:
    parsed = APIResponse(response)
    d = parsed.data
    return {
        "total_balance": safe_float(d.get("total_bank_balance", 0)),
        "allocated_equity": safe_float(d.get("allocated_equity", 0)),
        "allocated_fno": safe_float(d.get("allocated_fno", 0)),
        "unallocated": safe_float(d.get("unallocated_balance", 0)),
        "block_equity": safe_float(d.get("block_by_trade_equity", 0)),
        "block_fno": safe_float(d.get("block_by_trade_fno", 0)),
    }


# ═══════════════════════════════════════════════════════════════
# POSITION LOGIC
# ═══════════════════════════════════════════════════════════════

def detect_position_type(position: Dict) -> str:
    action = safe_str(position.get("action")).lower()
    if action == "sell":
        return "short"
    if action == "buy":
        return "long"
    for f in ("position_type", "segment"):
        v = safe_str(position.get(f)).lower()
        if "short" in v or "sell" in v:
            return "short"
        if "long" in v or "buy" in v:
            return "long"
    sell_q = safe_int(position.get("sell_quantity", 0))
    buy_q = safe_int(position.get("buy_quantity", 0))
    if sell_q > buy_q:
        return "short"
    if buy_q > sell_q:
        return "long"
    qty = safe_int(position.get("quantity", 0))
    if qty < 0:
        return "short"
    return "long"


def get_closing_action(position_type: str) -> str:
    return "buy" if position_type == "short" else "sell"


def calculate_pnl(position_type: str, avg_price: float,
                  current_price: float, quantity: int) -> float:
    qty = abs(quantity)
    if position_type == "short":
        return (avg_price - current_price) * qty
    return (current_price - avg_price) * qty


# ═══════════════════════════════════════════════════════════════
# OPTION CHAIN
# ═══════════════════════════════════════════════════════════════

def process_option_chain(raw_data: Dict) -> pd.DataFrame:
    if not raw_data or "Success" not in raw_data:
        return pd.DataFrame()
    records = raw_data.get("Success", [])
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if df.empty:
        return df
    numeric_cols = [
        "strike_price", "ltp", "best_bid_price", "best_offer_price",
        "open", "high", "low", "close", "volume", "open_interest",
        "ltp_percent_change", "oi_change", "iv"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "right" in df.columns:
        df["right"] = df["right"].str.strip().str.capitalize()
    return df


def create_pivot_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "strike_price" not in df.columns or "right" not in df.columns:
        return pd.DataFrame()
    pivot_fields = {
        "open_interest": "OI", "volume": "Vol", "ltp": "LTP",
        "best_bid_price": "Bid", "best_offer_price": "Ask"
    }
    available = {k: v for k, v in pivot_fields.items() if k in df.columns}
    if not available:
        return df
    calls = df[df["right"] == "Call"].set_index("strike_price")
    puts = df[df["right"] == "Put"].set_index("strike_price")
    all_strikes = sorted(df["strike_price"].dropna().unique())
    result = pd.DataFrame({"Strike": all_strikes}).set_index("Strike")
    for field, label in available.items():
        if field in calls.columns:
            result[f"C_{label}"] = calls[field]
        if field in puts.columns:
            result[f"P_{label}"] = puts[field]
    result = result.fillna(0).reset_index()
    call_cols = [c for c in result.columns if c.startswith("C_")]
    put_cols = [c for c in result.columns if c.startswith("P_")]
    return result[call_cols + ["Strike"] + put_cols]


def calculate_pcr(df: pd.DataFrame) -> float:
    if df.empty or "right" not in df.columns or "open_interest" not in df.columns:
        return 0.0
    call_oi = df[df["right"] == "Call"]["open_interest"].sum()
    put_oi = df[df["right"] == "Put"]["open_interest"].sum()
    return put_oi / call_oi if call_oi > 0 else 0.0


def calculate_max_pain(df: pd.DataFrame) -> int:
    if df.empty or "strike_price" not in df.columns or "open_interest" not in df.columns:
        return 0
    strikes = df["strike_price"].dropna().unique()
    if len(strikes) == 0:
        return 0
    pain = {}
    for s in strikes:
        cp = ((s - df[(df["right"] == "Call") & (df["strike_price"] < s)]["strike_price"]) *
              df[(df["right"] == "Call") & (df["strike_price"] < s)]["open_interest"]).sum()
        pp = ((df[(df["right"] == "Put") & (df["strike_price"] > s)]["strike_price"] - s) *
              df[(df["right"] == "Put") & (df["strike_price"] > s)]["open_interest"]).sum()
        pain[s] = cp + pp
    return int(min(pain, key=pain.get)) if pain else 0


def estimate_atm_strike(df: pd.DataFrame) -> float:
    if df.empty or "strike_price" not in df.columns:
        return 0.0
    if "right" not in df.columns or "ltp" not in df.columns:
        strikes = sorted(df["strike_price"].unique())
        return strikes[len(strikes) // 2] if strikes else 0.0
    calls = df[df["right"] == "Call"][["strike_price", "ltp"]].set_index("strike_price")
    puts = df[df["right"] == "Put"][["strike_price", "ltp"]].set_index("strike_price")
    combined = calls.join(puts, lsuffix="_call", rsuffix="_put").dropna()
    if combined.empty:
        strikes = sorted(df["strike_price"].unique())
        return strikes[len(strikes) // 2] if strikes else 0.0
    combined["diff"] = abs(combined["ltp_call"] - combined["ltp_put"])
    return float(combined["diff"].idxmin())


def add_greeks_to_chain(df: pd.DataFrame, spot_price: float,
                        expiry_date: str) -> pd.DataFrame:
    if df.empty:
        return df
    try:
        expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
        tte = max((expiry - datetime.now(C.IST).replace(tzinfo=None)).days / C.DAYS_PER_YEAR, 0.001)
    except Exception:
        tte = 0.05
    greeks_list = []
    for _, row in df.iterrows():
        strike = row.get("strike_price", 0)
        ot = C.normalize_option_type(row.get("right"))
        ltp = row.get("ltp", 0)
        if ot in ("CE", "PE") and strike > 0 and spot_price > 0 and ltp > 0:
            try:
                iv_raw = row.get("iv", 0)
                iv = iv_raw / 100 if iv_raw > 1 else (
                    estimate_implied_volatility(ltp, spot_price, strike, tte, ot)
                    if iv_raw <= 0 else iv_raw
                )
                greeks_list.append(calculate_greeks(spot_price, strike, tte, iv, ot))
            except Exception:
                greeks_list.append({'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0})
        else:
            greeks_list.append({'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0})
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(greeks_list)], axis=1)


# ═══════════════════════════════════════════════════════════════
# FORMATTING
# ═══════════════════════════════════════════════════════════════

def get_market_status() -> str:
    now = datetime.now(C.IST)
    if now.weekday() >= 5:
        return "🔴 Closed (Weekend)"
    o = now.replace(hour=C.MARKET_OPEN[0], minute=C.MARKET_OPEN[1], second=0, microsecond=0)
    c = now.replace(hour=C.MARKET_CLOSE[0], minute=C.MARKET_CLOSE[1], second=0, microsecond=0)
    p = now.replace(hour=C.MARKET_PRE_OPEN_START[0], minute=C.MARKET_PRE_OPEN_START[1],
                    second=0, microsecond=0)
    if now < p:
        return "🟡 Pre-Market"
    if now < o:
        return "🟠 Pre-Open"
    if now <= c:
        return "🟢 Market Open"
    return "🔴 Closed"


def format_currency(value: float) -> str:
    av = abs(value)
    sign = "-" if value < 0 else ""
    if av >= 1e7:
        return f"{sign}₹{av / 1e7:.2f}Cr"
    if av >= 1e5:
        return f"{sign}₹{av / 1e5:.2f}L"
    if av >= 1e3:
        return f"{sign}₹{av / 1e3:.1f}K"
    return f"{sign}₹{av:.2f}"


def format_expiry(date_str: str) -> str:
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%d %b %Y (%A)")
        except ValueError:
            continue
    return date_str


def calculate_days_to_expiry(expiry_date: str) -> int:
    if not expiry_date:
        return 0
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%dT%H:%M:%S"]:
        try:
            expiry = datetime.strptime(expiry_date.strip()[:10], fmt[:len(expiry_date.strip()[:10])])
            return max(0, (expiry - datetime.now(C.IST).replace(tzinfo=None)).days)
        except ValueError:
            continue
    return 0
