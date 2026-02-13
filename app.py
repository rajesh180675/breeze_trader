"""
Breeze Options Trader - Main Application
Ultra-Enhanced Production Version v7.0.0

STREAMLIT 1.54+ COMPATIBLE - Uses width='stretch' instead of use_container_width
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from functools import wraps
import time
import logging
from typing import Optional, Dict, List, Any, Callable
import traceback

# Local imports
import app_config as C
from helpers import (
    APIResponse, safe_int, safe_float, safe_str,
    detect_position_type, get_closing_action, calculate_pnl,
    calculate_unrealized_pnl, calculate_margin_used,
    process_option_chain, create_pivot_table,
    calculate_pcr, calculate_max_pain, estimate_atm_strike,
    add_greeks_to_chain, get_market_status, format_currency,
    format_expiry, format_percentage, calculate_days_to_expiry
)
from session_manager import (
    Credentials, SessionState, CacheManager, Notifications
)
from breeze_api import BreezeAPIClient
from validators import (
    OrderRequest, QuoteRequest, OptionChainRequest,
    SquareOffRequest, validate_date_range
)
from analytics import (
    calculate_greeks, estimate_implied_volatility,
    calculate_portfolio_greeks, calculate_strategy_payoff,
    calculate_var, calculate_max_drawdown, calculate_sharpe_ratio,
    calculate_win_rate
)

# ═══════════════════════════════════════════════════════════════════
# LOGGING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('breeze_trader.log', mode='a', encoding='utf-8')
    ]
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# PAGE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Breeze Options Trader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/breeze-trader/docs',
        'Report a bug': 'https://github.com/breeze-trader/issues',
        'About': """
        # Breeze Options Trader v7.0
        Professional options trading platform for ICICI Direct Breeze API.
        """
    }
)

# ═══════════════════════════════════════════════════════════════════
# CUSTOM CSS
# ═══════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    :root {
        --primary-color: #1f77b4;
        --secondary-color: #2ecc71;
        --danger-color: #dc3545;
        --warning-color: #ffc107;
        --success-color: #28a745;
        --dark-color: #2c3e50;
        --light-color: #f8f9fa;
        --border-radius: 8px;
        --shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-align: center;
        padding: 1rem 0;
        margin-bottom: 0.5rem;
    }
    
    .page-header {
        font-size: 2rem;
        font-weight: 700;
        color: var(--primary-color);
        border-bottom: 4px solid var(--primary-color);
        padding-bottom: 0.5rem;
        margin-bottom: 1.5rem;
    }
    
    .section-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: var(--dark-color);
        margin-top: 1.5rem;
        margin-bottom: 1rem;
    }
    
    .status-connected {
        background: #d4edda;
        color: #155724;
        padding: 6px 14px;
        border-radius: 16px;
        font-weight: 600;
        font-size: 0.9rem;
        display: inline-block;
        box-shadow: var(--shadow);
    }
    
    .status-disconnected {
        background: #f8d7da;
        color: #721c24;
        padding: 6px 14px;
        border-radius: 16px;
        font-weight: 600;
        font-size: 0.9rem;
        display: inline-block;
    }
    
    .market-open { color: var(--success-color); font-weight: 700; font-size: 1.1rem; }
    .market-closed { color: var(--danger-color); font-weight: 700; font-size: 1.1rem; }
    .market-pre { color: var(--warning-color); font-weight: 700; font-size: 1.1rem; }
    
    .profit { color: var(--success-color) !important; font-weight: 700; }
    .loss { color: var(--danger-color) !important; font-weight: 700; }
    .neutral { color: #6c757d !important; }
    
    .info-box {
        background: linear-gradient(135deg, #e7f3ff 0%, #f0f7ff 100%);
        border-left: 5px solid #2196F3;
        padding: 1rem 1.25rem;
        margin: 1rem 0;
        border-radius: 0 var(--border-radius) var(--border-radius) 0;
        box-shadow: var(--shadow);
    }
    
    .success-box {
        background: linear-gradient(135deg, #d4edda 0%, #e8f5e9 100%);
        border-left: 5px solid var(--success-color);
        padding: 1rem 1.25rem;
        margin: 1rem 0;
        border-radius: 0 var(--border-radius) var(--border-radius) 0;
    }
    
    .warning-box {
        background: linear-gradient(135deg, #fff3cd 0%, #fff8e1 100%);
        border-left: 5px solid var(--warning-color);
        padding: 1rem 1.25rem;
        margin: 1rem 0;
        border-radius: 0 var(--border-radius) var(--border-radius) 0;
    }
    
    .danger-box {
        background: linear-gradient(135deg, #f8d7da 0%, #ffebee 100%);
        border-left: 5px solid var(--danger-color);
        padding: 1rem 1.25rem;
        margin: 1rem 0;
        border-radius: 0 var(--border-radius) var(--border-radius) 0;
    }
    
    .metric-card {
        background: var(--light-color);
        padding: 1.25rem;
        border-radius: var(--border-radius);
        border: 1px solid #dee2e6;
        box-shadow: var(--shadow);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }
    
    .atm-strike {
        background-color: #fff3cd !important;
        font-weight: 700 !important;
        border: 2px solid var(--warning-color) !important;
    }
    
    .empty-state {
        text-align: center;
        padding: 3rem 1rem;
        color: #6c757d;
    }
    
    .empty-state-icon {
        font-size: 4rem;
        margin-bottom: 1rem;
        opacity: 0.5;
    }
    
    .leg-card {
        background: white;
        border: 2px solid #e0e0e0;
        border-radius: var(--border-radius);
        padding: 1rem;
        margin: 0.5rem 0;
    }
    
    .leg-card.buy { border-left: 4px solid var(--success-color); }
    .leg-card.sell { border-left: 4px solid var(--danger-color); }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    @media (max-width: 768px) {
        .main-header { font-size: 1.8rem; }
        .page-header { font-size: 1.5rem; }
    }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════
# GLOBAL CONSTANTS
# ═══════════════════════════════════════════════════════════════════

PAGES: List[str] = [
    "Dashboard",
    "Option Chain",
    "Sell Options",
    "Square Off",
    "Orders & Trades",
    "Positions",
    "Strategy Builder",
    "Analytics"
]

PAGE_ICONS: Dict[str, str] = {
    "Dashboard": "🏠",
    "Option Chain": "📊",
    "Sell Options": "💰",
    "Square Off": "🔄",
    "Orders & Trades": "📋",
    "Positions": "📍",
    "Strategy Builder": "🎯",
    "Analytics": "📈"
}

AUTH_REQUIRED_PAGES: set = set(PAGES[1:])

# ═══════════════════════════════════════════════════════════════════
# UTILITY DECORATORS
# ═══════════════════════════════════════════════════════════════════

def error_handler(func: Callable) -> Callable:
    """Decorator for graceful error handling."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.error(f"Error in {func.__name__}: {e}", exc_info=True)
            st.error(f"❌ An error occurred: {str(e)}")
            
            if st.session_state.get("debug_mode", False):
                st.exception(e)
                with st.expander("🔧 Debug Traceback"):
                    st.code(traceback.format_exc())
            
            st.info("💡 Try refreshing the page or reconnecting if the issue persists.")
    return wrapper


def require_auth(func: Callable) -> Callable:
    """Decorator to require authentication."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not SessionState.is_authenticated():
            st.warning("🔒 Please login to access this page")
            st.info("👈 Use the sidebar to enter your credentials")
            return None
        return func(*args, **kwargs)
    return wrapper


def check_session_validity(func: Callable) -> Callable:
    """Decorator to check session validity."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if SessionState.is_authenticated():
            if SessionState.is_session_expired():
                st.error("🔴 Your session has expired. Please reconnect.")
                if st.button("🔄 Reconnect Now", type="primary", width="stretch"):
                    SessionState.set_authentication(False, None)
                    SessionState.navigate_to("Dashboard")
                    st.rerun()
                return None
            
            if SessionState.is_session_stale():
                st.warning("⚠️ Session may be stale. Consider refreshing your connection.")
        
        return func(*args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def show_empty_state(icon: str, message: str, suggestion: str = "", action_button: Dict = None) -> None:
    """Display empty state with icon and message."""
    st.markdown(
        f'''
        <div class="empty-state">
            <div class="empty-state-icon">{icon}</div>
            <h3>{message}</h3>
            <p>{suggestion}</p>
        </div>
        ''',
        unsafe_allow_html=True
    )
    
    if action_button:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button(
                action_button.get("label", "Action"),
                type=action_button.get("type", "secondary"),
                width="stretch"
            ):
                if "page" in action_button:
                    SessionState.navigate_to(action_button["page"])
                    st.rerun()


def safe_get_client() -> Optional[BreezeAPIClient]:
    """Safely get API client with validation."""
    client = SessionState.get_client()
    
    if not client:
        st.error("❌ Not connected to Breeze API")
        st.info("👈 Please login using the sidebar")
        return None
    
    if not client.connected:
        st.error("❌ Connection lost. Please reconnect.")
        if st.button("🔄 Reconnect", width="stretch"):
            SessionState.set_authentication(False, None)
            st.rerun()
        return None
    
    return client


def create_download_button(data: pd.DataFrame, filename: str, label: str = "📥 Download") -> None:
    """Create download button for DataFrame."""
    csv = data.to_csv(index=False)
    st.download_button(
        label=label,
        data=csv,
        file_name=f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        width="stretch"
    )


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

def render_sidebar() -> None:
    """Render complete sidebar."""
    with st.sidebar:
        st.markdown("## 📈 Breeze Trader")
        st.markdown("*Professional Options Platform*")
        st.markdown("---")
        
        render_navigation()
        st.markdown("---")
        
        if SessionState.is_authenticated():
            render_authenticated_sidebar()
        else:
            render_login_sidebar()
        
        st.markdown("---")
        render_settings_sidebar()
        
        st.markdown("---")
        st.caption("v7.0.0 Production")
        st.caption(f"© {datetime.now().year} Breeze Trader")


def render_navigation() -> None:
    """Render navigation menu."""
    available_pages = PAGES if SessionState.is_authenticated() else ["Dashboard"]
    current_page = SessionState.get_current_page()
    
    if current_page not in available_pages:
        current_page = "Dashboard"
        SessionState.navigate_to("Dashboard")
    
    try:
        current_index = available_pages.index(current_page)
    except ValueError:
        current_index = 0
    
    selected_page = st.radio(
        "Navigation",
        available_pages,
        index=current_index,
        format_func=lambda p: f"{PAGE_ICONS.get(p, '📄')} {p}",
        label_visibility="collapsed",
        key="nav_radio"
    )
    
    if selected_page != current_page:
        SessionState.navigate_to(selected_page)
        log.info(f"Navigation: {current_page} -> {selected_page}")
        st.rerun()


def render_login_sidebar() -> None:
    """Render login section."""
    has_stored = Credentials.has_stored_credentials()
    
    if has_stored:
        st.markdown("### 🔑 Daily Login")
        st.markdown(
            '<div class="success-box">'
            '✅ API credentials loaded from secrets.<br>'
            'Enter today\'s <b>Session Token</b>.'
            '</div>',
            unsafe_allow_html=True
        )
        
        with st.form("quick_login", clear_on_submit=False):
            session_token = st.text_input(
                "Session Token",
                type="password",
                placeholder="Paste from ICICI Direct",
                help="Get fresh token daily from ICICI Direct portal"
            )
            
            submitted = st.form_submit_button("🔑 Connect", use_container_width=True)
            
            if submitted:
                if not session_token or len(session_token.strip()) < 10:
                    st.warning("Please enter a valid session token")
                else:
                    api_key, api_secret, _ = Credentials.get_all_credentials()
                    perform_login(api_key, api_secret, session_token.strip())
        
        with st.expander("🔧 Use different credentials"):
            render_full_login_form()
    else:
        st.markdown("### 🔐 Login Required")
        st.markdown(
            '<div class="info-box">'
            '💡 Store API Key & Secret in Streamlit Secrets for quick daily login.'
            '</div>',
            unsafe_allow_html=True
        )
        render_full_login_form()


def render_full_login_form() -> None:
    """Render complete login form."""
    with st.form("full_login", clear_on_submit=False):
        api_key, api_secret, _ = Credentials.get_all_credentials()
        
        new_key = st.text_input("API Key", value=api_key, type="password")
        new_secret = st.text_input("API Secret", value=api_secret, type="password")
        session_token = st.text_input("Session Token", type="password")
        
        st.caption("⚠️ Token expires daily. Get fresh token from ICICI Direct.")
        
        submitted = st.form_submit_button("🔑 Connect", use_container_width=True)
        
        if submitted:
            if not all([new_key, new_secret, session_token]):
                st.warning("Please fill in all credential fields")
            else:
                perform_login(new_key.strip(), new_secret.strip(), session_token.strip())


def perform_login(api_key: str, api_secret: str, session_token: str) -> None:
    """Perform login with credentials."""
    with st.spinner("🔄 Connecting to Breeze API..."):
        try:
            client = BreezeAPIClient(api_key, api_secret)
            response = client.connect(session_token)
            
            if response["success"]:
                Credentials.save_runtime_credentials(api_key, api_secret, session_token)
                SessionState.set_authentication(True, client)
                SessionState.log_activity("Login", "Connected to Breeze API successfully")
                
                Notifications.success("✅ Connected successfully!")
                log.info("User authenticated successfully")
                time.sleep(0.5)
                st.rerun()
            else:
                error_msg = response.get('message', 'Unknown error')
                st.error(f"❌ Connection failed: {error_msg}")
                
                if "token" in error_msg.lower():
                    st.info("💡 Your session token may be expired. Get a fresh token from ICICI Direct.")
                
                log.warning(f"Login failed: {error_msg}")
        
        except Exception as e:
            log.error(f"Login exception: {e}", exc_info=True)
            st.error(f"❌ Connection error: {str(e)}")


def render_authenticated_sidebar() -> None:
    """Render sidebar for authenticated users."""
    st.markdown(
        '<span class="status-connected">✅ Connected</span>',
        unsafe_allow_html=True
    )
    
    client = SessionState.get_client()
    
    # User info
    if client:
        try:
            user_name = st.session_state.get('user_name')
            
            if not user_name:
                response = client.get_customer_details()
                if response["success"]:
                    parsed = APIResponse(response)
                    user_name = parsed.get("name", "Trader")
                    st.session_state.user_name = user_name
                    st.session_state.user_id = parsed.get("user_id", "")
            
            st.markdown(f"**👤 {user_name}**")
        except Exception:
            st.markdown(f"**👤 {st.session_state.get('user_name', 'Trader')}**")
    
    # Session duration
    duration = SessionState.get_login_duration()
    if duration:
        st.caption(f"⏱️ Session: {duration}")
    
    # Session health
    if SessionState.is_session_expired():
        st.error("🔴 Session expired")
    elif SessionState.is_session_stale():
        st.warning("⚠️ Session may be stale")
    
    # Market status
    st.markdown("---")
    market_status = get_market_status()
    if "Open" in market_status:
        st.markdown(f'<p class="market-open">🟢 {market_status}</p>', unsafe_allow_html=True)
    elif "Pre" in market_status:
        st.markdown(f'<p class="market-pre">🟡 {market_status}</p>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p class="market-closed">🔴 {market_status}</p>', unsafe_allow_html=True)
    
    # Margin display
    if client:
        try:
            cached_margin = CacheManager.get("margin_data", "general")
            
            if cached_margin is None:
                response = client.get_funds()
                if response["success"]:
                    parsed = APIResponse(response)
                    cached_margin = {
                        "available": safe_float(parsed.get("available_margin", 0)),
                        "used": safe_float(parsed.get("utilized_margin", 0))
                    }
                    CacheManager.set("margin_data", cached_margin, "general", 60)
            
            if cached_margin:
                st.metric(
                    "Available Margin",
                    format_currency(cached_margin["available"]),
                    help="Available margin for trading"
                )
        except Exception as e:
            log.debug(f"Could not fetch margin: {e}")
    
    # Disconnect button
    st.markdown("---")
    if st.button("🔓 Disconnect", width="stretch"):
        SessionState.set_authentication(False, None)
        Credentials.clear_runtime_credentials()
        CacheManager.clear_all()
        SessionState.log_activity("Logout", "Disconnected from Breeze API")
        SessionState.navigate_to("Dashboard")
        st.rerun()


def render_settings_sidebar() -> None:
    """Render settings section."""
    with st.expander("⚙️ Settings"):
        st.selectbox(
            "Default Instrument",
            list(C.INSTRUMENTS.keys()),
            key="selected_instrument"
        )
        
        st.session_state.debug_mode = st.checkbox(
            "🔧 Debug Mode",
            value=st.session_state.get("debug_mode", False)
        )
        
        st.session_state.auto_refresh = st.checkbox(
            "🔄 Auto Refresh (30s)",
            value=st.session_state.get("auto_refresh", False)
        )


# ═══════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@error_handler
def page_dashboard() -> None:
    """Dashboard with portfolio overview."""
    st.markdown('<h1 class="page-header">🏠 Dashboard</h1>', unsafe_allow_html=True)
    
    if not SessionState.is_authenticated():
        render_welcome_dashboard()
    else:
        render_authenticated_dashboard()


def render_welcome_dashboard() -> None:
    """Welcome screen for non-authenticated users."""
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <h2>Welcome to Breeze Options Trader</h2>
        <p style="font-size: 1.2rem; color: #666;">
            Professional options trading platform for ICICI Direct Breeze API
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        ### 📊 Market Data
        - Live option chains
        - Real-time Greeks (Δ, Γ, Θ, ν)
        - OI analysis & PCR
        - Max Pain indicators
        """)
    
    with col2:
        st.markdown("""
        ### 💰 Smart Trading
        - One-click option selling
        - Multi-leg strategy builder
        - Quick square-off
        - Order management
        """)
    
    with col3:
        st.markdown("""
        ### 🛡️ Risk Management
        - Portfolio Greeks
        - Real-time P&L tracking
        - Margin monitoring
        - Risk analytics
        """)
    
    st.markdown("---")
    
    # Supported instruments
    st.markdown('<h2 class="section-header">📈 Supported Instruments</h2>', unsafe_allow_html=True)
    
    instruments_data = []
    for name, config in C.INSTRUMENTS.items():
        instruments_data.append({
            "Instrument": name,
            "Description": config.description,
            "Exchange": config.exchange,
            "Lot Size": f"{config.lot_size:,}",
            "Strike Gap": f"{config.strike_gap:,}",
            "Weekly Expiry": config.expiry_day
        })
    
    st.dataframe(pd.DataFrame(instruments_data), width="stretch", hide_index=True)
    
    st.info("👈 **Login** using the sidebar to access all trading features")


@check_session_validity
def render_authenticated_dashboard() -> None:
    """Dashboard for authenticated users."""
    client = safe_get_client()
    if not client:
        return
    
    st.markdown('<h2 class="section-header">📊 Portfolio Summary</h2>', unsafe_allow_html=True)
    
    # Fetch data
    try:
        with st.spinner("Loading portfolio data..."):
            funds_response = client.get_funds()
            positions_response = client.get_positions()
    except Exception as e:
        log.error(f"Failed to fetch portfolio data: {e}")
        st.error("❌ Failed to load portfolio data. Please try again.")
        return
    
    # Margin metrics
    col1, col2, col3, col4 = st.columns(4)
    
    if funds_response["success"]:
        parsed_funds = APIResponse(funds_response)
        available = safe_float(parsed_funds.get("available_margin", 0))
        used = safe_float(parsed_funds.get("utilized_margin", 0))
        
        # Handle case where margins are nested differently
        if available == 0 and used == 0:
            # Try alternative field names
            data = parsed_funds.data
            if "total_bank_balance" in data:
                available = safe_float(data.get("unallocated_balance", 0))
                used = safe_float(data.get("allocated_fno", 0))
        
        total = available + used
        
        with col1:
            st.metric("Available Margin", format_currency(available))
        with col2:
            st.metric("Used Margin", format_currency(used))
        with col3:
            st.metric("Total Margin", format_currency(total))
        with col4:
            utilization = (used / total * 100) if total > 0 else 0
            st.metric("Utilization", f"{utilization:.1f}%")
    else:
        st.warning(f"⚠️ Could not load margin data")
    
    st.markdown("---")
    
    # Open Positions
    st.markdown('<h2 class="section-header">📍 Open Option Positions</h2>', unsafe_allow_html=True)
    
    if not positions_response["success"]:
        st.error(f"❌ Could not load positions")
        return
    
    parsed_positions = APIResponse(positions_response)
    all_positions = parsed_positions.items
    
    # Filter option positions using the config helper
    option_positions = []
    for pos in all_positions:
        try:
            qty = safe_int(pos.get("quantity", 0))
            if qty == 0:
                continue
            if not C.is_option_position(pos):
                continue
            option_positions.append(pos)
        except Exception as e:
            log.debug(f"Skipping position: {e}")
            continue
    
    # Debug info
    if st.session_state.get("debug_mode"):
        with st.expander("🔧 Debug: All Positions"):
            st.write(f"Total positions: {len(all_positions)}")
            st.write(f"Option positions: {len(option_positions)}")
            for i, pos in enumerate(all_positions[:5]):
                st.write(f"Position {i+1}: segment={pos.get('segment')}, product_type={pos.get('product_type')}, right={pos.get('right')}")
    
    if not option_positions:
        show_empty_state(
            "📭",
            "No open option positions",
            "Start trading to see your positions here",
            {"label": "💰 Sell Options", "page": "Sell Options", "type": "primary"}
        )
    else:
        total_pnl = 0.0
        position_rows = []
        
        for pos in option_positions:
            try:
                qty = safe_int(pos.get("quantity", 0))
                pos_type = detect_position_type(pos)
                avg_price = safe_float(pos.get("average_price", 0))
                ltp = safe_float(pos.get("ltp", avg_price))
                
                pnl = calculate_pnl(pos_type, avg_price, ltp, abs(qty))
                total_pnl += pnl
                
                position_rows.append({
                    "Instrument": C.api_code_to_display(pos.get("stock_code", "")),
                    "Strike": pos.get("strike_price", "N/A"),
                    "Type": C.normalize_option_type(pos.get("right", "")),
                    "Position": pos_type.upper(),
                    "Qty": abs(qty),
                    "Avg": f"₹{avg_price:.2f}",
                    "LTP": f"₹{ltp:.2f}",
                    "P&L": pnl
                })
            except Exception as e:
                log.error(f"Error processing position: {e}")
                continue
        
        if position_rows:
            df = pd.DataFrame(position_rows)
            df["P&L Display"] = df["P&L"].apply(lambda x: f"₹{x:+,.2f}")
            display_df = df.drop(columns=["P&L"]).rename(columns={"P&L Display": "P&L"})
            
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.dataframe(display_df, width="stretch", hide_index=True)
            
            with col2:
                pnl_class = "profit" if total_pnl >= 0 else "loss"
                pnl_emoji = "📈" if total_pnl >= 0 else "📉"
                
                st.markdown(
                    f'''
                    <div class="metric-card">
                        <h4 style="margin:0;">Total P&L {pnl_emoji}</h4>
                        <h2 class="{pnl_class}" style="margin:0.5rem 0;">{format_currency(total_pnl)}</h2>
                    </div>
                    ''',
                    unsafe_allow_html=True
                )
                
                st.metric("Positions", len(option_positions))
    
    st.markdown("---")
    
    # Quick Actions
    st.markdown('<h2 class="section-header">⚡ Quick Actions</h2>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("📊 Option Chain", width="stretch"):
            SessionState.navigate_to("Option Chain")
            st.rerun()
    
    with col2:
        if st.button("💰 Sell Options", width="stretch"):
            SessionState.navigate_to("Sell Options")
            st.rerun()
    
    with col3:
        if st.button("🔄 Square Off", width="stretch"):
            SessionState.navigate_to("Square Off")
            st.rerun()
    
    with col4:
        if st.button("📋 Orders", width="stretch"):
            SessionState.navigate_to("Orders & Trades")
            st.rerun()
    
    # Recent Activity
    activity_log = SessionState.get_activity_log()
    if activity_log:
        st.markdown("---")
        with st.expander("📝 Recent Activity", expanded=False):
            st.dataframe(pd.DataFrame(activity_log[:10]), width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════
# PAGE: OPTION CHAIN
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session_validity
def page_option_chain() -> None:
    """Advanced option chain with Greeks."""
    st.markdown('<h1 class="page-header">📊 Option Chain</h1>', unsafe_allow_html=True)
    
    client = safe_get_client()
    if not client:
        return
    
    # Controls
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        instrument = st.selectbox(
            "Instrument",
            list(C.INSTRUMENTS.keys()),
            key="oc_instrument"
        )
    
    instrument_config = C.get_instrument(instrument)
    
    with col2:
        expiries = C.get_next_expiries(instrument, 5)
        if not expiries:
            st.error(f"❌ Could not calculate expiries for {instrument}")
            return
        
        expiry = st.selectbox("Expiry", expiries, format_func=format_expiry, key="oc_expiry")
    
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh_clicked = st.button("🔄 Refresh", width="stretch", key="oc_refresh")
    
    # View options
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    
    with col1:
        view_mode = st.radio("View Mode", ["Traditional", "Flat", "Calls Only", "Puts Only"], horizontal=True, key="oc_view")
    
    with col2:
        strikes_count = st.slider("Strikes ±ATM", 5, 50, 15, key="oc_strikes")
    
    with col3:
        show_greeks = st.checkbox("Show Greeks", value=True, key="oc_greeks")
    
    with col4:
        show_oi = st.checkbox("OI Chart", value=True, key="oc_oi_chart")
    
    # Cache handling
    cache_key = f"oc_{instrument_config.api_code}_{expiry}"
    
    if refresh_clicked:
        CacheManager.invalidate(cache_key, "option_chain")
        st.rerun()
    
    # Try cached data
    cached_df = CacheManager.get(cache_key, "option_chain")
    
    if cached_df is not None:
        df = cached_df
        st.caption("📦 Using cached data (30s TTL)")
    else:
        with st.spinner(f"Loading {instrument} option chain..."):
            try:
                response = client.get_option_chain(
                    instrument_config.api_code,
                    instrument_config.exchange,
                    expiry
                )
            except Exception as e:
                log.error(f"Option chain fetch error: {e}")
                st.error("❌ Failed to load option chain.")
                return
        
        if not response["success"]:
            st.error(f"❌ {response.get('message', 'Failed to fetch option chain')}")
            return
        
        df = process_option_chain(response.get("data", {}))
        
        if df.empty:
            st.warning("No option chain data available")
            return
        
        CacheManager.set(cache_key, df, "option_chain", C.OC_CACHE_TTL_SECONDS)
        SessionState.log_activity("Option Chain", f"Loaded {instrument} {format_expiry(expiry)}")
    
    # Display header
    st.markdown(f"### {instrument} ({instrument_config.api_code}) — {format_expiry(expiry)}")
    
    # Analytics
    days_left = calculate_days_to_expiry(expiry)
    pcr = calculate_pcr(df)
    max_pain = calculate_max_pain(df)
    atm_strike = estimate_atm_strike(df)
    
    call_oi = df[df["right"] == "Call"]["open_interest"].sum() if "right" in df.columns else 0
    put_oi = df[df["right"] == "Put"]["open_interest"].sum() if "right" in df.columns else 0
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        pcr_delta = "Bullish" if pcr > 1 else "Bearish" if pcr < 0.7 else "Neutral"
        st.metric("PCR", f"{pcr:.2f}", pcr_delta)
    with col2:
        st.metric("Max Pain", f"{max_pain:,.0f}")
    with col3:
        st.metric("ATM ≈", f"{atm_strike:,.0f}")
    with col4:
        st.metric("Days to Expiry", days_left)
    with col5:
        st.metric("Total OI", f"{(call_oi + put_oi):,.0f}")
    
    st.markdown("---")
    
    # Filter strikes
    if "strike_price" in df.columns and atm_strike > 0:
        strikes = sorted(df["strike_price"].unique())
        if strikes:
            atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_strike))
            start_idx = max(0, atm_idx - strikes_count)
            end_idx = min(len(strikes), atm_idx + strikes_count + 1)
            filtered_strikes = strikes[start_idx:end_idx]
            display_df = df[df["strike_price"].isin(filtered_strikes)].copy()
        else:
            display_df = df.copy()
    else:
        display_df = df.copy()
    
    # Add Greeks
    if show_greeks and not display_df.empty:
        try:
            display_df = add_greeks_to_chain(display_df, atm_strike, expiry)
        except Exception as e:
            log.warning(f"Could not calculate Greeks: {e}")
    
    # Render based on view mode
    if view_mode == "Traditional":
        pivot_df = create_pivot_table(display_df)
        if not pivot_df.empty:
            st.dataframe(pivot_df, width="stretch", height=600, hide_index=True)
    elif view_mode == "Calls Only":
        calls_df = display_df[display_df["right"] == "Call"] if "right" in display_df.columns else display_df
        st.dataframe(calls_df, width="stretch", height=600, hide_index=True)
    elif view_mode == "Puts Only":
        puts_df = display_df[display_df["right"] == "Put"] if "right" in display_df.columns else display_df
        st.dataframe(puts_df, width="stretch", height=600, hide_index=True)
    else:
        st.dataframe(display_df, width="stretch", height=600, hide_index=True)
    
    # OI Chart
    if show_oi and "right" in display_df.columns:
        st.markdown("---")
        st.markdown('<h3 class="section-header">Open Interest Distribution</h3>', unsafe_allow_html=True)
        
        try:
            calls_oi = display_df[display_df["right"] == "Call"][["strike_price", "open_interest"]].rename(columns={"open_interest": "Call OI"})
            puts_oi = display_df[display_df["right"] == "Put"][["strike_price", "open_interest"]].rename(columns={"open_interest": "Put OI"})
            oi_chart_df = pd.merge(calls_oi, puts_oi, on="strike_price", how="outer").fillna(0)
            oi_chart_df = oi_chart_df.sort_values("strike_price").set_index("strike_price")
            st.bar_chart(oi_chart_df)
        except Exception:
            st.caption("⚠️ Could not display OI chart")


# ═══════════════════════════════════════════════════════════════════
# PAGE: SELL OPTIONS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session_validity
def page_sell_options() -> None:
    """Sell options page."""
    st.markdown('<h1 class="page-header">💰 Sell Options</h1>', unsafe_allow_html=True)
    
    client = safe_get_client()
    if not client:
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📝 Order Details")
        
        instrument = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="sell_instrument")
        instrument_config = C.get_instrument(instrument)
        
        expiries = C.get_next_expiries(instrument, 5)
        expiry = st.selectbox("Expiry", expiries, format_func=format_expiry, key="sell_expiry")
        
        option_type = st.radio("Option Type", ["CE (Call)", "PE (Put)"], horizontal=True, key="sell_option_type")
        option_code = "CE" if "CE" in option_type else "PE"
        
        default_strike = instrument_config.min_strike + 10 * instrument_config.strike_gap
        strike = st.number_input(
            "Strike Price",
            min_value=int(instrument_config.min_strike),
            max_value=int(instrument_config.max_strike),
            value=int(default_strike),
            step=int(instrument_config.strike_gap),
            key="sell_strike"
        )
        
        strike_valid = C.validate_strike(instrument, strike)
        if not strike_valid:
            st.warning(f"⚠️ Strike must be multiple of {instrument_config.strike_gap}")
        
        lots = st.number_input("Number of Lots", min_value=C.MIN_LOTS_PER_ORDER, max_value=C.MAX_LOTS_PER_ORDER, value=1, key="sell_lots")
        quantity = lots * instrument_config.lot_size
        st.info(f"**Total Quantity:** {quantity:,} ({lots} lot{'s' if lots > 1 else ''} × {instrument_config.lot_size:,})")
        
        order_type = st.radio("Order Type", ["Market", "Limit"], horizontal=True, key="sell_order_type")
        
        limit_price = 0.0
        if order_type == "Limit":
            limit_price = st.number_input("Limit Price", min_value=0.0, value=0.0, step=0.05, key="sell_price")
    
    with col2:
        st.markdown("### 📊 Market Information")
        
        if st.button("📊 Get Live Quote", width="stretch", disabled=not strike_valid):
            with st.spinner("Fetching quote..."):
                try:
                    response = client.get_quotes(instrument_config.api_code, instrument_config.exchange, expiry, int(strike), option_code)
                    if response["success"]:
                        parsed = APIResponse(response)
                        items = parsed.items
                        if items:
                            quote = items[0]
                            ltp = safe_float(quote.get("ltp", 0))
                            bid = safe_float(quote.get("best_bid_price", 0))
                            ask = safe_float(quote.get("best_offer_price", 0))
                            
                            st.success("✅ Live Quote")
                            q_col1, q_col2 = st.columns(2)
                            with q_col1:
                                st.metric("LTP", f"₹{ltp:.2f}")
                                st.metric("Bid", f"₹{bid:.2f}")
                            with q_col2:
                                st.metric("Ask", f"₹{ask:.2f}")
                                st.metric("Spread", f"₹{abs(ask - bid):.2f}")
                            
                            premium = ltp * quantity
                            st.markdown(f'<div class="success-box"><strong>Estimated Premium:</strong> {format_currency(premium)}</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"❌ Could not fetch quote: {e}")
        
        st.markdown("---")
        
        if st.button("💰 Calculate Margin", width="stretch", disabled=not strike_valid):
            with st.spinner("Calculating margin..."):
                try:
                    response = client.get_margin(instrument_config.api_code, instrument_config.exchange, expiry, int(strike), option_code, "sell", quantity)
                    if response["success"]:
                        parsed = APIResponse(response)
                        required = safe_float(parsed.get("required_margin", 0))
                        st.success(f"**Required Margin:** {format_currency(required)}")
                except Exception:
                    st.warning("⚠️ Could not calculate margin")
    
    # Risk warning
    st.markdown("---")
    st.markdown(
        '<div class="danger-box">'
        '<h4>⚠️ RISK WARNING - Option Selling</h4>'
        '<p><strong>Option selling carries UNLIMITED RISK potential.</strong></p>'
        '<ul><li>You can lose more than your initial margin</li><li>Losses can escalate rapidly</li><li>Always use stop-loss orders</li></ul>'
        '</div>',
        unsafe_allow_html=True
    )
    
    risk_acknowledged = st.checkbox("✅ I understand and accept the risks of option selling", key="sell_risk_ack")
    
    can_submit = risk_acknowledged and strike > 0 and strike_valid and (order_type == "Market" or limit_price > 0)
    
    if st.button(f"🔴 SELL {quantity:,} {instrument} {strike} {option_code}", type="primary", width="stretch", disabled=not can_submit):
        with st.spinner("Placing order..."):
            try:
                if option_code == "CE":
                    response = client.sell_call(instrument_config.api_code, instrument_config.exchange, expiry, int(strike), quantity, order_type.lower(), limit_price)
                else:
                    response = client.sell_put(instrument_config.api_code, instrument_config.exchange, expiry, int(strike), quantity, order_type.lower(), limit_price)
                
                if response["success"]:
                    parsed = APIResponse(response)
                    order_id = parsed.get("order_id", "Unknown")
                    st.markdown(f'<div class="success-box"><h4>✅ Order Placed!</h4><p>Order ID: {order_id}</p></div>', unsafe_allow_html=True)
                    st.balloons()
                    SessionState.log_activity("Order Placed", f"SELL {instrument} {strike} {option_code} x{quantity}")
                    CacheManager.clear_all()
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(f"❌ Order failed: {response.get('message')}")
            except Exception as e:
                st.error(f"❌ Order failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# PAGE: SQUARE OFF
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session_validity
def page_square_off() -> None:
    """Square off positions page."""
    st.markdown('<h1 class="page-header">🔄 Square Off Positions</h1>', unsafe_allow_html=True)
    
    client = safe_get_client()
    if not client:
        return
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Refresh", width="stretch"):
            CacheManager.invalidate("positions", "general")
            st.rerun()
    
    with st.spinner("Loading positions..."):
        response = client.get_positions()
    
    if not response["success"]:
        st.error(f"❌ Failed to load positions")
        return
    
    parsed = APIResponse(response)
    all_positions = parsed.items
    
    # Filter option positions
    option_positions = []
    for pos in all_positions:
        try:
            if not C.is_option_position(pos):
                continue
            qty = safe_int(pos.get("quantity", 0))
            if qty == 0:
                continue
            
            pos_type = detect_position_type(pos)
            avg_price = safe_float(pos.get("average_price", 0))
            ltp = safe_float(pos.get("ltp", avg_price))
            pnl = calculate_pnl(pos_type, avg_price, ltp, abs(qty))
            
            option_positions.append({
                **pos,
                "_position_type": pos_type,
                "_quantity": abs(qty),
                "_closing_action": get_closing_action(pos_type),
                "_pnl": pnl,
                "_avg_price": avg_price,
                "_ltp": ltp
            })
        except Exception:
            continue
    
    if not option_positions:
        show_empty_state("📭", "No open option positions to square off", "", {"label": "💰 Sell Options", "page": "Sell Options", "type": "primary"})
        return
    
    # Summary
    total_pnl = sum(p["_pnl"] for p in option_positions)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Open Positions", len(option_positions))
    col2.metric("Total P&L", format_currency(total_pnl))
    long_count = sum(1 for p in option_positions if p["_position_type"] == "long")
    col3.metric("Long/Short", f"{long_count} / {len(option_positions) - long_count}")
    
    # Position table
    position_rows = []
    for idx, pos in enumerate(option_positions):
        pnl_emoji = "📈" if pos["_pnl"] >= 0 else "📉"
        position_rows.append({
            "#": idx + 1,
            "Instrument": C.api_code_to_display(pos.get("stock_code", "")),
            "Strike": pos.get("strike_price"),
            "Type": C.normalize_option_type(pos.get("right", "")),
            "Position": pos["_position_type"].upper(),
            "Qty": pos["_quantity"],
            "Avg": f"₹{pos['_avg_price']:.2f}",
            "LTP": f"₹{pos['_ltp']:.2f}",
            "P&L": f"{pnl_emoji} ₹{pos['_pnl']:+,.2f}",
            "Action": pos["_closing_action"].upper()
        })
    
    st.dataframe(pd.DataFrame(position_rows), width="stretch", hide_index=True)
    
    st.markdown("---")
    
    # Individual Square Off
    st.markdown('<h2 class="section-header">📍 Individual Square Off</h2>', unsafe_allow_html=True)
    
    position_labels = [
        f"{C.api_code_to_display(p.get('stock_code', ''))} {p.get('strike_price')} {C.normalize_option_type(p.get('right', ''))} | {p['_position_type'].upper()} | Qty: {p['_quantity']}"
        for p in option_positions
    ]
    
    selected_idx = st.selectbox("Select Position", range(len(position_labels)), format_func=lambda i: position_labels[i], key="sq_position")
    selected_position = option_positions[selected_idx]
    
    col1, col2 = st.columns(2)
    with col1:
        sq_order_type = st.radio("Order Type", ["Market", "Limit"], horizontal=True, key="sq_order_type")
    with col2:
        sq_price = 0.0
        if sq_order_type == "Limit":
            sq_price = st.number_input("Limit Price", min_value=0.0, value=float(selected_position["_ltp"]), key="sq_price")
    
    sq_quantity = st.slider("Quantity to Close", min_value=1, max_value=selected_position["_quantity"], value=selected_position["_quantity"], key="sq_qty")
    
    action_label = selected_position['_closing_action'].upper()
    if st.button(f"🔄 {action_label} {sq_quantity} to Close", type="primary", width="stretch"):
        with st.spinner(f"Executing {action_label} order..."):
            try:
                response = client.square_off(
                    stock_code=selected_position.get("stock_code"),
                    exchange=selected_position.get("exchange_code"),
                    expiry=selected_position.get("expiry_date"),
                    strike=safe_int(selected_position.get("strike_price")),
                    option_type=C.normalize_option_type(selected_position.get("right", "")),
                    quantity=sq_quantity,
                    position_type=selected_position["_position_type"],
                    order_type=sq_order_type.lower(),
                    price=sq_price if sq_order_type == "Limit" else 0.0
                )
                
                if response["success"]:
                    st.success(f"✅ {action_label} order placed!")
                    SessionState.log_activity("Square Off", f"{selected_position.get('stock_code')} {selected_position.get('strike_price')}")
                    CacheManager.clear_all()
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(f"❌ {response.get('message')}")
            except Exception as e:
                st.error(f"❌ Error: {e}")
    
    # Bulk Square Off
    st.markdown("---")
    st.markdown('<h2 class="section-header">⚡ Square Off All</h2>', unsafe_allow_html=True)
    
    st.markdown(
        f'<div class="danger-box"><h4>⚠️ DANGER</h4><p>This will close ALL {len(option_positions)} positions at market price.</p></div>',
        unsafe_allow_html=True
    )
    
    confirm_text = st.text_input("Type 'CLOSE ALL' to confirm", key="sq_all_confirm")
    
    if st.button(f"🔴 SQUARE OFF ALL {len(option_positions)} POSITIONS", type="primary", width="stretch", disabled=confirm_text.upper() != "CLOSE ALL"):
        results = client.square_off_all_positions()
        success_count = sum(1 for r in results if r.get("success"))
        
        if success_count > 0:
            st.success(f"✅ Closed {success_count} position(s)")
        
        SessionState.log_activity("Square Off All", f"{success_count} closed")
        CacheManager.clear_all()
        time.sleep(2)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════
# PAGE: ORDERS & TRADES
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session_validity
def page_orders_trades() -> None:
    """Orders and trades management."""
    st.markdown('<h1 class="page-header">📋 Orders & Trades</h1>', unsafe_allow_html=True)
    
    client = safe_get_client()
    if not client:
        return
    
    tab1, tab2, tab3 = st.tabs(["📋 Orders", "📊 Trades", "📝 Activity Log"])
    
    with tab1:
        st.markdown("### Order Book")
        
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        with col1:
            exchange_filter = st.selectbox("Exchange", ["All", "NFO", "BFO"], key="orders_exchange")
        with col2:
            from_date = st.date_input("From", value=date.today() - timedelta(days=7), key="orders_from")
        with col3:
            to_date = st.date_input("To", value=date.today(), key="orders_to")
        with col4:
            st.markdown("<br>", unsafe_allow_html=True)
            st.button("🔄", key="orders_refresh", width="stretch")
        
        try:
            validate_date_range(from_date, to_date)
        except ValueError as e:
            st.error(f"❌ {e}")
            return
        
        with st.spinner("Loading orders..."):
            response = client.get_order_list(
                exchange="" if exchange_filter == "All" else exchange_filter,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d")
            )
        
        if response["success"]:
            parsed = APIResponse(response)
            orders = parsed.items
            
            if not orders:
                show_empty_state("📭", "No orders found", "")
            else:
                st.dataframe(pd.DataFrame(orders), width="stretch", height=400, hide_index=True)
    
    with tab2:
        st.markdown("### Trade Book")
        
        with st.spinner("Loading trades..."):
            response = client.get_trade_list(from_date=from_date.strftime("%Y-%m-%d"), to_date=to_date.strftime("%Y-%m-%d"))
        
        if response["success"]:
            parsed = APIResponse(response)
            trades = parsed.items
            
            if not trades:
                show_empty_state("📭", "No trades found", "")
            else:
                st.dataframe(pd.DataFrame(trades), width="stretch", height=400, hide_index=True)
    
    with tab3:
        st.markdown("### Session Activity Log")
        activity_log = SessionState.get_activity_log()
        
        if not activity_log:
            show_empty_state("📝", "No activity logged", "")
        else:
            st.dataframe(pd.DataFrame(activity_log), width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════
# PAGE: POSITIONS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session_validity
def page_positions() -> None:
    """Detailed positions view."""
    st.markdown('<h1 class="page-header">📍 Positions</h1>', unsafe_allow_html=True)
    
    client = safe_get_client()
    if not client:
        return
    
    if st.button("🔄 Refresh", width="stretch"):
        CacheManager.clear_all()
        st.rerun()
    
    with st.spinner("Loading positions..."):
        response = client.get_positions()
    
    if not response["success"]:
        st.error("❌ Failed to load positions")
        return
    
    parsed = APIResponse(response)
    all_positions = parsed.items
    
    active_positions = []
    total_pnl = 0.0
    
    for pos in all_positions:
        try:
            if not C.is_option_position(pos):
                continue
            qty = safe_int(pos.get("quantity", 0))
            if qty == 0:
                continue
            
            pos_type = detect_position_type(pos)
            avg_price = safe_float(pos.get("average_price", 0))
            ltp = safe_float(pos.get("ltp", avg_price))
            pnl = calculate_pnl(pos_type, avg_price, ltp, abs(qty))
            total_pnl += pnl
            
            active_positions.append({
                "display_name": C.api_code_to_display(pos.get("stock_code", "")),
                "strike": pos.get("strike_price"),
                "option_type": C.normalize_option_type(pos.get("right", "")),
                "position_type": pos_type,
                "quantity": abs(qty),
                "avg_price": avg_price,
                "ltp": ltp,
                "pnl": pnl
            })
        except Exception:
            continue
    
    if not active_positions:
        show_empty_state("📭", "No active positions", "", {"label": "💰 Sell Options", "page": "Sell Options", "type": "primary"})
        return
    
    # Summary
    col1, col2, col3 = st.columns(3)
    col1.metric("Positions", len(active_positions))
    col2.metric("Total P&L", format_currency(total_pnl))
    col3.metric("Long/Short", f"{sum(1 for p in active_positions if p['position_type']=='long')} / {sum(1 for p in active_positions if p['position_type']=='short')}")
    
    # Table
    table_data = []
    for pos in active_positions:
        pnl_emoji = "📈" if pos["pnl"] >= 0 else "📉"
        table_data.append({
            "Instrument": pos["display_name"],
            "Strike": pos["strike"],
            "Type": pos["option_type"],
            "Position": pos["position_type"].upper(),
            "Qty": pos["quantity"],
            "Avg": f"₹{pos['avg_price']:.2f}",
            "LTP": f"₹{pos['ltp']:.2f}",
            "P&L": f"{pnl_emoji} ₹{pos['pnl']:+,.2f}"
        })
    
    st.dataframe(pd.DataFrame(table_data), width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════
# PAGE: STRATEGY BUILDER
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session_validity
def page_strategy_builder() -> None:
    """Multi-leg strategy builder."""
    st.markdown('<h1 class="page-header">🎯 Strategy Builder</h1>', unsafe_allow_html=True)
    
    client = safe_get_client()
    if not client:
        return
    
    st.info("🚧 **Strategy Builder** - Coming Soon!")
    
    st.markdown("""
    ### Planned Features:
    
    **Predefined Strategies:**
    - Bull Call Spread
    - Bear Put Spread  
    - Iron Condor
    - Short Straddle
    - Short Strangle
    - Iron Butterfly
    
    **Analysis:**
    - Payoff diagram
    - Breakeven calculation
    - Max profit/loss
    - Probability of profit
    
    **Execution:**
    - One-click strategy execution
    - Automatic leg management
    """)


# ═══════════════════════════════════════════════════════════════════
# PAGE: ANALYTICS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session_validity
def page_analytics() -> None:
    """Portfolio analytics."""
    st.markdown('<h1 class="page-header">📈 Analytics</h1>', unsafe_allow_html=True)
    
    client = safe_get_client()
    if not client:
        return
    
    tab1, tab2, tab3 = st.tabs(["📊 Portfolio Greeks", "🛡️ Risk Metrics", "📈 Performance"])
    
    with tab1:
        st.markdown("### Portfolio Greeks Summary")
        
        with st.spinner("Loading positions for Greeks calculation..."):
            response = client.get_positions()
        
        if not response["success"]:
            st.error("❌ Could not load positions")
            return
        
        parsed = APIResponse(response)
        positions = [p for p in parsed.items if C.is_option_position(p) and safe_int(p.get("quantity", 0)) != 0]
        
        if not positions:
            show_empty_state("📊", "No positions for Greeks calculation", "")
            return
        
        # Convert to DataFrame for analytics
        positions_df = pd.DataFrame(positions)
        positions_df['quantity'] = positions_df['quantity'].apply(safe_int)
        
        for col in ['delta', 'gamma', 'theta', 'vega', 'rho']:
            if col not in positions_df.columns:
                positions_df[col] = 0.0
        
        portfolio_greeks = calculate_portfolio_greeks(positions_df)
        
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Δ Delta", f"{portfolio_greeks.get('delta', 0):+.2f}")
        col2.metric("Γ Gamma", f"{portfolio_greeks.get('gamma', 0):+.4f}")
        col3.metric("Θ Theta", f"{portfolio_greeks.get('theta', 0):+.2f}")
        col4.metric("ν Vega", f"{portfolio_greeks.get('vega', 0):+.2f}")
        col5.metric("ρ Rho", f"{portfolio_greeks.get('rho', 0):+.4f}")
    
    with tab2:
        st.markdown("### Risk Metrics")
        st.info("🚧 Advanced risk metrics coming soon!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("VaR (95%)", "Coming Soon")
        col2.metric("Max Drawdown", "Coming Soon")
        col3.metric("Sharpe Ratio", "Coming Soon")
    
    with tab3:
        st.markdown("### Performance Analytics")
        st.info("🚧 Performance tracking coming soon!")


# ═══════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ═══════════════════════════════════════════════════════════════════

PAGE_FUNCTIONS: Dict[str, Callable] = {
    "Dashboard": page_dashboard,
    "Option Chain": page_option_chain,
    "Sell Options": page_sell_options,
    "Square Off": page_square_off,
    "Orders & Trades": page_orders_trades,
    "Positions": page_positions,
    "Strategy Builder": page_strategy_builder,
    "Analytics": page_analytics
}


def main() -> None:
    """Main application entry point."""
    try:
        SessionState.initialize()
        render_sidebar()
        
        st.markdown('<h1 class="main-header">📈 Breeze Options Trader</h1>', unsafe_allow_html=True)
        st.markdown("---")
        
        current_page = SessionState.get_current_page()
        
        if current_page in AUTH_REQUIRED_PAGES and not SessionState.is_authenticated():
            st.warning("🔒 Authentication required")
            st.info("👈 Please login using the sidebar")
            return
        
        if SessionState.is_authenticated() and SessionState.is_session_expired():
            st.error("🔴 Session expired. Please reconnect.")
            if st.button("🔄 Reconnect", type="primary", width="stretch"):
                SessionState.set_authentication(False, None)
                SessionState.navigate_to("Dashboard")
                st.rerun()
            return
        
        page_function = PAGE_FUNCTIONS.get(current_page, page_dashboard)
        page_function()
        
    except Exception as e:
        log.critical(f"Critical error: {e}", exc_info=True)
        st.error("❌ A critical error occurred. Please refresh.")
        if st.session_state.get("debug_mode"):
            st.exception(e)


if __name__ == "__main__":
    main()
