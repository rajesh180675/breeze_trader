"""
Configuration — instruments, expiry logic, session state defaults.
FIXED: Handles None values in normalize_option_type
ENHANCED: Added better validation and error handling
"""

from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional
from dataclasses import dataclass
import pytz

IST = pytz.timezone("Asia/Kolkata")

# ═══════════════════════════════════════════════════════════════════
# TIMEZONE & DATE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

# Market timings (IST)
MARKET_PRE_OPEN_START = (9, 0)
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)

# Session configuration
SESSION_TIMEOUT_SECONDS = 28800  # 8 hours
SESSION_WARNING_SECONDS = 25200  # 7 hours

# Cache configuration
OC_CACHE_TTL_SECONDS = 30
QUOTE_CACHE_TTL_SECONDS = 5
POSITION_CACHE_TTL_SECONDS = 10

# ═══════════════════════════════════════════════════════════════════
# INSTRUMENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class InstrumentConfig:
    """Immutable instrument configuration."""
    display_name: str
    api_code: str
    exchange: Literal['NFO', 'BFO']
    lot_size: int
    tick_size: float
    strike_gap: int
    expiry_day: Literal['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    description: str
    min_strike: int = 0
    max_strike: int = 999999

INSTRUMENTS: Dict[str, InstrumentConfig] = {
    "NIFTY": InstrumentConfig(
        display_name="NIFTY",
        api_code="NIFTY",
        exchange="NFO",
        lot_size=65,
        tick_size=0.05,
        strike_gap=50,
        expiry_day="Tuesday",
        description="NIFTY 50 Index",
        min_strike=15000,
        max_strike=30000
    ),
    "BANKNIFTY": InstrumentConfig(
        display_name="BANKNIFTY",
        api_code="BANKNIFTY",
        exchange="NFO",
        lot_size=15,
        tick_size=0.05,
        strike_gap=100,
        expiry_day="Wednesday",
        description="Bank NIFTY Index",
        min_strike=30000,
        max_strike=60000
    ),
    "FINNIFTY": InstrumentConfig(
        display_name="FINNIFTY",
        api_code="FINNIFTY",
        exchange="NFO",
        lot_size=25,
        tick_size=0.05,
        strike_gap=50,
        expiry_day="Tuesday",
        description="NIFTY Financial Services",
        min_strike=15000,
        max_strike=30000
    ),
    "MIDCPNIFTY": InstrumentConfig(
        display_name="MIDCPNIFTY",
        api_code="MIDCPNIFTY",
        exchange="NFO",
        lot_size=50,
        tick_size=0.05,
        strike_gap=25,
        expiry_day="Monday",
        description="NIFTY Midcap Select",
        min_strike=8000,
        max_strike=15000
    ),
    "SENSEX": InstrumentConfig(
        display_name="SENSEX",
        api_code="BSESEN",
        exchange="BFO",
        lot_size=20,
        tick_size=0.05,
        strike_gap=100,
        expiry_day="Thursday",
        description="BSE SENSEX",
        min_strike=50000,
        max_strike=100000
    ),
    "BANKEX": InstrumentConfig(
        display_name="BANKEX",
        api_code="BANKEX",
        exchange="BFO",
        lot_size=15,
        tick_size=0.05,
        strike_gap=100,
        expiry_day="Monday",
        description="BSE BANKEX",
        min_strike=40000,
        max_strike=80000
    ),
}

DAY_NUM = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2,
    "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
}

# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def get_instrument(name: str) -> InstrumentConfig:
    """Get instrument configuration by display name."""
    if name not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {name}")
    return INSTRUMENTS[name]


def get_next_expiries(instrument_name: str, count: int = 5) -> List[str]:
    """Calculate next N weekly expiry dates for an instrument."""
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    
    target_day = DAY_NUM[inst.expiry_day]
    now = datetime.now(IST)
    
    days_ahead = (target_day - now.weekday()) % 7
    next_expiry = now if days_ahead == 0 else now + timedelta(days=days_ahead)
    
    expiries = []
    for i in range(count):
        expiry_date = next_expiry + timedelta(weeks=i)
        expiries.append(expiry_date.strftime("%Y-%m-%d"))
    
    return expiries


def api_code_to_display(api_code: str) -> str:
    """
    Convert API stock code to display name.
    
    FIXED: Returns original code if not found (instead of raising error)
    """
    if not api_code:
        return ""
    
    for name, config in INSTRUMENTS.items():
        if config.api_code == api_code:
            return name
    
    # Return original if not found
    return api_code


def normalize_option_type(option_str: Optional[str]) -> str:
    """
    Normalize option type to CE/PE format.
    
    FIXED: Properly handles None, empty strings, and invalid values
    
    Args:
        option_str: Any variant ('call', 'Call', 'CE', 'c', 'put', 'Put', 'PE', 'p')
                    Can be None (for equity positions)
    
    Returns:
        'CE', 'PE', or 'N/A' for non-options
    """
    # Handle None and empty strings
    if option_str is None or option_str == "":
        return "N/A"
    
    # Convert to string and normalize
    s = str(option_str).strip().lower()
    
    # Handle empty after strip
    if not s:
        return "N/A"
    
    # Map to CE/PE
    if s in ('call', 'ce', 'c'):
        return 'CE'
    elif s in ('put', 'pe', 'p'):
        return 'PE'
    else:
        # Return uppercased original for unknown types
        return str(option_str).upper()


def is_option_position(position: Dict) -> bool:
    """
    Check if a position is an option position (not equity).
    
    NEW: Helper to filter out equity positions
    
    Args:
        position: Position dictionary from API
    
    Returns:
        True if option position, False if equity
    """
    # Check product type
    product_type = str(position.get("product_type", "")).lower()
    if product_type == "options":
        return True
    
    # Check segment
    segment = str(position.get("segment", "")).lower()
    if segment == "fno":
        return True
    
    # Check if has option-specific fields
    if position.get("right") is not None and position.get("strike_price") is not None:
        return True
    
    return False


def validate_strike(instrument_name: str, strike: int) -> bool:
    """Validate if strike price is valid for instrument."""
    try:
        inst = get_instrument(instrument_name)
        
        if strike < inst.min_strike or strike > inst.max_strike:
            return False
        
        if strike % inst.strike_gap != 0:
            return False
        
        return True
    except KeyError:
        return False


def round_to_tick(price: float, instrument_name: str) -> float:
    """Round price to valid tick size for instrument."""
    try:
        inst = get_instrument(instrument_name)
        tick = inst.tick_size
        return round(price / tick) * tick
    except KeyError:
        return round(price, 2)


def is_market_open() -> bool:
    """Check if market is currently open."""
    now = datetime.now(IST)
    
    if now.weekday() >= 5:
        return False
    
    open_time = now.replace(
        hour=MARKET_OPEN[0],
        minute=MARKET_OPEN[1],
        second=0,
        microsecond=0
    )
    
    close_time = now.replace(
        hour=MARKET_CLOSE[0],
        minute=MARKET_CLOSE[1],
        second=0,
        microsecond=0
    )
    
    return open_time <= now <= close_time


# ═══════════════════════════════════════════════════════════════════
# APPLICATION CONSTANTS
# ═══════════════════════════════════════════════════════════════════

MAX_ACTIVITY_LOG_ENTRIES = 100
MAX_STRIKES_TO_DISPLAY = 50
DEFAULT_STRIKES_TO_DISPLAY = 15
MAX_LOTS_PER_ORDER = 1000
MIN_LOTS_PER_ORDER = 1

CURRENCY_FORMATS = {
    'crore': 1e7,
    'lakh': 1e5,
    'thousand': 1e3
}

RISK_FREE_RATE = 0.065
DAYS_PER_YEAR = 365


# ═══════════════════════════════════════════════════════════════════
# ERROR MESSAGES
# ═══════════════════════════════════════════════════════════════════

class ErrorMessages:
    """Centralized error messages."""
    NOT_CONNECTED = "Not connected to Breeze API"
    CONNECTION_FAILED = "Failed to connect: {error}"
    SESSION_EXPIRED = "Session has expired. Please reconnect"
    INVALID_STRIKE = "Invalid strike price for {instrument}"
    INVALID_QUANTITY = "Quantity must be between {min} and {max} lots"
    INVALID_PRICE = "Price must be positive"
    INVALID_INSTRUMENT = "Unknown instrument: {instrument}"
    ORDER_FAILED = "Order placement failed: {error}"
    CANCEL_FAILED = "Order cancellation failed: {error}"
    MODIFY_FAILED = "Order modification failed: {error}"
    NO_DATA = "No data available"
    FETCH_FAILED = "Failed to fetch data: {error}"
    PARSE_FAILED = "Failed to parse response: {error}"


class Colors:
    """Application color scheme."""
    SUCCESS = "#28a745"
    WARNING = "#ffc107"
    ERROR = "#dc3545"
    INFO = "#2196F3"
    PROFIT = "#28a745"
    LOSS = "#dc3545"
    NEUTRAL = "#6c757d"
    MARKET_OPEN = "#28a745"
    MARKET_CLOSED = "#dc3545"
    PRE_MARKET = "#ffc107"
    PRIMARY = "#1f77b4"
    SECONDARY = "#2ecc71"
    ACCENT = "#9b59b6"
