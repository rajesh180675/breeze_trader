"""
Breeze API Wrapper with Retry Logic & Rate Limiting.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from functools import wraps

from breeze_connect import BreezeConnect
from helpers import APIResponse, safe_int
import app_config as C

log = logging.getLogger(__name__)


def convert_to_breeze_date(date_str: str) -> str:
    if not date_str or not date_str.strip():
        return ""
    date_str = date_str.strip()
    formats = [
        ("%d-%b-%Y", False), ("%d-%B-%Y", True), ("%Y-%m-%d", True),
        ("%Y-%m-%dT%H:%M:%S", True), ("%Y-%m-%dT%H:%M:%S.%f", True),
        ("%d/%m/%Y", True), ("%d-%m-%Y", True),
    ]
    for fmt, needs_conv in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%d-%b-%Y") if needs_conv else date_str
        except ValueError:
            continue
    log.warning(f"Could not parse date: {date_str}")
    return date_str


def retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0, exceptions=(Exception,)):
    def decorator(func):
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
                    log.warning(f"{func.__name__} attempt {attempt} failed: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
                    attempt += 1
        return wrapper
    return decorator


class RateLimiter:
    def __init__(self, calls_per_second=5.0):
        self.min_interval = 1.0 / calls_per_second
        self.last_call_time = 0.0

    def wait_if_needed(self):
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()


class BreezeAPIClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.breeze: Optional[BreezeConnect] = None
        self.connected = False
        self.rate_limiter = RateLimiter(5.0)

    def is_connected(self) -> bool:
        return self.connected and self.breeze is not None

    def _ok(self, data): return {"success": True, "data": data, "message": "", "error_code": None}
    def _err(self, msg, code=None): return {"success": False, "data": {}, "message": str(msg), "error_code": code}

    def _check(self):
        if not self.connected:
            return self._err(C.ErrorMessages.NOT_CONNECTED)
        return None

    @retry_on_failure(max_attempts=2, delay=1.0)
    def connect(self, session_token):
        try:
            self.breeze = BreezeConnect(api_key=self.api_key)
            self.breeze.generate_session(api_secret=self.api_secret, session_token=session_token)
            self.connected = True
            log.info("Successfully connected to Breeze API")
            return self._ok({"message": "Connected"})
        except Exception as e:
            self.connected = False
            log.error(f"Connection failed: {e}")
            return self._err(C.ErrorMessages.CONNECTION_FAILED.format(error=str(e)))

    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_customer_details(self):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.get_customer_details())
        except Exception as e:
            return self._err(str(e))

    @retry_on_failure(max_attempts=3, delay=0.5)
    def get_funds(self):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.get_funds())
        except Exception as e:
            log.error(f"Get funds failed: {e}")
            return self._err(str(e))

    @retry_on_failure(max_attempts=3, delay=1.0, backoff=1.5)
    def get_option_chain(self, stock_code, exchange, expiry):
        if e := self._check(): return e
        try:
            expiry_date = convert_to_breeze_date(expiry)
            log.info(f"Fetching option chain: {stock_code} {exchange} {expiry_date}")
            self.rate_limiter.wait_if_needed()
            data = self.breeze.get_option_chain_quotes(
                stock_code=stock_code, exchange_code=exchange, product_type="options",
                expiry_date=expiry_date, right="", strike_price=""
            )
            return self._ok(data)
        except Exception as e:
            log.error(f"Option chain failed: {e}")
            return self._err(C.ErrorMessages.FETCH_FAILED.format(error=str(e)))

    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_quotes(self, stock_code, exchange, expiry, strike, option_type):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            data = self.breeze.get_quotes(
                stock_code=stock_code, exchange_code=exchange,
                expiry_date=convert_to_breeze_date(expiry), product_type="options",
                right="call" if option_type.upper() == "CE" else "put",
                strike_price=str(strike)
            )
            return self._ok(data)
        except Exception as e:
            return self._err(str(e))

    def place_order(self, stock_code, exchange, expiry, strike, option_type, action, quantity, order_type="market", price=0.0):
        if e := self._check(): return e
        try:
            right = "call" if option_type.upper() == "CE" else "put"
            log.info(f"Order: {action.upper()} {stock_code} {strike} {option_type} x{quantity}")
            self.rate_limiter.wait_if_needed()
            resp = self.breeze.place_order(
                stock_code=stock_code, exchange_code=exchange, product="options",
                action=action.lower(), order_type=order_type.lower(),
                quantity=str(quantity), price=str(price) if order_type.lower() == "limit" else "",
                validity="day", validity_date="", disclosed_quantity="", stoploss="",
                expiry_date=convert_to_breeze_date(expiry), right=right, strike_price=str(strike)
            )
            return self._ok(resp)
        except Exception as e:
            log.error(f"Order failed: {e}")
            return self._err(C.ErrorMessages.ORDER_FAILED.format(error=str(e)))

    def sell_call(self, stock_code, exchange, expiry, strike, quantity, order_type="market", price=0.0):
        return self.place_order(stock_code, exchange, expiry, strike, "CE", "sell", quantity, order_type, price)

    def sell_put(self, stock_code, exchange, expiry, strike, quantity, order_type="market", price=0.0):
        return self.place_order(stock_code, exchange, expiry, strike, "PE", "sell", quantity, order_type, price)

    def square_off(self, stock_code, exchange, expiry, strike, option_type, quantity, position_type, order_type="market", price=0.0):
        action = "buy" if position_type == "short" else "sell"
        return self.place_order(stock_code, exchange, expiry, strike, option_type, action, quantity, order_type, price)

    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_positions(self):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.get_portfolio_positions())
        except Exception as e:
            return self._err(str(e))

    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_order_list(self, exchange="", from_date="", to_date=""):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.get_order_list(exchange_code=exchange, from_date=from_date, to_date=to_date))
        except Exception as e:
            return self._err(str(e))

    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_trade_list(self, exchange="", from_date="", to_date=""):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.get_trade_list(exchange_code=exchange, from_date=from_date, to_date=to_date))
        except Exception as e:
            return self._err(str(e))

    def cancel_order(self, order_id, exchange):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.cancel_order(exchange_code=exchange, order_id=order_id))
        except Exception as e:
            return self._err(C.ErrorMessages.CANCEL_FAILED.format(error=str(e)))

    def modify_order(self, order_id, exchange, quantity=0, price=0.0):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.modify_order(
                order_id=order_id, exchange_code=exchange,
                quantity=str(quantity) if quantity > 0 else None,
                price=str(price) if price > 0 else None,
                order_type=None, stoploss=None, validity=None
            ))
        except Exception as e:
            return self._err(C.ErrorMessages.MODIFY_FAILED.format(error=str(e)))

    @retry_on_failure(max_attempts=2, delay=0.5)
    def get_margin(self, stock_code, exchange, expiry, strike, option_type, action, quantity):
        if e := self._check(): return e
        try:
            self.rate_limiter.wait_if_needed()
            return self._ok(self.breeze.get_margin(
                exchange_code=exchange, stock_code=stock_code, product_type="options",
                right="call" if option_type.upper() == "CE" else "put",
                strike_price=str(strike), expiry_date=convert_to_breeze_date(expiry),
                quantity=str(quantity), action=action.lower(), order_type="market", price=""
            ))
        except Exception as e:
            return self._err(str(e))

    def square_off_all_positions(self):
        if e := self._check(): return [e]
        from helpers import detect_position_type
        resp = self.get_positions()
        if not resp["success"]: return [resp]
        parsed = APIResponse(resp)
        results = []
        for pos in parsed.items:
            try:
                if not C.is_option_position(pos): continue
                qty = safe_int(pos.get("quantity", 0))
                if qty == 0: continue
                pt = detect_position_type(pos)
                r = self.square_off(
                    pos.get("stock_code", ""), pos.get("exchange_code", ""),
                    pos.get("expiry_date", ""), safe_int(pos.get("strike_price", 0)),
                    C.normalize_option_type(pos.get("right", "")), abs(qty), pt
                )
                results.append(r)
            except Exception as e:
                results.append(self._err(str(e)))
        return results or [self._ok({"message": "No positions"})]
