"""
Breeze API Wrapper with Retry Logic & Rate Limiting
====================================================
Robust API client with automatic retries, rate limiting, and error handling.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from functools import wraps
import pytz

from breeze_connect import BreezeConnect

from helpers import APIResponse, safe_int
import app_config as C

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# DATE CONVERSION UTILITIES
# ═══════════════════════════════════════════════════════════════════

def convert_to_breeze_date(date_str: str) -> str:
    """
    Convert any date format to DD-Mon-YYYY (Breeze API format).
    
    Handles:
        - YYYY-MM-DD (ISO)
        - DD-Mon-YYYY (already correct)
        - DD-MM-YYYY
        - DD/MM/YYYY
        - ISO with time
    
    Args:
        date_str: Date string in any format
    
    Returns:
        Date in DD-Mon-YYYY format
    
    Example:
        >>> convert_to_breeze_date("2026-02-17")
        "17-Feb-2026"
    """
    if not date_str or not date_str.strip():
        return ""
    
    date_str = date_str.strip()
    
    # Try different formats
    formats_to_try = [
        ("%d-%b-%Y", False),        # Already correct format
        ("%d-%B-%Y", True),          # Full month name
        ("%Y-%m-%d", True),          # ISO date
        ("%Y-%m-%dT%H:%M:%S", True), # ISO datetime
        ("%Y-%m-%dT%H:%M:%S.%f", True),  # ISO with microseconds
        ("%d/%m/%Y", True),          # DD/MM/YYYY
        ("%d-%m-%Y", True),          # DD-MM-YYYY
        ("%Y/%m/%d", True),          # YYYY/MM/DD
    ]
    
    for fmt, needs_conversion in formats_to_try:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            if needs_conversion:
                return parsed_date.strftime("%d-%b-%Y")
            else:
                return date_str  # Already in correct format
        except ValueError:
            continue
    
    # If all formats fail, log warning and return as-is
    log.warning(f"Could not parse date: {date_str}")
    return date_str


# ═══════════════════════════════════════════════════════════════════
# RETRY DECORATOR
# ═══════════════════════════════════════════════════════════════════

def retry_on_failure(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator to retry function on failure with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exceptions to catch
    
    Example:
        @retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0)
        def api_call():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 1
            current_delay = delay
            
            while attempt <= max_attempts:
                try:
                    return func(*args, **kwargs)
                
                except exceptions as e:
                    if attempt == max_attempts:
                        log.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    
                    log.warning(f"{func.__name__} attempt {attempt} failed: {e}. "
                              f"Retrying in {current_delay}s...")
                    
                    time.sleep(current_delay)
                    current_delay *= backoff
                    attempt += 1
            
            return None
        
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Simple rate limiter to prevent API throttling.
    """
    
    def __init__(self, calls_per_second: float = 5.0):
        """
        Initialize rate limiter.
        
        Args:
            calls_per_second: Maximum calls allowed per second
        """
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call_time = 0.0
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limit."""
        current_time = time.time()
        time_since_last_call = current_time - self.last_call_time
        
        if time_since_last_call < self.min_interval:
            sleep_time = self.min_interval - time_since_last_call
            time.sleep(sleep_time)
        
        self.last_call_time = time.time()


# ═══════════════════════════════════════════════════════════════════
# BREEZE API CLIENT
# ═══════════════════════════════════════════════════════════════════

class BreezeAPIClient:
    """
    Enhanced Breeze API client with retry logic and rate limiting.
    """
    
    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize API client.
        
        Args:
            api_key: Breeze API key
            api_secret: Breeze API secret
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.breeze: Optional[BreezeConnect] = None
        self.connected = False
        self.rate_limiter = RateLimiter(calls_per_second=5.0)
    
    def _success_response(self, data: Any) -> Dict[str, Any]:
        """Create success response."""
        return {
            "success": True,
            "data": data,
            "message": "",
            "error_code": None
        }
    
    def _error_response(self, message: str, error_code: Optional[str] = None) -> Dict[str, Any]:
        """Create error response."""
        return {
            "success": False,
            "data": {},
            "message": str(message),
            "error_code": error_code
        }
    
    def _check_connection(self) -> Optional[Dict[str, Any]]:
        """Check if client is connected."""
        if not self.connected:
            return self._error_response(C.ErrorMessages.NOT_CONNECTED)
        return None
    
    # ─── Connection ───────────────────────────────────────────────
    
    @retry_on_failure(max_attempts=2, delay=1.0)
    def connect(self, session_token: str) -> Dict[str, Any]:
        """
        Connect to Breeze API.
        
        Args:
            session_token: Daily session token from ICICI
        
        Returns:
            Response dictionary
        """
        try:
            self.breeze = BreezeConnect(api_key=self.api_key)
            
            response = self.breeze.generate_session(
                api_secret=self.api_secret,
                session_token=session_token
            )
            
            self.connected = True
            log.info("Successfully connected to Breeze API")
            
            return self._success_response({
                "message": "Connected successfully",
                "response": response
            })
        
        except Exception as e:
            self.connected = False
            log.error(f"Connection failed: {e}")
            return self._error_response(
                C.ErrorMessages.CONNECTION_FAILED.format(error=str(e))
            )
    
    def disconnect(self):
        """Disconnect from API."""
        self.connected = False
        self.breeze = None
        log.info("Disconnected from Breeze API")
    
    # ─── Account Information ──────────────────────────────────────
    
    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_customer_details(self) -> Dict[str, Any]:
        """
        Get customer/account details.
        
        Returns:
            Response with customer info
        """
        if error := self._check_connection():
            return error
        
        try:
            self.rate_limiter.wait_if_needed()
            data = self.breeze.get_customer_details()
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get customer details failed: {e}")
            return self._error_response(str(e))
    
    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_funds(self) -> Dict[str, Any]:
        """
        Get fund/margin details.
        
        Returns:
            Response with fund info
        """
        if error := self._check_connection():
            return error
        
        try:
            self.rate_limiter.wait_if_needed()
            data = self.breeze.get_funds()
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get funds failed: {e}")
            return self._error_response(str(e))
    
    # ─── Market Data ──────────────────────────────────────────────
    
    @retry_on_failure(max_attempts=3, delay=1.0, backoff=1.5)
    def get_option_chain(
        self,
        stock_code: str,
        exchange: str,
        expiry: str
    ) -> Dict[str, Any]:
        """
        Get complete option chain for an instrument.
        
        Args:
            stock_code: Stock code (e.g., 'NIFTY', 'BSESEN')
            exchange: Exchange code ('NFO' or 'BFO')
            expiry: Expiry date (any format, will be converted)
        
        Returns:
            Response with option chain data
        """
        if error := self._check_connection():
            return error
        
        try:
            # Convert date to Breeze format
            expiry_date = convert_to_breeze_date(expiry)
            
            log.info(f"Fetching option chain: {stock_code} {exchange} {expiry_date}")
            
            self.rate_limiter.wait_if_needed()
            
            data = self.breeze.get_option_chain_quotes(
                stock_code=stock_code,
                exchange_code=exchange,
                product_type="options",
                expiry_date=expiry_date,
                right="",  # Empty to get both calls and puts
                strike_price=""  # Empty to get all strikes
            )
            
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get option chain failed: {e}")
            return self._error_response(
                C.ErrorMessages.FETCH_FAILED.format(error=str(e))
            )
    
    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_quotes(
        self,
        stock_code: str,
        exchange: str,
        expiry: str,
        strike: int,
        option_type: str
    ) -> Dict[str, Any]:
        """
        Get quote for specific option contract.
        
        Args:
            stock_code: Stock code
            exchange: Exchange code
            expiry: Expiry date
            strike: Strike price
            option_type: 'CE' or 'PE'
        
        Returns:
            Response with quote data
        """
        if error := self._check_connection():
            return error
        
        try:
            expiry_date = convert_to_breeze_date(expiry)
            right = "call" if option_type.upper() == "CE" else "put"
            
            self.rate_limiter.wait_if_needed()
            
            data = self.breeze.get_quotes(
                stock_code=stock_code,
                exchange_code=exchange,
                expiry_date=expiry_date,
                product_type="options",
                right=right,
                strike_price=str(strike)
            )
            
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get quotes failed: {e}")
            return self._error_response(str(e))
    
    # ─── Order Placement ──────────────────────────────────────────
    
    @retry_on_failure(max_attempts=1, delay=0.5)  # No retry for orders
    def place_order(
        self,
        stock_code: str,
        exchange: str,
        expiry: str,
        strike: int,
        option_type: str,
        action: str,
        quantity: int,
        order_type: str = "market",
        price: float = 0.0
    ) -> Dict[str, Any]:
        """
        Place an option order.
        
        Args:
            stock_code: Stock code
            exchange: Exchange code
            expiry: Expiry date
            strike: Strike price
            option_type: 'CE' or 'PE'
            action: 'buy' or 'sell'
            quantity: Order quantity
            order_type: 'market' or 'limit'
            price: Limit price (if limit order)
        
        Returns:
            Response with order details
        """
        if error := self._check_connection():
            return error
        
        try:
            expiry_date = convert_to_breeze_date(expiry)
            right = "call" if option_type.upper() == "CE" else "put"
            
            log.info(f"Placing order: {action.upper()} {stock_code} "
                    f"{strike} {option_type} x{quantity} @ {order_type}")
            
            self.rate_limiter.wait_if_needed()
            
            response = self.breeze.place_order(
                stock_code=stock_code,
                exchange_code=exchange,
                product="options",
                action=action.lower(),
                order_type=order_type.lower(),
                quantity=str(quantity),
                price=str(price) if order_type.lower() == "limit" else "",
                validity="day",
                validity_date="",
                disclosed_quantity="",
                stoploss="",
                expiry_date=expiry_date,
                right=right,
                strike_price=str(strike)
            )
            
            log.info(f"Order placed successfully: {response}")
            return self._success_response(response)
        
        except Exception as e:
            log.error(f"Place order failed: {e}")
            return self._error_response(
                C.ErrorMessages.ORDER_FAILED.format(error=str(e))
            )
    
    def sell_call(
        self,
        stock_code: str,
        exchange: str,
        expiry: str,
        strike: int,
        quantity: int,
        order_type: str = "market",
        price: float = 0.0
    ) -> Dict[str, Any]:
        """Sell call option."""
        return self.place_order(
            stock_code, exchange, expiry, strike, "CE",
            "sell", quantity, order_type, price
        )
    
    def sell_put(
        self,
        stock_code: str,
        exchange: str,
        expiry: str,
        strike: int,
        quantity: int,
        order_type: str = "market",
        price: float = 0.0
    ) -> Dict[str, Any]:
        """Sell put option."""
        return self.place_order(
            stock_code, exchange, expiry, strike, "PE",
            "sell", quantity, order_type, price
        )
    
    def square_off(
        self,
        stock_code: str,
        exchange: str,
        expiry: str,
        strike: int,
        option_type: str,
        quantity: int,
        position_type: str,
        order_type: str = "market",
        price: float = 0.0
    ) -> Dict[str, Any]:
        """
        Square off (close) a position.
        
        Args:
            position_type: 'long' or 'short'
            
        Other args same as place_order
        """
        # Determine closing action
        action = "buy" if position_type == "short" else "sell"
        
        log.info(f"Square off: {action.upper()} {stock_code} {strike} "
                f"{option_type} (was {position_type})")
        
        return self.place_order(
            stock_code, exchange, expiry, strike, option_type,
            action, quantity, order_type, price
        )
    
    # ─── Portfolio ────────────────────────────────────────────────
    
    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_positions(self) -> Dict[str, Any]:
        """
        Get all open positions.
        
        Returns:
            Response with positions data
        """
        if error := self._check_connection():
            return error
        
        try:
            self.rate_limiter.wait_if_needed()
            data = self.breeze.get_portfolio_positions()
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get positions failed: {e}")
            return self._error_response(str(e))
    
    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_order_list(
        self,
        exchange: str = "",
        from_date: str = "",
        to_date: str = ""
    ) -> Dict[str, Any]:
        """
        Get order history.
        
        Args:
            exchange: Exchange code (optional filter)
            from_date: From date in YYYY-MM-DD format
            to_date: To date in YYYY-MM-DD format
        
        Returns:
            Response with order list
        """
        if error := self._check_connection():
            return error
        
        try:
            self.rate_limiter.wait_if_needed()
            
            data = self.breeze.get_order_list(
                exchange_code=exchange,
                from_date=from_date,
                to_date=to_date
            )
            
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get order list failed: {e}")
            return self._error_response(str(e))
    
    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_trade_list(
        self,
        exchange: str = "",
        from_date: str = "",
        to_date: str = ""
    ) -> Dict[str, Any]:
        """
        Get trade history.
        
        Args:
            exchange: Exchange code (optional filter)
            from_date: From date in YYYY-MM-DD format
            to_date: To date in YYYY-MM-DD format
        
        Returns:
            Response with trade list
        """
        if error := self._check_connection():
            return error
        
        try:
            self.rate_limiter.wait_if_needed()
            
            data = self.breeze.get_trade_list(
                exchange_code=exchange,
                from_date=from_date,
                to_date=to_date
            )
            
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get trade list failed: {e}")
            return self._error_response(str(e))
    
    # ─── Order Management ─────────────────────────────────────────
    
    @retry_on_failure(max_attempts=1, delay=0.5)
    def cancel_order(self, order_id: str, exchange: str) -> Dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            exchange: Exchange code
        
        Returns:
            Response
        """
        if error := self._check_connection():
            return error
        
        try:
            self.rate_limiter.wait_if_needed()
            
            data = self.breeze.cancel_order(
                exchange_code=exchange,
                order_id=order_id
            )
            
            log.info(f"Order cancelled: {order_id}")
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Cancel order failed: {e}")
            return self._error_response(
                C.ErrorMessages.CANCEL_FAILED.format(error=str(e))
            )
    
    @retry_on_failure(max_attempts=1, delay=0.5)
    def modify_order(
        self,
        order_id: str,
        exchange: str,
        quantity: int = 0,
        price: float = 0.0
    ) -> Dict[str, Any]:
        """
        Modify an order.
        
        Args:
            order_id: Order ID to modify
            exchange: Exchange code
            quantity: New quantity (0 = no change)
            price: New price (0 = no change)
        
        Returns:
            Response
        """
        if error := self._check_connection():
            return error
        
        try:
            self.rate_limiter.wait_if_needed()
            
            data = self.breeze.modify_order(
                order_id=order_id,
                exchange_code=exchange,
                quantity=str(quantity) if quantity > 0 else None,
                price=str(price) if price > 0 else None,
                order_type=None,
                stoploss=None,
                validity=None
            )
            
            log.info(f"Order modified: {order_id}")
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Modify order failed: {e}")
            return self._error_response(
                C.ErrorMessages.MODIFY_FAILED.format(error=str(e))
            )
    
    # ─── Margin ───────────────────────────────────────────────────
    
    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_margin(
        self,
        stock_code: str,
        exchange: str,
        expiry: str,
        strike: int,
        option_type: str,
        action: str,
        quantity: int
    ) -> Dict[str, Any]:
        """
        Get margin requirement for order.
        
        Args:
            stock_code: Stock code
            exchange: Exchange code
            expiry: Expiry date
            strike: Strike price
            option_type: 'CE' or 'PE'
            action: 'buy' or 'sell'
            quantity: Order quantity
        
        Returns:
            Response with margin info
        """
        if error := self._check_connection():
            return error
        
        try:
            expiry_date = convert_to_breeze_date(expiry)
            right = "call" if option_type.upper() == "CE" else "put"
            
            self.rate_limiter.wait_if_needed()
            
            data = self.breeze.get_margin(
                exchange_code=exchange,
                stock_code=stock_code,
                product_type="options",
                right=right,
                strike_price=str(strike),
                expiry_date=expiry_date,
                quantity=str(quantity),
                action=action.lower(),
                order_type="market",
                price=""
            )
            
            return self._success_response(data)
        
        except Exception as e:
            log.error(f"Get margin failed: {e}")
            return self._error_response(str(e))
    
    # ─── Bulk Operations ──────────────────────────────────────────
    
    def square_off_all_positions(self, exchange: str = "") -> List[Dict[str, Any]]:
        """
        Square off all open positions.
        
        Args:
            exchange: Exchange filter (optional)
        
        Returns:
            List of responses for each position
        """
        if error := self._check_connection():
            return [error]
        
        # Import here to avoid circular dependency
        from helpers import detect_position_type, safe_int
        
        # Get positions
        positions_response = self.get_positions()
        
        if not positions_response["success"]:
            return [positions_response]
        
        # Parse positions
        response_obj = APIResponse(positions_response)
        positions = response_obj.items
        
        if not positions:
            return [self._success_response({"message": "No positions to close"})]
        
        results = []
        
        for position in positions:
            try:
                # Filter by exchange if specified
                if exchange and position.get("exchange_code") != exchange:
                    continue
                
                # Only process option positions
                if str(position.get("product_type", "")).lower() != "options":
                    continue
                
                # Check quantity
                qty = safe_int(position.get("quantity", 0))
                if qty == 0:
                    continue
                
                # Detect position type
                pos_type = detect_position_type(position)
                
                # Normalize option type
                right = C.normalize_option_type(position.get("right", ""))
                
                # Square off
                result = self.square_off(
                    stock_code=position.get("stock_code", ""),
                    exchange=position.get("exchange_code", ""),
                    expiry=position.get("expiry_date", ""),
                    strike=safe_int(position.get("strike_price", 0)),
                    option_type=right,
                    quantity=abs(qty),
                    position_type=pos_type
                )
                
                results.append(result)
            
            except Exception as e:
                log.error(f"Error squaring off position: {e}")
                results.append(self._error_response(str(e)))
        
        if not results:
            return [self._success_response({"message": "No positions matched criteria"})]
        
        return results
