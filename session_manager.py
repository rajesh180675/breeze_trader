"""
Session Management, Credentials, and Caching
=============================================
Handles user session, credentials, and data caching.
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pytz
import logging
import pickle
import hashlib

import app_config as C

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# CREDENTIALS MANAGER
# ═══════════════════════════════════════════════════════════════════

class Credentials:
    """
    Secure credential management.
    
    Uses Streamlit Secrets for permanent storage (API Key & Secret).
    Uses session state for temporary storage (Session Token).
    """
    
    @staticmethod
    def get_stored_api_key() -> str:
        """Get API key from Streamlit Secrets."""
        try:
            return st.secrets.get("BREEZE_API_KEY", "")
        except Exception as e:
            log.debug(f"No secrets configured: {e}")
            return ""
    
    @staticmethod
    def get_stored_api_secret() -> str:
        """Get API secret from Streamlit Secrets."""
        try:
            return st.secrets.get("BREEZE_API_SECRET", "")
        except Exception as e:
            log.debug(f"No secrets configured: {e}")
            return ""
    
    @staticmethod
    def has_stored_credentials() -> bool:
        """Check if API credentials are stored in secrets."""
        return bool(
            Credentials.get_stored_api_key() and 
            Credentials.get_stored_api_secret()
        )
    
    @staticmethod
    def get_all_credentials() -> Tuple[str, str, str]:
        """
        Get all credentials (API key, secret, token).
        
        Returns:
            Tuple of (api_key, api_secret, session_token)
        """
        # Try secrets first, fallback to session state
        api_key = (Credentials.get_stored_api_key() or 
                   st.session_state.get("api_key", ""))
        
        api_secret = (Credentials.get_stored_api_secret() or 
                      st.session_state.get("api_secret", ""))
        
        session_token = st.session_state.get("session_token", "")
        
        return api_key, api_secret, session_token
    
    @staticmethod
    def save_runtime_credentials(
        api_key: str,
        api_secret: str,
        session_token: str
    ):
        """
        Save credentials to session state.
        
        Args:
            api_key: API key
            api_secret: API secret
            session_token: Session token
        """
        st.session_state.api_key = api_key
        st.session_state.api_secret = api_secret
        st.session_state.session_token = session_token
        st.session_state.login_time = datetime.now(C.IST).isoformat()
    
    @staticmethod
    def clear_runtime_credentials():
        """Clear credentials from session state."""
        for key in ("api_key", "api_secret", "session_token", "login_time"):
            if key in st.session_state:
                if key == "login_time":
                    st.session_state[key] = None
                else:
                    st.session_state[key] = ""


# ═══════════════════════════════════════════════════════════════════
# SESSION STATE MANAGER
# ═══════════════════════════════════════════════════════════════════

class SessionState:
    """
    Centralized session state management.
    """
    
    # Default values for session state
    DEFAULTS = {
        "authenticated": False,
        "breeze_client": None,
        "current_page": "Dashboard",
        "selected_instrument": "NIFTY",
        "api_key": "",
        "api_secret": "",
        "session_token": "",
        "login_time": None,
        "user_name": "",
        "user_id": "",
        "debug_mode": False,
        "activity_log": [],
        "last_refresh": {},
    }
    
    @staticmethod
    def initialize():
        """Initialize session state with default values."""
        for key, default_value in SessionState.DEFAULTS.items():
            if key not in st.session_state:
                st.session_state[key] = default_value
    
    # ─── Authentication ───────────────────────────────────────────
    
    @staticmethod
    def is_authenticated() -> bool:
        """Check if user is authenticated."""
        return st.session_state.get("authenticated", False)
    
    @staticmethod
    def get_client():
        """Get Breeze API client instance."""
        return st.session_state.get("breeze_client")
    
    @staticmethod
    def set_authentication(authenticated: bool, client=None):
        """
        Set authentication status.
        
        Args:
            authenticated: Authentication status
            client: API client instance
        """
        st.session_state.authenticated = authenticated
        st.session_state.breeze_client = client
    
    # ─── Navigation ───────────────────────────────────────────────
    
    @staticmethod
    def get_current_page() -> str:
        """Get current page name."""
        return st.session_state.get("current_page", "Dashboard")
    
    @staticmethod
    def navigate_to(page: str):
        """
        Navigate to a page.
        
        Args:
            page: Page name
        """
        st.session_state.current_page = page
    
    # ─── Activity Logging ─────────────────────────────────────────
    
    @staticmethod
    def log_activity(action: str, detail: str = ""):
        """
        Log user activity.
        
        Args:
            action: Action performed
            detail: Additional details
        """
        if "activity_log" not in st.session_state:
            st.session_state.activity_log = []
        
        entry = {
            "timestamp": datetime.now(C.IST).isoformat(),
            "time": datetime.now(C.IST).strftime("%H:%M:%S"),
            "action": action,
            "detail": detail
        }
        
        st.session_state.activity_log.insert(0, entry)
        
        # Keep only recent entries
        st.session_state.activity_log = st.session_state.activity_log[:C.MAX_ACTIVITY_LOG_ENTRIES]
    
    @staticmethod
    def get_activity_log() -> List[Dict[str, str]]:
        """Get activity log."""
        return st.session_state.get("activity_log", [])
    
    # ─── Session Health ───────────────────────────────────────────
    
    @staticmethod
    def get_login_duration() -> Optional[str]:
        """
        Get duration since login.
        
        Returns:
            Human-readable duration string, or None
        """
        login_time = st.session_state.get("login_time")
        if not login_time:
            return None
        
        try:
            login_dt = datetime.fromisoformat(login_time)
            now = datetime.now(C.IST)
            
            # Ensure timezone awareness
            if login_dt.tzinfo is None:
                login_dt = C.IST.localize(login_dt)
            
            delta = now - login_dt
            total_seconds = int(delta.total_seconds())
            
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            return f"{hours}h {minutes}m"
        
        except Exception as e:
            log.error(f"Error calculating login duration: {e}")
            return None
    
    @staticmethod
    def is_session_stale() -> bool:
        """
        Check if session is stale (> 7 hours).
        
        Returns:
            True if stale, False otherwise
        """
        login_time = st.session_state.get("login_time")
        if not login_time:
            return True
        
        try:
            login_dt = datetime.fromisoformat(login_time)
            now = datetime.now(C.IST)
            
            if login_dt.tzinfo is None:
                login_dt = C.IST.localize(login_dt)
            
            delta = now - login_dt
            return delta.total_seconds() > C.SESSION_WARNING_SECONDS
        
        except Exception:
            return True
    
    @staticmethod
    def is_session_expired() -> bool:
        """
        Check if session has expired (> 8 hours).
        
        Returns:
            True if expired, False otherwise
        """
        login_time = st.session_state.get("login_time")
        if not login_time:
            return True
        
        try:
            login_dt = datetime.fromisoformat(login_time)
            now = datetime.now(C.IST)
            
            if login_dt.tzinfo is None:
                login_dt = C.IST.localize(login_dt)
            
            delta = now - login_dt
            return delta.total_seconds() > C.SESSION_TIMEOUT_SECONDS
        
        except Exception:
            return True


# ═══════════════════════════════════════════════════════════════════
# CACHE MANAGER
# ═══════════════════════════════════════════════════════════════════

class CacheManager:
    """
    Advanced caching with TTL and size limits.
    """
    
    @staticmethod
    def _get_cache_key(key: str, cache_type: str) -> str:
        """Generate unique cache key."""
        return f"{cache_type}_{hashlib.md5(key.encode()).hexdigest()}"
    
    @staticmethod
    def set(key: str, value: Any, cache_type: str = "general", ttl: int = 30):
        """
        Store value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            cache_type: Type of cache (option_chain, quotes, positions, etc.)
            ttl: Time to live in seconds
        """
        cache_key = CacheManager._get_cache_key(key, cache_type)
        
        if f"{cache_type}_cache" not in st.session_state:
            st.session_state[f"{cache_type}_cache"] = {}
        
        if f"{cache_type}_cache_ts" not in st.session_state:
            st.session_state[f"{cache_type}_cache_ts"] = {}
        
        # Store value and timestamp
        st.session_state[f"{cache_type}_cache"][cache_key] = value
        st.session_state[f"{cache_type}_cache_ts"][cache_key] = {
            "timestamp": datetime.now(),
            "ttl": ttl
        }
    
    @staticmethod
    def get(key: str, cache_type: str = "general") -> Optional[Any]:
        """
        Retrieve value from cache.
        
        Args:
            key: Cache key
            cache_type: Type of cache
        
        Returns:
            Cached value or None if expired/not found
        """
        cache_key = CacheManager._get_cache_key(key, cache_type)
        
        cache = st.session_state.get(f"{cache_type}_cache", {})
        cache_ts = st.session_state.get(f"{cache_type}_cache_ts", {})
        
        if cache_key not in cache:
            return None
        
        # Check if expired
        if cache_key in cache_ts:
            ts_info = cache_ts[cache_key]
            timestamp = ts_info["timestamp"]
            ttl = ts_info["ttl"]
            
            elapsed = (datetime.now() - timestamp).total_seconds()
            
            if elapsed > ttl:
                # Expired - remove from cache
                CacheManager.invalidate(key, cache_type)
                return None
        
        return cache[cache_key]
    
    @staticmethod
    def invalidate(key: str, cache_type: str = "general"):
        """
        Invalidate (delete) cache entry.
        
        Args:
            key: Cache key
            cache_type: Type of cache
        """
        cache_key = CacheManager._get_cache_key(key, cache_type)
        
        cache = st.session_state.get(f"{cache_type}_cache", {})
        cache_ts = st.session_state.get(f"{cache_type}_cache_ts", {})
        
        cache.pop(cache_key, None)
        cache_ts.pop(cache_key, None)
    
    @staticmethod
    def clear_all(cache_type: Optional[str] = None):
        """
        Clear all cache or specific cache type.
        
        Args:
            cache_type: Type of cache to clear, or None for all
        """
        if cache_type:
            st.session_state[f"{cache_type}_cache"] = {}
            st.session_state[f"{cache_type}_cache_ts"] = {}
        else:
            # Clear all caches
            keys_to_clear = [k for k in st.session_state.keys() 
                           if k.endswith("_cache") or k.endswith("_cache_ts")]
            for key in keys_to_clear:
                st.session_state[key] = {}
    
    # ─── Convenience Methods ──────────────────────────────────────
    
    @staticmethod
    def cache_option_chain(instrument: str, expiry: str, data: Any):
        """Cache option chain data."""
        key = f"{instrument}_{expiry}"
        CacheManager.set(key, data, "option_chain", C.OC_CACHE_TTL_SECONDS)
    
    @staticmethod
    def get_option_chain(instrument: str, expiry: str) -> Optional[Any]:
        """Get cached option chain data."""
        key = f"{instrument}_{expiry}"
        return CacheManager.get(key, "option_chain")
    
    @staticmethod
    def cache_quote(instrument: str, strike: int, option_type: str, data: Any):
        """Cache quote data."""
        key = f"{instrument}_{strike}_{option_type}"
        CacheManager.set(key, data, "quote", C.QUOTE_CACHE_TTL_SECONDS)
    
    @staticmethod
    def get_quote(instrument: str, strike: int, option_type: str) -> Optional[Any]:
        """Get cached quote data."""
        key = f"{instrument}_{strike}_{option_type}"
        return CacheManager.get(key, "quote")


# ═══════════════════════════════════════════════════════════════════
# NOTIFICATION MANAGER
# ═══════════════════════════════════════════════════════════════════

class Notifications:
    """Handle user notifications and toasts."""
    
    @staticmethod
    def show(message: str, icon: str = "ℹ️"):
        """
        Show toast notification.
        
        Args:
            message: Notification message
            icon: Emoji icon
        """
        try:
            st.toast(f"{icon} {message}", icon=icon)
        except Exception as e:
            log.debug(f"Toast failed: {e}")
    
    @staticmethod
    def success(message: str):
        """Show success notification."""
        Notifications.show(message, "✅")
    
    @staticmethod
    def error(message: str):
        """Show error notification."""
        Notifications.show(message, "❌")
    
    @staticmethod
    def warning(message: str):
        """Show warning notification."""
        Notifications.show(message, "⚠️")
    
    @staticmethod
    def info(message: str):
        """Show info notification."""
        Notifications.show(message, "ℹ️")
