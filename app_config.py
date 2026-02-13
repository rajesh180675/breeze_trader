"""
Instrument Configuration & Application Constants
================================================
All configuration, instruments, constants in one place.
Zero external dependencies except stdlib.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Literal
from dataclasses import dataclass
import pytz

# ═══════════════════════════════════════════════════════════════════
# TIMEZONE & DATE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

IST = pytz.timezone("Asia/Kolkata")

# Market timings (IST)
MARKET_PRE_OPEN_START = (9, 0)   # 9:00 AM
MARKET_OPEN = (9, 15)             # 9:15 AM
MARKET_CLOSE = (15, 30)           # 3:30 PM

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

# All supported instruments
INSTRUMENTS: Dict[str, InstrumentConfig] = {
    "NIFTY": InstrumentConfig(
        display_name="NIFTY",
        api_code="NIFTY",
        exchange="NFO",
        lot_size=25,
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
        api_code="BSESEN",  # Critical: API uses BSESEN not SENSEX
        exchange="BFO",
        lot_size=10,
        tick_size=0.05,
        strike_gap=100,
        expiry_day="Thursday",  # Confirmed: Thursday expiry
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

# Day number mapping for expiry calculations
DAY_NUM = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6
}

# ═══════════════════════════════════════════════════════════════════
# APPLICATION CONSTANTS
# ═══════════════════════════════════════════════════════════════════

# Activity log limits
MAX_ACTIVITY_LOG_ENTRIES = 100

# Display limits
MAX_STRIKES_TO_DISPLAY = 50
DEFAULT_STRIKES_TO_DISPLAY = 15

# Order limits
MAX_LOTS_PER_ORDER = 1000
MIN_LOTS_PER_ORDER = 1

# Formatting
CURRENCY_FORMATS = {
    'crore': 1e7,
    'lakh': 1e5,
    'thousand': 1e3
}

# Greeks calculation constants
RISK_FREE_RATE = 0.065  # 6.5% annual
DAYS_PER_YEAR = 365

# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def get_instrument(name: str) -> InstrumentConfig:
    """
    Get instrument configuration by display name.
    
    Args:
        name: Instrument display name (e.g., 'NIFTY', 'SENSEX')
    
    Returns:
        InstrumentConfig object
    
    Raises:
        KeyError: If instrument not found
    """
    if name not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {name}")
    return INSTRUMENTS[name]


def get_next_expiries(instrument_name: str, count: int = 5) -> List[str]:
    """
    Calculate next N weekly expiry dates for an instrument.
    
    Args:
        instrument_name: Name of instrument (e.g., 'NIFTY')
        count: Number of expiries to return
    
    Returns:
        List of expiry dates as 'YYYY-MM-DD' strings
    
    Example:
        >>> get_next_expiries('NIFTY', 3)
        ['2026-02-17', '2026-02-24', '2026-03-03']
    """
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    
    target_day = DAY_NUM[inst.expiry_day]
    now = datetime.now(IST)
    
    # Calculate days ahead to next expiry
    days_ahead = (target_day - now.weekday()) % 7
    
    # If today is expiry day and market is still open, include today
    if days_ahead == 0:
        next_expiry = now
    else:
        next_expiry = now + timedelta(days=days_ahead)
    
    # Generate list of expiries
    expiries = []
    for i in range(count):
        expiry_date = next_expiry + timedelta(weeks=i)
        expiries.append(expiry_date.strftime("%Y-%m-%d"))
    
    return expiries


def api_code_to_display(api_code: str) -> str:
    """
    Convert API stock code to display name.
    
    Args:
        api_code: API stock code (e.g., 'BSESEN')
    
    Returns:
        Display name (e.g., 'SENSEX')
    
    Example:
        >>> api_code_to_display('BSESEN')
        'SENSEX'
    """
    for name, config in INSTRUMENTS.items():
        if config.api_code == api_code:
            return name
    return api_code  # Return as-is if not found


def normalize_option_type(option_str: str) -> str:
    """
    Normalize option type to CE/PE format.
    
    Args:
        option_str: Any variant ('call', 'Call', 'CE', 'c', 'put', 'Put', 'PE', 'p')
    
    Returns:
        'CE' or 'PE'
    
    Example:
        >>> normalize_option_type('call')
        'CE'
        >>> normalize_option_type('Put')
        'PE'
    """
    s = str(option_str).strip().lower()
    
    if s in ('call', 'ce', 'c'):
        return 'CE'
    elif s in ('put', 'pe', 'p'):
        return 'PE'
    else:
        # Return uppercased original if unknown
        return option_str.upper()


def validate_strike(instrument_name: str, strike: int) -> bool:
    """
    Validate if strike price is valid for instrument.
    
    Args:
        instrument_name: Instrument name
        strike: Strike price to validate
    
    Returns:
        True if valid, False otherwise
    """
    try:
        inst = get_instrument(instrument_name)
        
        # Check if within bounds
        if strike < inst.min_strike or strike > inst.max_strike:
            return False
        
        # Check if it's a valid strike (multiple of gap)
        if strike % inst.strike_gap != 0:
            return False
        
        return True
    
    except KeyError:
        return False


def round_to_tick(price: float, instrument_name: str) -> float:
    """
    Round price to valid tick size for instrument.
    
    Args:
        price: Price to round
        instrument_name: Instrument name
    
    Returns:
        Rounded price
    
    Example:
        >>> round_to_tick(100.12, 'NIFTY')
        100.10
    """
    try:
        inst = get_instrument(instrument_name)
        tick = inst.tick_size
        return round(price / tick) * tick
    except KeyError:
        return round(price, 2)


def is_market_open() -> bool:
    """
    Check if market is currently open.
    
    Returns:
        True if market open, False otherwise
    """
    now = datetime.now(IST)
    
    # Weekend check
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Time check
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
# ERROR MESSAGES
# ═══════════════════════════════════════════════════════════════════

class ErrorMessages:
    """Centralized error messages."""
    
    # Connection errors
    NOT_CONNECTED = "Not connected to Breeze API"
    CONNECTION_FAILED = "Failed to connect: {error}"
    SESSION_EXPIRED = "Session has expired. Please reconnect"
    
    # Validation errors
    INVALID_STRIKE = "Invalid strike price for {instrument}"
    INVALID_QUANTITY = "Quantity must be between {min} and {max} lots"
    INVALID_PRICE = "Price must be positive"
    INVALID_INSTRUMENT = "Unknown instrument: {instrument}"
    
    # Order errors
    ORDER_FAILED = "Order placement failed: {error}"
    CANCEL_FAILED = "Order cancellation failed: {error}"
    MODIFY_FAILED = "Order modification failed: {error}"
    
    # Data errors
    NO_DATA = "No data available"
    FETCH_FAILED = "Failed to fetch data: {error}"
    PARSE_FAILED = "Failed to parse response: {error}"


# ═══════════════════════════════════════════════════════════════════
# COLOR SCHEME
# ═══════════════════════════════════════════════════════════════════

class Colors:
    """Application color scheme."""
    
    # Status colors
    SUCCESS = "#28a745"
    WARNING = "#ffc107"
    ERROR = "#dc3545"
    INFO = "#2196F3"
    
    # P&L colors
    PROFIT = "#28a745"
    LOSS = "#dc3545"
    NEUTRAL = "#6c757d"
    
    # Market status
    MARKET_OPEN = "#28a745"
    MARKET_CLOSED = "#dc3545"
    PRE_MARKET = "#ffc107"
    
    # UI elements
    PRIMARY = "#1f77b4"
    SECONDARY = "#2ecc71"
    ACCENT = "#9b59b6"
