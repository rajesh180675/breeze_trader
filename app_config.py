"""
Configuration — instruments, expiry logic, constants.
All pure logic. No external dependencies.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional
from dataclasses import dataclass
import pytz

IST = pytz.timezone("Asia/Kolkata")

MARKET_PRE_OPEN_START = (9, 0)
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)

SESSION_TIMEOUT_SECONDS = 28800
SESSION_WARNING_SECONDS = 25200

OC_CACHE_TTL_SECONDS = 30
QUOTE_CACHE_TTL_SECONDS = 5
POSITION_CACHE_TTL_SECONDS = 10
FUNDS_CACHE_TTL_SECONDS = 60
SPOT_CACHE_TTL_SECONDS = 30

MAX_ACTIVITY_LOG_ENTRIES = 100
MAX_LOTS_PER_ORDER = 1000
MIN_LOTS_PER_ORDER = 1
RISK_FREE_RATE = 0.065
DAYS_PER_YEAR = 365


@dataclass(frozen=True)
class InstrumentConfig:
    display_name: str
    api_code: str
    exchange: Literal['NFO', 'BFO']
    lot_size: int
    tick_size: float
    strike_gap: int
    expiry_day: Literal['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    description: str
    spot_code: str = ""
    spot_exchange: str = ""
    min_strike: int = 0
    max_strike: int = 999999


INSTRUMENTS: Dict[str, InstrumentConfig] = {
    "NIFTY": InstrumentConfig(
        "NIFTY", "NIFTY", "NFO", 65, 0.05, 50, "Tuesday",
        "NIFTY 50 Index", "NIFTY", "NSE", 15000, 30000),
    "BANKNIFTY": InstrumentConfig(
        "BANKNIFTY", "BANKNIFTY", "NFO", 15, 0.05, 100, "Wednesday",
        "Bank NIFTY Index", "CNXBAN", "NSE", 30000, 60000),
    "FINNIFTY": InstrumentConfig(
        "FINNIFTY", "FINNIFTY", "NFO", 25, 0.05, 50, "Tuesday",
        "NIFTY Financial Services", "FINNIFTY", "NSE", 15000, 30000),
    "MIDCPNIFTY": InstrumentConfig(
        "MIDCPNIFTY", "MIDCPNIFTY", "NFO", 50, 0.05, 25, "Monday",
        "NIFTY Midcap Select", "MIDCPNIFTY", "NSE", 8000, 20000),
    "SENSEX": InstrumentConfig(
        "SENSEX", "BSESEN", "BFO", 20, 0.05, 100, "Thursday",
        "BSE SENSEX", "BSESEN", "BSE", 50000, 100000),
    "BANKEX": InstrumentConfig(
        "BANKEX", "BANKEX", "BFO", 15, 0.05, 100, "Monday",
        "BSE BANKEX", "BANKEX", "BSE", 40000, 80000),
}

DAY_NUM = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4}


def get_instrument(name: str) -> InstrumentConfig:
    if name not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {name}")
    return INSTRUMENTS[name]


def get_next_expiries(instrument_name: str, count: int = 5) -> List[str]:
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    target_day = DAY_NUM[inst.expiry_day]
    now = datetime.now(IST)
    days_ahead = (target_day - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= 15 and now.minute >= 30:
        days_ahead = 7
    next_exp = now + timedelta(days=days_ahead) if days_ahead > 0 else now
    return [(next_exp + timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(count)]


def api_code_to_display(api_code: str) -> str:
    if not api_code:
        return ""
    for name, config in INSTRUMENTS.items():
        if config.api_code == api_code:
            return name
    return api_code


def display_to_api_code(display_name: str) -> str:
    if display_name in INSTRUMENTS:
        return INSTRUMENTS[display_name].api_code
    return display_name


def normalize_option_type(option_str: Optional[str]) -> str:
    if option_str is None or option_str == "":
        return "N/A"
    s = str(option_str).strip().lower()
    if not s:
        return "N/A"
    if s in ('call', 'ce', 'c'):
        return 'CE'
    elif s in ('put', 'pe', 'p'):
        return 'PE'
    return str(option_str).upper()


def is_option_position(position: Dict) -> bool:
    product_type = str(position.get("product_type", "")).lower()
    if product_type == "options":
        return True
    segment = str(position.get("segment", "")).lower()
    if segment == "fno" and position.get("right") is not None:
        return True
    return False


def is_equity_position(position: Dict) -> bool:
    segment = str(position.get("segment", "")).lower()
    product_type = str(position.get("product_type", "")).lower()
    if segment == "equity" or product_type in ("easymargin", "cash", "delivery", "margin"):
        return True
    return False


def validate_strike(instrument_name: str, strike: int) -> bool:
    try:
        inst = get_instrument(instrument_name)
        return inst.min_strike <= strike <= inst.max_strike and strike % inst.strike_gap == 0
    except KeyError:
        return False


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0)
    c = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0)
    return o <= now <= c


class ErrorMessages:
    NOT_CONNECTED = "Not connected to Breeze API"
    CONNECTION_FAILED = "Failed to connect: {error}"
    SESSION_EXPIRED = "Session has expired. Please reconnect"
    ORDER_FAILED = "Order placement failed: {error}"
    CANCEL_FAILED = "Order cancellation failed: {error}"
    MODIFY_FAILED = "Order modification failed: {error}"
    FETCH_FAILED = "Failed to fetch data: {error}"
