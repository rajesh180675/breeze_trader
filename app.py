"""
Breeze Options Trader - Main Application
=========================================
Complete production-ready options trading platform.

Features:
- Dashboard with portfolio analytics
- Advanced option chain with Greeks
- Multi-leg strategy builder
- Risk management tools
- Order & trade tracking
- Position management
- Activity journal
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from functools import wraps
import time
import logging
from typing import Optional, Dict, List, Any

# Local imports
import app_config as C
from helpers import (
    APIResponse, safe_int, safe_float, safe_str,
    detect_position_type, get_closing_action, calculate_pnl,
    calculate_unrealized_pnl, calculate_margin_used,
    process_option_chain, create_pivot_table,
    calculate_pcr, calculate_max_pain, estimate_atm_strike,
    add_greeks_to_chain,
    get_market_status, format_currency, format_expiry,
    format_percentage, calculate_days_to_expiry
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
    calculate_greeks, calculate_portfolio_greeks,
    calculate_var, calculate_max_drawdown,
    calculate_sharpe_ratio, calculate_win_rate,
    calculate_strategy_payoff
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
        'Get Help': None,
        'Report a bug': None,
        'About': "# Breeze Options Trader v5.0\n\nProfessional options trading platform."
    }
)

# ═══════════════════════════════════════════════════════════════════
# CUSTOM CSS
# ═══════════════════════════════════════════════════════════════════

st.markdown("""
<style>
/* Main header */
.main-header {
    font-size: 2.5rem;
    font-weight: 700;
    background: linear-gradient(135deg, #1f77b4 0%, #2ecc71 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-align: center;
    padding: 1rem 0;
    margin-bottom: 0.5rem;
}

/* Page headers */
.page-header {
    font-size: 2rem;
    font-weight: 700;
    color: #1f77b4;
    border-bottom: 4px solid #1f77b4;
    padding-bottom: 0.5rem;
    margin-bottom: 1.5rem;
}

/* Section headers */
.section-header {
    font-size: 1.5rem;
    font-weight: 600;
    color: #2c3e50;
    margin-top: 1.5rem;
    margin-bottom: 1rem;
}

/* Status badges */
.status-connected {
    background: #d4edda;
    color: #155724;
    padding: 4px 12px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 0.9rem;
}

.status-disconnected {
    background: #f8d7da;
    color: #721c24;
    padding: 4px 12px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 0.9rem;
}

/* Market status */
.market-open {
    color: #28a745;
    font-weight: 700;
}

.market-closed {
    color: #dc3545;
    font-weight: 700;
}

.market-pre {
    color: #ffc107;
    font-weight: 700;
}

/* P&L colors */
.profit {
    color: #28a745 !important;
    font-weight: 700;
}

.loss {
    color: #dc3545 !important;
    font-weight: 700;
}

.neutral {
    color: #6c757d !important;
}

/* Info boxes */
.info-box {
    background: #e7f3ff;
    border-left: 5px solid #2196F3;
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 0 8px 8px 0;
}

.success-box {
    background: #d4edda;
    border-left: 5px solid #28a745;
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 0 8px 8px 0;
}

.warning-box {
    background: #fff3cd;
    border-left: 5px solid #ffc107;
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 0 8px 8px 0;
}

.danger-box {
    background: #f8d7da;
    border-left: 5px solid #dc3545;
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 0 8px 8px 0;
}

/* Buttons */
.stButton > button {
    width: 100%;
    border-radius: 6px;
    font-weight: 600;
}

/* Metrics */
.metric-card {
    background: #f8f9fa;
    padding: 1rem;
    border-radius: 8px;
    border: 1px solid #dee2e6;
}

/* Tables */
.dataframe {
    font-size: 0.9rem;
}

/* ATM strike highlight */
.atm-strike {
    background-color: #fff3cd !important;
    font-weight: 700 !important;
}

/* Greeks display */
.greeks-positive {
    color: #28a745;
}

.greeks-negative {
    color: #dc3545;
}

/* Compact spacing */
.compact-metrics .stMetric {
    background: white;
    padding: 0.5rem;
    border-radius: 6px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

/* Hide streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════
# GLOBAL CONSTANTS
# ═══════════════════════════════════════════════════════════════════

PAGES = [
    "Dashboard",
    "Option Chain",
    "Sell Options",
    "Square Off",
    "Orders & Trades",
    "Positions",
    "Strategy Builder",
    "Analytics"
]

PAGE_ICONS = {
    "Dashboard": "🏠",
    "Option Chain": "📊",
    "Sell Options": "💰",
    "Square Off": "🔄",
    "Orders & Trades": "📋",
    "Positions": "📍",
    "Strategy Builder": "🎯",
    "Analytics": "📈"
}

AUTH_REQUIRED_PAGES = set(PAGES[1:])  # All except Dashboard

# ═══════════════════════════════════════════════════════════════════
# UTILITY DECORATORS
# ═══════════════════════════════════════════════════════════════════

def error_handler(func):
    """Decorator to handle errors gracefully."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.error(f"{func.__name__} error: {e}", exc_info=True)
            st.error(f"❌ An error occurred: {str(e)}")
            if SessionState.DEFAULTS.get("debug_mode", False):
                st.exception(e)
    return wrapper


def require_auth(func):
    """Decorator to require authentication."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not SessionState.is_authenticated():
            st.warning("🔒 Please login to access this page")
            st.info("👈 Use the sidebar to login")
            return
        return func(*args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

def render_sidebar():
    """Render sidebar with navigation and auth."""
    with st.sidebar:
        # Branding
        st.markdown("## 📈 Breeze Trader")
        st.markdown("**Professional Options Platform**")
        st.markdown("---")
        
        # Navigation
        render_navigation()
        
        st.markdown("---")
        
        # Authentication
        if SessionState.is_authenticated():
            render_authenticated_sidebar()
        else:
            render_login_sidebar()
        
        st.markdown("---")
        
        # Settings
        render_settings_sidebar()


def render_navigation():
    """Render navigation menu."""
    available_pages = PAGES if SessionState.is_authenticated() else ["Dashboard"]
    current_page = SessionState.get_current_page()
    
    # Ensure current page is valid
    if current_page not in available_pages:
        current_page = "Dashboard"
        SessionState.navigate_to("Dashboard")
    
    selected_page = st.radio(
        "Navigation",
        available_pages,
        index=available_pages.index(current_page),
        format_func=lambda p: f"{PAGE_ICONS.get(p, '📄')} {p}",
        label_visibility="collapsed"
    )
    
    # Navigate if changed
    if selected_page != current_page:
        SessionState.navigate_to(selected_page)
        st.rerun()


def render_login_sidebar():
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
        
        with st.form("quick_login"):
            session_token = st.text_input(
                "Session Token",
                type="password",
                placeholder="Paste from ICICI Direct",
                help="Get fresh token daily from ICICI Direct"
            )
            
            submitted = st.form_submit_button("🔑 Connect", use_container_width=True)
            
            if submitted:
                if not session_token:
                    st.warning("Please enter session token")
                else:
                    api_key, api_secret, _ = Credentials.get_all_credentials()
                    perform_login(api_key, api_secret, session_token)
        
        with st.expander("Use different credentials"):
            render_full_login_form()
    
    else:
        st.markdown("### 🔐 Login")
        st.markdown(
            '<div class="info-box">'
            '💡 Store API Key & Secret in '
            '<a href="https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management" target="_blank">Streamlit Secrets</a> '
            'for quick daily login.'
            '</div>',
            unsafe_allow_html=True
        )
        render_full_login_form()


def render_full_login_form():
    """Render full login form with all credentials."""
    with st.form("full_login"):
        api_key, api_secret, _ = Credentials.get_all_credentials()
        
        new_key = st.text_input(
            "API Key",
            value=api_key,
            type="password",
            help="Your Breeze API key"
        )
        
        new_secret = st.text_input(
            "API Secret",
            value=api_secret,
            type="password",
            help="Your Breeze API secret"
        )
        
        session_token = st.text_input(
            "Session Token",
            type="password",
            help="Daily session token from ICICI Direct"
        )
        
        st.caption("⚠️ Token changes daily - get fresh from ICICI Direct")
        
        submitted = st.form_submit_button("🔑 Connect", use_container_width=True)
        
        if submitted:
            if not all([new_key, new_secret, session_token]):
                st.warning("Please fill all fields")
            else:
                perform_login(new_key, new_secret, session_token)


def perform_login(api_key: str, api_secret: str, session_token: str):
    """Perform login with credentials."""
    with st.spinner("Connecting to Breeze API..."):
        # Create API client
        client = BreezeAPIClient(api_key, api_secret)
        
        # Connect
        response = client.connect(session_token)
        
        if response["success"]:
            # Save credentials
            Credentials.save_runtime_credentials(api_key, api_secret, session_token)
            
            # Set authentication
            SessionState.set_authentication(True, client)
            
            # Log activity
            SessionState.log_activity("Login", "Connected to Breeze API")
            
            # Success notification
            Notifications.success("Connected successfully!")
            
            time.sleep(0.5)
            st.rerun()
        else:
            st.error(f"❌ Connection failed: {response['message']}")


def render_authenticated_sidebar():
    """Render sidebar for authenticated user."""
    # Connection status
    st.markdown(
        '<span class="status-connected">✅ Connected</span>',
        unsafe_allow_html=True
    )
    
    # User info
    client = SessionState.get_client()
    if client:
        try:
            response = client.get_customer_details()
            if response["success"]:
                parsed = APIResponse(response)
                user_name = parsed.get("name", "User")
                user_id = parsed.get("user_id", "")
                
                st.session_state.user_name = user_name
                st.session_state.user_id = user_id
                
                st.markdown(f"**👤 {user_name}**")
                if user_id:
                    st.caption(f"ID: {user_id}")
        except Exception as e:
            log.error(f"Failed to get customer details: {e}")
            st.markdown(f"**👤 {st.session_state.get('user_name', 'User')}**")
    
    # Session duration
    duration = SessionState.get_login_duration()
    if duration:
        st.caption(f"⏱️ Session: {duration}")
    
    # Session warnings
    if SessionState.is_session_expired():
        st.error("🔴 Session expired - please reconnect")
    elif SessionState.is_session_stale():
        st.warning("⚠️ Session may be stale")
    
    # Market status
    market_status = get_market_status()
    if "Open" in market_status:
        st.markdown(f'<p class="market-open">{market_status}</p>', unsafe_allow_html=True)
    elif "Pre" in market_status:
        st.markdown(f'<p class="market-pre">{market_status}</p>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p class="market-closed">{market_status}</p>', unsafe_allow_html=True)
    
    # Quick margin info
    if client:
        try:
            response = client.get_funds()
            if response["success"]:
                parsed = APIResponse(response)
                available = safe_float(parsed.get("available_margin", 0))
                st.metric(
                    "Available Margin",
                    format_currency(available),
                    help="Available margin for trading"
                )
        except Exception:
            pass
    
    # Disconnect button
    if st.button("🔓 Disconnect", use_container_width=True):
        SessionState.set_authentication(False, None)
        Credentials.clear_runtime_credentials()
        CacheManager.clear_all()
        SessionState.navigate_to("Dashboard")
        SessionState.log_activity("Logout", "Disconnected from Breeze API")
        st.rerun()


def render_settings_sidebar():
    """Render settings section."""
    st.markdown("### ⚙️ Settings")
    
    # Instrument selector
    st.selectbox(
        "Default Instrument",
        list(C.INSTRUMENTS.keys()),
        key="selected_instrument",
        help="Default instrument for trading"
    )
    
    # Debug mode
    st.session_state.debug_mode = st.checkbox(
        "🔧 Debug Mode",
        value=st.session_state.get("debug_mode", False),
        help="Show detailed error messages and API responses"
    )
    
    # Auto-refresh toggle
    st.session_state.auto_refresh = st.checkbox(
        "🔄 Auto Refresh",
        value=st.session_state.get("auto_refresh", False),
        help="Automatically refresh data every 30 seconds"
    )
    
    # Version
    st.caption("v5.0.0 Production")


# ═══════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@error_handler
def page_dashboard():
    """Dashboard with portfolio overview and quick stats."""
    st.markdown('<h1 class="page-header">🏠 Dashboard</h1>', unsafe_allow_html=True)
    
    if not SessionState.is_authenticated():
        render_welcome_dashboard()
    else:
        render_authenticated_dashboard()


def render_welcome_dashboard():
    """Welcome screen for non-authenticated users."""
    # Feature highlights
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("### 📊 Market Data")
        st.markdown("""
        - Live option chains
        - Real-time Greeks
        - OI analysis
        - PCR & Max Pain
        """)
    
    with col2:
        st.markdown("### 💰 Trading")
        st.markdown("""
        - Sell options
        - Multi-leg strategies
        - Quick square-off
        - Order management
        """)
    
    with col3:
        st.markdown("### 🛡️ Risk Management")
        st.markdown("""
        - Portfolio Greeks
        - P&L tracking
        - Margin monitoring
        - Risk analytics
        """)
    
    st.markdown("---")
    
    # Instrument table
    st.subheader("📈 Supported Instruments")
    
    instruments_data = []
    for name, config in C.INSTRUMENTS.items():
        instruments_data.append({
            "Instrument": name,
            "Description": config.description,
            "Exchange": config.exchange,
            "Lot Size": config.lot_size,
            "Tick Size": config.tick_size,
            "Strike Gap": config.strike_gap,
            "Weekly Expiry": config.expiry_day
        })
    
    st.dataframe(
        pd.DataFrame(instruments_data),
        use_container_width=True,
        hide_index=True
    )
    
    # Setup instructions
    if not Credentials.has_stored_credentials():
        st.markdown("---")
        st.markdown(
            '<div class="info-box">'
            '<h4>🚀 Quick Setup</h4>'
            '<ol>'
            '<li>Add API credentials to Streamlit Secrets</li>'
            '<li>Get daily session token from ICICI Direct</li>'
            '<li>Login using the sidebar</li>'
            '<li>Start trading!</li>'
            '</ol>'
            '<p><b>Secrets Configuration:</b></p>'
            '<pre style="background:#f8f9fa;padding:10px;border-radius:5px;">'
            'BREEZE_API_KEY = "your_key_here"\n'
            'BREEZE_API_SECRET = "your_secret_here"'
            '</pre>'
            '</div>',
            unsafe_allow_html=True
        )
    
    st.info("👈 **Login** to access all features")


def render_authenticated_dashboard():
    """Dashboard for authenticated users."""
    client = SessionState.get_client()
    
    # Portfolio summary
    st.markdown('<h2 class="section-header">📊 Portfolio Summary</h2>', unsafe_allow_html=True)
    
    # Fetch data
    funds_response = client.get_funds()
    positions_response = client.get_positions()
    
    # Funds metrics
    col1, col2, col3, col4 = st.columns(4)
    
    if funds_response["success"]:
        parsed_funds = APIResponse(funds_response)
        available = safe_float(parsed_funds.get("available_margin", 0))
        used = safe_float(parsed_funds.get("utilized_margin", 0))
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
    
    st.markdown("---")
    
    # Positions summary
    st.markdown('<h2 class="section-header">📍 Open Positions</h2>', unsafe_allow_html=True)
    
    if positions_response["success"]:
        parsed_positions = APIResponse(positions_response)
        all_positions = parsed_positions.items
        
        # Filter active positions
        active_positions = [
            p for p in all_positions
            if safe_int(p.get("quantity", 0)) != 0
        ]
        
        if not active_positions:
            st.info("📭 No open positions")
        else:
            # Calculate aggregates
            total_pnl = 0.0
            position_rows = []
            
            for pos in active_positions:
                qty = safe_int(pos.get("quantity", 0))
                pos_type = detect_position_type(pos)
                avg_price = safe_float(pos.get("average_price", 0))
                ltp = safe_float(pos.get("ltp", avg_price))
                
                pnl = calculate_pnl(pos_type, avg_price, ltp, qty)
                total_pnl += pnl
                
                position_rows.append({
                    "Instrument": C.api_code_to_display(pos.get("stock_code", "")),
                    "Strike": pos.get("strike_price"),
                    "Type": C.normalize_option_type(pos.get("right", "")),
                    "Position": pos_type.upper(),
                    "Qty": abs(qty),
                    "Avg": f"₹{avg_price:.2f}",
                    "LTP": f"₹{ltp:.2f}",
                    "P&L": pnl
                })
            
            # Show positions table
            df = pd.DataFrame(position_rows)
            
            # Format P&L column
            df["P&L Formatted"] = df["P&L"].apply(
                lambda x: f"₹{x:+,.2f}"
            )
            
            display_df = df.drop(columns=["P&L"]).rename(
                columns={"P&L Formatted": "P&L"}
            )
            
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True
                )
            
            with col2:
                # Total P&L
                pnl_color = "profit" if total_pnl >= 0 else "loss"
                st.markdown(
                    f'<div class="metric-card">'
                    f'<h4>Total P&L</h4>'
                    f'<h2 class="{pnl_color}">{format_currency(total_pnl)}</h2>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
                # Position count
                st.metric("Positions", len(active_positions))
                
                # Position breakdown
                long_count = sum(1 for p in position_rows if p["Position"] == "LONG")
                short_count = len(position_rows) - long_count
                
                st.write(f"🟢 Long: {long_count}")
                st.write(f"🔴 Short: {short_count}")
    
    st.markdown("---")
    
    # Quick actions
    st.markdown('<h2 class="section-header">⚡ Quick Actions</h2>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("📊 View Option Chain", use_container_width=True):
            SessionState.navigate_to("Option Chain")
            st.rerun()
    
    with col2:
        if st.button("💰 Sell Options", use_container_width=True):
            SessionState.navigate_to("Sell Options")
            st.rerun()
    
    with col3:
        if st.button("🔄 Square Off", use_container_width=True):
            SessionState.navigate_to("Square Off")
            st.rerun()
    
    with col4:
        if st.button("📋 View Orders", use_container_width=True):
            SessionState.navigate_to("Orders & Trades")
            st.rerun()
    
    # Activity log
    activity_log = SessionState.get_activity_log()
    if activity_log:
        st.markdown("---")
        with st.expander("📝 Recent Activity", expanded=False):
            recent_activities = activity_log[:20]
            st.dataframe(
                pd.DataFrame(recent_activities),
                use_container_width=True,
                hide_index=True
            )


# ═══════════════════════════════════════════════════════════════════
# PAGE: OPTION CHAIN
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_option_chain():
    """Advanced option chain with Greeks and analytics."""
    st.markdown('<h1 class="page-header">📊 Option Chain</h1>', unsafe_allow_html=True)
    
    client = SessionState.get_client()
    
    # Controls row 1
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
        expiry = st.selectbox(
            "Expiry",
            expiries,
            format_func=format_expiry,
            key="oc_expiry"
        )
    
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh_clicked = st.button("🔄 Refresh", use_container_width=True, key="oc_refresh")
    
    # Controls row 2
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        view_mode = st.radio(
            "View Mode",
            ["Traditional", "Flat", "Calls Only", "Puts Only"],
            horizontal=True,
            key="oc_view"
        )
    
    with col2:
        strikes_count = st.slider(
            "Strikes Around ATM",
            5, 50, 15,
            key="oc_strikes"
        )
    
    with col3:
        show_greeks = st.checkbox(
            "Show Greeks",
            value=True,
            key="oc_greeks"
        )
    
    # Fetch option chain
    cache_key = f"{instrument_config.api_code}_{expiry}"
    
    if refresh_clicked:
        CacheManager.invalidate(cache_key, "option_chain")
    
    cached_df = CacheManager.get_option_chain(instrument_config.api_code, expiry)
    
    if cached_df is not None:
        df = cached_df
        st.caption("📦 Using cached data (30s TTL)")
    else:
        with st.spinner(f"Loading {instrument} option chain..."):
            response = client.get_option_chain(
                instrument_config.api_code,
                instrument_config.exchange,
                expiry
            )
        
        if not response["success"]:
            st.error(f"❌ Failed to fetch option chain: {response['message']}")
            if st.session_state.get("debug_mode"):
                st.json(response)
            return
        
        df = process_option_chain(response["data"])
        
        if df.empty:
            st.warning("No option chain data available")
            if st.session_state.get("debug_mode"):
                st.write("Response data:", response.get("data", {}).keys())
            return
        
        # Cache the data
        CacheManager.cache_option_chain(instrument_config.api_code, expiry, df)
        SessionState.log_activity("Option Chain", f"{instrument} {format_expiry(expiry)}")
    
    # Calculate metrics
    st.markdown(f"### {instrument} ({instrument_config.api_code}) — {format_expiry(expiry)}")
    
    # Days to expiry
    days_left = calculate_days_to_expiry(expiry)
    
    # Metrics row
    pcr = calculate_pcr(df)
    max_pain = calculate_max_pain(df)
    atm_strike = estimate_atm_strike(df)
    
    call_oi = df[df["right"] == "Call"]["open_interest"].sum() if "right" in df.columns else 0
    put_oi = df[df["right"] == "Put"]["open_interest"].sum() if "right" in df.columns else 0
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        pcr_sentiment = "Bullish" if pcr > 1 else "Bearish"
        st.metric("PCR", f"{pcr:.2f}", pcr_sentiment)
    
    with col2:
        st.metric("Max Pain", f"{max_pain:,.0f}")
    
    with col3:
        st.metric("ATM ≈", f"{atm_strike:,.0f}")
    
    with col4:
        st.metric("Days to Expiry", days_left)
    
    with col5:
        st.metric("Call OI", f"{call_oi:,.0f}")
    
    st.markdown("---")
    
    # Filter strikes around ATM
    if "strike_price" in df.columns and atm_strike > 0:
        strikes = sorted(df["strike_price"].unique())
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_strike))
        
        start_idx = max(0, atm_idx - strikes_count)
        end_idx = min(len(strikes), atm_idx + strikes_count + 1)
        
        filtered_strikes = strikes[start_idx:end_idx]
        display_df = df[df["strike_price"].isin(filtered_strikes)].copy()
    else:
        display_df = df.copy()
    
    # Add Greeks if requested
    if show_greeks and not display_df.empty:
        display_df = add_greeks_to_chain(display_df, atm_strike, expiry)
    
    # Display based on view mode
    if view_mode == "Traditional":
        pivot_df = create_pivot_table(display_df)
        
        if pivot_df.empty:
            st.warning("Cannot create pivot view")
        else:
            # Highlight ATM strike
            def highlight_atm_row(row):
                if abs(row.get("Strike", 0) - atm_strike) < instrument_config.strike_gap / 2:
                    return ['background-color: #fff3cd; font-weight: bold'] * len(row)
                return [''] * len(row)
            
            styled = pivot_df.style.apply(highlight_atm_row, axis=1)
            
            # Format numeric columns
            numeric_cols = [c for c in pivot_df.columns if c != "Strike"]
            format_dict = {col: "{:,.0f}" for col in numeric_cols}
            styled = styled.format(format_dict)
            
            st.dataframe(
                styled,
                use_container_width=True,
                height=600,
                hide_index=True
            )
    
    elif view_mode == "Calls Only":
        calls_df = display_df[display_df["right"] == "Call"] if "right" in display_df.columns else display_df
        render_flat_option_chain(calls_df, show_greeks)
    
    elif view_mode == "Puts Only":
        puts_df = display_df[display_df["right"] == "Put"] if "right" in display_df.columns else display_df
        render_flat_option_chain(puts_df, show_greeks)
    
    else:  # Flat view
        render_flat_option_chain(display_df, show_greeks)
    
    # OI Distribution Chart
    if "right" in display_df.columns and "open_interest" in display_df.columns:
        st.markdown("---")
        st.markdown('<h3 class="section-header">Open Interest Distribution</h3>', unsafe_allow_html=True)
        
        calls_oi = display_df[display_df["right"] == "Call"][["strike_price", "open_interest"]].rename(
            columns={"open_interest": "Call OI"}
        )
        puts_oi = display_df[display_df["right"] == "Put"][["strike_price", "open_interest"]].rename(
            columns={"open_interest": "Put OI"}
        )
        
        oi_chart_df = pd.merge(calls_oi, puts_oi, on="strike_price", how="outer").fillna(0)
        oi_chart_df = oi_chart_df.sort_values("strike_price").set_index("strike_price")
        
        st.bar_chart(oi_chart_df)
    
    # Debug info
    if st.session_state.get("debug_mode"):
        with st.expander("🔧 Debug Information"):
            st.write(f"Total rows: {len(df)}")
            if "right" in df.columns:
                st.write(f"Calls: {len(df[df['right']=='Call'])}")
                st.write(f"Puts: {len(df[df['right']=='Put'])}")
            st.write("First 10 rows:")
            st.dataframe(df.head(10), use_container_width=True)


def render_flat_option_chain(df: pd.DataFrame, show_greeks: bool):
    """Render flat option chain table."""
    if df.empty:
        st.info("No data to display")
        return
    
    # Select columns to display
    base_cols = ["strike_price", "right", "ltp", "open_interest", "volume", 
                 "best_bid_price", "best_offer_price"]
    
    if show_greeks:
        greek_cols = ["delta", "gamma", "theta", "vega"]
        display_cols = [c for c in base_cols + greek_cols if c in df.columns]
    else:
        display_cols = [c for c in base_cols if c in df.columns]
    
    # Column name mapping
    col_names = {
        "strike_price": "Strike",
        "right": "Type",
        "ltp": "LTP",
        "open_interest": "OI",
        "volume": "Volume",
        "best_bid_price": "Bid",
        "best_offer_price": "Ask",
        "delta": "Δ Delta",
        "gamma": "Γ Gamma",
        "theta": "Θ Theta",
        "vega": "ν Vega"
    }
    
    display_df = df[display_cols].rename(columns=col_names)
    display_df = display_df.sort_values("Strike")
    
    st.dataframe(
        display_df,
        use_container_width=True,
        height=600,
        hide_index=True
    )


# ═══════════════════════════════════════════════════════════════════
# Continue in next message...
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# PAGE: SELL OPTIONS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_sell_options():
    """Sell options page with validation and margin checks."""
    st.markdown('<h1 class="page-header">💰 Sell Options</h1>', unsafe_allow_html=True)
    
    client = SessionState.get_client()
    
    col1, col2 = st.columns(2)
    
    # Left column - Order parameters
    with col1:
        st.markdown("### Order Details")
        
        instrument = st.selectbox(
            "Instrument",
            list(C.INSTRUMENTS.keys()),
            key="sell_instrument"
        )
        
        instrument_config = C.get_instrument(instrument)
        
        expiry = st.selectbox(
            "Expiry",
            C.get_next_expiries(instrument, 5),
            format_func=format_expiry,
            key="sell_expiry"
        )
        
        option_type = st.radio(
            "Option Type",
            ["CE (Call)", "PE (Put)"],
            horizontal=True,
            key="sell_option_type"
        )
        
        option_code = "CE" if "CE" in option_type else "PE"
        
        strike = st.number_input(
            "Strike Price",
            min_value=instrument_config.min_strike,
            max_value=instrument_config.max_strike,
            value=instrument_config.min_strike + 1000,
            step=instrument_config.strike_gap,
            key="sell_strike"
        )
        
        # Validate strike
        if not C.validate_strike(instrument, strike):
            st.warning(f"⚠️ Invalid strike. Must be multiple of {instrument_config.strike_gap}")
        
        lots = st.number_input(
            "Number of Lots",
            min_value=C.MIN_LOTS_PER_ORDER,
            max_value=C.MAX_LOTS_PER_ORDER,
            value=1,
            step=1,
            key="sell_lots"
        )
        
        quantity = lots * instrument_config.lot_size
        st.info(f"**Total Quantity:** {quantity} ({lots} lots × {instrument_config.lot_size})")
        
        order_type = st.radio(
            "Order Type",
            ["Market", "Limit"],
            horizontal=True,
            key="sell_order_type"
        )
        
        limit_price = 0.0
        if order_type == "Limit":
            limit_price = st.number_input(
                "Limit Price",
                min_value=0.0,
                value=0.0,
                step=instrument_config.tick_size,
                key="sell_price"
            )
    
    # Right column - Quote and margin
    with col2:
        st.markdown("### Market Information")
        
        # Quote button
        if st.button("📊 Get Live Quote", use_container_width=True, disabled=(strike <= 0)):
            with st.spinner("Fetching quote..."):
                quote_response = client.get_quotes(
                    instrument_config.api_code,
                    instrument_config.exchange,
                    expiry,
                    strike,
                    option_code
                )
                
                if quote_response["success"]:
                    quote_data = APIResponse(quote_response)
                    items = quote_data.items
                    
                    if items:
                        quote = items[0]
                        ltp = safe_float(quote.get("ltp", 0))
                        bid = safe_float(quote.get("best_bid_price", 0))
                        ask = safe_float(quote.get("best_offer_price", 0))
                        volume = safe_int(quote.get("volume", 0))
                        oi = safe_int(quote.get("open_interest", 0))
                        
                        st.success("✅ Live Quote:")
                        
                        # Display metrics
                        q_col1, q_col2 = st.columns(2)
                        with q_col1:
                            st.metric("LTP", f"₹{ltp:.2f}")
                            st.metric("Bid", f"₹{bid:.2f}")
                        with q_col2:
                            st.metric("Ask", f"₹{ask:.2f}")
                            st.metric("Spread", f"₹{abs(ask - bid):.2f}")
                        
                        st.write(f"**Volume:** {volume:,}")
                        st.write(f"**Open Interest:** {oi:,}")
                        
                        # Estimate premium received
                        premium = ltp * quantity
                        st.info(f"**Estimated Premium:** {format_currency(premium)}")
                    else:
                        st.warning("No quote data available")
                else:
                    st.error(f"❌ {quote_response['message']}")
        
        st.markdown("---")
        
        # Margin calculator
        if st.button("💰 Calculate Margin", use_container_width=True, disabled=(strike <= 0)):
            with st.spinner("Calculating margin..."):
                margin_response = client.get_margin(
                    instrument_config.api_code,
                    instrument_config.exchange,
                    expiry,
                    strike,
                    option_code,
                    "sell",
                    quantity
                )
                
                if margin_response["success"]:
                    margin_data = APIResponse(margin_response)
                    required_margin = safe_float(margin_data.get("required_margin", 0))
                    
                    st.success(f"**Required Margin:** {format_currency(required_margin)}")
                    
                    # Check available margin
                    funds_response = client.get_funds()
                    if funds_response["success"]:
                        funds_data = APIResponse(funds_response)
                        available = safe_float(funds_data.get("available_margin", 0))
                        
                        if required_margin > available:
                            st.error(f"⚠️ Insufficient margin! Need {format_currency(required_margin - available)} more")
                        else:
                            remaining = available - required_margin
                            st.info(f"✅ Sufficient margin. Remaining: {format_currency(remaining)}")
                else:
                    st.warning("Margin calculation not available")
    
    # Risk warning
    st.markdown("---")
    st.markdown(
        '<div class="danger-box">'
        '<h4>⚠️ RISK WARNING</h4>'
        '<p><b>Option selling has UNLIMITED RISK.</b></p>'
        '<ul>'
        '<li>You can lose more than your initial margin</li>'
        '<li>Losses can escalate quickly in volatile markets</li>'
        '<li>Always use stop losses and monitor positions</li>'
        '<li>Understand the risks before trading</li>'
        '</ul>'
        '</div>',
        unsafe_allow_html=True
    )
    
    # Confirmation and submit
    risk_acknowledged = st.checkbox(
        "✅ I understand and accept the risks of option selling",
        key="sell_risk_ack"
    )
    
    can_submit = (
        risk_acknowledged and
        strike > 0 and
        C.validate_strike(instrument, strike) and
        (order_type == "Market" or limit_price > 0)
    )
    
    if st.button(
        f"🔴 SELL {option_code}",
        type="primary",
        use_container_width=True,
        disabled=not can_submit
    ):
        # Validate using Pydantic
        try:
            order_request = OrderRequest(
                instrument=instrument,
                strike=strike,
                option_type=option_code,
                action="sell",
                quantity=quantity,
                order_type=order_type.lower(),
                price=limit_price
            )
        except Exception as e:
            st.error(f"❌ Validation error: {e}")
            return
        
        # Place order
        with st.spinner("Placing order..."):
            if option_code == "CE":
                response = client.sell_call(
                    instrument_config.api_code,
                    instrument_config.exchange,
                    expiry,
                    strike,
                    quantity,
                    order_type.lower(),
                    limit_price
                )
            else:
                response = client.sell_put(
                    instrument_config.api_code,
                    instrument_config.exchange,
                    expiry,
                    strike,
                    quantity,
                    order_type.lower(),
                    limit_price
                )
            
            if response["success"]:
                order_data = APIResponse(response)
                order_id = order_data.get("order_id", "Unknown")
                
                st.markdown(
                    f'<div class="success-box">'
                    f'<h4>✅ Order Placed Successfully!</h4>'
                    f'<p><b>Order ID:</b> {order_id}</p>'
                    f'<p><b>Action:</b> SELL {option_code}</p>'
                    f'<p><b>Instrument:</b> {instrument} {strike}</p>'
                    f'<p><b>Quantity:</b> {quantity}</p>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
                st.balloons()
                
                SessionState.log_activity(
                    "Order Placed",
                    f"SELL {instrument} {strike} {option_code} x{quantity}"
                )
                
                # Clear form
                time.sleep(2)
                st.rerun()
            else:
                st.error(f"❌ Order failed: {response['message']}")


# ═══════════════════════════════════════════════════════════════════
# PAGE: SQUARE OFF
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_square_off():
    """Square off positions page."""
    st.markdown('<h1 class="page-header">🔄 Square Off Positions</h1>', unsafe_allow_html=True)
    
    client = SessionState.get_client()
    
    # Fetch positions
    with st.spinner("Loading positions..."):
        response = client.get_positions()
    
    if not response["success"]:
        st.error(f"❌ Failed to load positions: {response['message']}")
        return
    
    parsed = APIResponse(response)
    all_positions = parsed.items
    
    # Filter option positions with quantity
    option_positions = []
    for pos in all_positions:
        if str(pos.get("product_type", "")).lower() != "options":
            continue
        
        qty = safe_int(pos.get("quantity", 0))
        if qty == 0:
            continue
        
        # Enrich position data
        pos_type = detect_position_type(pos)
        avg_price = safe_float(pos.get("average_price", 0))
        ltp = safe_float(pos.get("ltp", avg_price))
        pnl = calculate_pnl(pos_type, avg_price, ltp, qty)
        
        enriched_pos = {
            **pos,
            "_position_type": pos_type,
            "_quantity": abs(qty),
            "_closing_action": get_closing_action(pos_type),
            "_pnl": pnl
        }
        
        option_positions.append(enriched_pos)
    
    if not option_positions:
        st.info("📭 No open option positions to square off")
        return
    
    st.success(f"**{len(option_positions)} open position(s)**")
    
    # Display positions table
    position_rows = []
    for pos in option_positions:
        position_rows.append({
            "Instrument": C.api_code_to_display(pos.get("stock_code", "")),
            "Strike": pos.get("strike_price"),
            "Type": C.normalize_option_type(pos.get("right", "")),
            "Position": pos["_position_type"].upper(),
            "Qty": pos["_quantity"],
            "Avg": f"₹{safe_float(pos.get('average_price', 0)):.2f}",
            "LTP": f"₹{safe_float(pos.get('ltp', 0)):.2f}",
            "P&L": f"₹{pos['_pnl']:+,.2f}",
            "To Close": pos["_closing_action"].upper()
        })
    
    st.dataframe(
        pd.DataFrame(position_rows),
        use_container_width=True,
        hide_index=True
    )
    
    # Debug mode - show raw data
    if st.session_state.get("debug_mode"):
        with st.expander("🔧 Raw Position Data"):
            for pos in option_positions:
                clean_pos = {k: v for k, v in pos.items() if not k.startswith("_")}
                st.json(clean_pos)
    
    st.markdown("---")
    
    # Individual square off
    st.markdown('<h2 class="section-header">Individual Square Off</h2>', unsafe_allow_html=True)
    
    position_labels = [
        f"{C.api_code_to_display(p.get('stock_code', ''))} "
        f"{p.get('strike_price')} {C.normalize_option_type(p.get('right', ''))} | "
        f"{p['_position_type'].upper()} | Qty: {p['_quantity']}"
        for p in option_positions
    ]
    
    selected_idx = st.selectbox(
        "Select Position",
        range(len(position_labels)),
        format_func=lambda i: position_labels[i],
        key="sq_position"
    )
    
    selected_position = option_positions[selected_idx]
    
    # Display selected position details
    st.markdown(
        f'<div class="info-box">'
        f'<b>Position:</b> {selected_position["_position_type"].upper()}<br>'
        f'<b>Action to Close:</b> {selected_position["_closing_action"].upper()}<br>'
        f'<b>Current P&L:</b> ₹{selected_position["_pnl"]:+,.2f}'
        f'</div>',
        unsafe_allow_html=True
    )
    
    # Square off controls
    col1, col2 = st.columns(2)
    
    with col1:
        sq_order_type = st.radio(
            "Order Type",
            ["Market", "Limit"],
            horizontal=True,
            key="sq_order_type"
        )
    
    with col2:
        sq_price = 0.0
        if sq_order_type == "Limit":
            sq_price = st.number_input(
                "Limit Price",
                min_value=0.0,
                value=safe_float(selected_position.get("ltp", 0)),
                step=0.05,
                key="sq_price"
            )
    
    sq_quantity = st.slider(
        "Quantity to Close",
        min_value=1,
        max_value=selected_position["_quantity"],
        value=selected_position["_quantity"],
        key="sq_qty"
    )
    
    # Submit square off
    if st.button(
        f"🔄 {selected_position['_closing_action'].upper()} {sq_quantity} to Close",
        type="primary",
        use_container_width=True
    ):
        with st.spinner(f"{selected_position['_closing_action'].upper()}ing..."):
            response = client.square_off(
                stock_code=selected_position.get("stock_code"),
                exchange=selected_position.get("exchange_code"),
                expiry=selected_position.get("expiry_date"),
                strike=safe_int(selected_position.get("strike_price")),
                option_type=C.normalize_option_type(selected_position.get("right")),
                quantity=sq_quantity,
                position_type=selected_position["_position_type"],
                order_type=sq_order_type.lower(),
                price=sq_price
            )
            
            if response["success"]:
                st.success(f"✅ {selected_position['_closing_action'].upper()} order placed successfully!")
                SessionState.log_activity(
                    "Square Off",
                    f"{selected_position.get('stock_code')} {selected_position.get('strike_price')}"
                )
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"❌ {response['message']}")
    
    st.markdown("---")
    
    # Bulk square off
    st.markdown('<h2 class="section-header">⚡ Square Off All Positions</h2>', unsafe_allow_html=True)
    
    st.markdown(
        '<div class="danger-box">'
        '<h4>⚠️ WARNING</h4>'
        '<p>This will close <b>ALL</b> open option positions at market price.</p>'
        '<p>This action cannot be undone!</p>'
        '</div>',
        unsafe_allow_html=True
    )
    
    confirm_all = st.checkbox(
        "I confirm I want to close all positions",
        key="sq_all_confirm"
    )
    
    if st.button(
        "🔴 SQUARE OFF ALL POSITIONS",
        type="primary",
        use_container_width=True,
        disabled=not confirm_all
    ):
        with st.spinner("Closing all positions..."):
            results = client.square_off_all_positions()
            
            success_count = sum(1 for r in results if r.get("success"))
            fail_count = len(results) - success_count
            
            if success_count > 0:
                st.success(f"✅ Successfully closed {success_count} position(s)")
            
            if fail_count > 0:
                st.warning(f"⚠️ Failed to close {fail_count} position(s)")
            
            SessionState.log_activity("Square Off All", f"{success_count} closed")
            
            time.sleep(2)
            st.rerun()


# ═══════════════════════════════════════════════════════════════════
# PAGE: ORDERS & TRADES
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_orders_trades():
    """Orders and trades management page."""
    st.markdown('<h1 class="page-header">📋 Orders & Trades</h1>', unsafe_allow_html=True)
    
    client = SessionState.get_client()
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["📋 Orders", "📊 Trades", "📝 Activity Log"])
    
    # ─── ORDERS TAB ───────────────────────────────────────────────
    with tab1:
        st.markdown("### Order Book")
        
        # Filters
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        
        with col1:
            exchange_filter = st.selectbox(
                "Exchange",
                ["All", "NFO", "BFO"],
                key="orders_exchange"
            )
        
        with col2:
            from_date = st.date_input(
                "From",
                value=date.today() - timedelta(days=7),
                key="orders_from"
            )
        
        with col3:
            to_date = st.date_input(
                "To",
                value=date.today(),
                key="orders_to"
            )
        
        with col4:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄", key="orders_refresh", use_container_width=True):
                st.rerun()
        
        # Validate date range
        try:
            validate_date_range(from_date, to_date)
        except ValueError as e:
            st.error(f"❌ {e}")
            return
        
        # Fetch orders
        with st.spinner("Loading orders..."):
            response = client.get_order_list(
                exchange="" if exchange_filter == "All" else exchange_filter,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d")
            )
        
        if not response["success"]:
            st.error(f"❌ {response['message']}")
        else:
            parsed = APIResponse(response)
            orders = parsed.items
            
            if not orders:
                st.info("📭 No orders found for selected period")
            else:
                # Summary metrics
                col1, col2, col3, col4 = st.columns(4)
                
                executed = sum(1 for o in orders if str(o.get("order_status", "")).lower() == "executed")
                pending = sum(1 for o in orders if str(o.get("order_status", "")).lower() in ("pending", "open"))
                rejected = sum(1 for o in orders if str(o.get("order_status", "")).lower() == "rejected")
                
                col1.metric("Total", len(orders))
                col2.metric("Executed", executed)
                col3.metric("Pending", pending)
                col4.metric("Rejected", rejected)
                
                # Orders table
                st.dataframe(
                    pd.DataFrame(orders),
                    use_container_width=True,
                    height=400,
                    hide_index=True
                )
                
                # Manage pending orders
                pending_orders = [
                    o for o in orders
                    if str(o.get("order_status", "")).lower() in ("pending", "open")
                ]
                
                if pending_orders:
                    st.markdown("---")
                    st.markdown("### Manage Pending Orders")
                    
                    pending_labels = [
                        f"#{o.get('order_id', '?')} - {o.get('stock_code', '')} - {o.get('action', '').upper()}"
                        for o in pending_orders
                    ]
                    
                    selected_pending_idx = st.selectbox(
                        "Select Order",
                        range(len(pending_labels)),
                        format_func=lambda i: pending_labels[i],
                        key="pending_order_select"
                    )
                    
                    selected_order = pending_orders[selected_pending_idx]
                    
                    # Display order details
                    with st.expander("📄 Order Details", expanded=True):
                        detail_col1, detail_col2, detail_col3 = st.columns(3)
                        
                        with detail_col1:
                            st.write(f"**Order ID:** {selected_order.get('order_id')}")
                            st.write(f"**Stock:** {selected_order.get('stock_code')}")
                        
                        with detail_col2:
                            st.write(f"**Action:** {selected_order.get('action', '').upper()}")
                            st.write(f"**Strike:** {selected_order.get('strike_price')}")
                        
                        with detail_col3:
                            st.write(f"**Quantity:** {selected_order.get('quantity')}")
                            st.write(f"**Price:** ₹{safe_float(selected_order.get('price', 0)):.2f}")
                    
                    # Order actions
                    action_col1, action_col2 = st.columns(2)
                    
                    with action_col1:
                        if st.button("❌ Cancel Order", use_container_width=True, key="cancel_order"):
                            with st.spinner("Cancelling..."):
                                cancel_response = client.cancel_order(
                                    selected_order.get("order_id"),
                                    selected_order.get("exchange_code")
                                )
                                
                                if cancel_response["success"]:
                                    st.success("✅ Order cancelled")
                                    SessionState.log_activity(
                                        "Cancel Order",
                                        selected_order.get("order_id", "")
                                    )
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"❌ {cancel_response['message']}")
                    
                    with action_col2:
                        with st.expander("✏️ Modify Order"):
                            new_price = st.number_input(
                                "New Price",
                                min_value=0.0,
                                value=safe_float(selected_order.get("price", 0)),
                                step=0.05,
                                key="modify_price"
                            )
                            
                            new_qty = st.number_input(
                                "New Quantity",
                                min_value=1,
                                value=max(1, safe_int(selected_order.get("quantity", 1))),
                                step=1,
                                key="modify_qty"
                            )
                            
                            if st.button("💾 Save Changes", key="modify_order"):
                                with st.spinner("Modifying..."):
                                    modify_response = client.modify_order(
                                        selected_order.get("order_id"),
                                        selected_order.get("exchange_code"),
                                        new_qty,
                                        new_price
                                    )
                                    
                                    if modify_response["success"]:
                                        st.success("✅ Order modified")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {modify_response['message']}")
    
    # ─── TRADES TAB ───────────────────────────────────────────────
    with tab2:
        st.markdown("### Trade Book")
        
        # Filters
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        
        with col1:
            trade_exchange_filter = st.selectbox(
                "Exchange",
                ["All", "NFO", "BFO"],
                key="trades_exchange"
            )
        
        with col2:
            trade_from = st.date_input(
                "From",
                value=date.today() - timedelta(days=7),
                key="trades_from"
            )
        
        with col3:
            trade_to = st.date_input(
                "To",
                value=date.today(),
                key="trades_to"
            )
        
        with col4:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄", key="trades_refresh", use_container_width=True):
                st.rerun()
        
        # Validate date range
        try:
            validate_date_range(trade_from, trade_to)
        except ValueError as e:
            st.error(f"❌ {e}")
            return
        
        # Fetch trades
        with st.spinner("Loading trades..."):
            response = client.get_trade_list(
                exchange="" if trade_exchange_filter == "All" else trade_exchange_filter,
                from_date=trade_from.strftime("%Y-%m-%d"),
                to_date=trade_to.strftime("%Y-%m-%d")
            )
        
        if not response["success"]:
            st.error(f"❌ {response['message']}")
        else:
            parsed = APIResponse(response)
            trades = parsed.items
            
            if not trades:
                st.info("📭 No trades found for selected period")
            else:
                # Summary metrics
                col1, col2, col3 = st.columns(3)
                
                buy_count = sum(1 for t in trades if str(t.get("action", "")).lower() == "buy")
                sell_count = sum(1 for t in trades if str(t.get("action", "")).lower() == "sell")
                
                col1.metric("Total Trades", len(trades))
                col2.metric("Buys", buy_count)
                col3.metric("Sells", sell_count)
                
                # Trades table
                st.dataframe(
                    pd.DataFrame(trades),
                    use_container_width=True,
                    height=400,
                    hide_index=True
                )
    
    # ─── ACTIVITY LOG TAB ─────────────────────────────────────────
    with tab3:
        st.markdown("### Session Activity Log")
        
        activity_log = SessionState.get_activity_log()
        
        if not activity_log:
            st.info("No activity logged this session")
        else:
            # Display as dataframe
            st.dataframe(
                pd.DataFrame(activity_log),
                use_container_width=True,
                hide_index=True
            )
            
            # Download option
            if st.button("📥 Download Activity Log", use_container_width=True):
                csv = pd.DataFrame(activity_log).to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv,
                    file_name=f"activity_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )


# ═══════════════════════════════════════════════════════════════════
# PAGE: POSITIONS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_positions():
    """Detailed positions view with analytics."""
    st.markdown('<h1 class="page-header">📍 Positions</h1>', unsafe_allow_html=True)
    
    client = SessionState.get_client()
    
    # Refresh button
    if st.button("🔄 Refresh Positions", use_container_width=True):
        CacheManager.clear_all("positions")
        st.rerun()
    
    # Fetch positions
    with st.spinner("Loading positions..."):
        response = client.get_positions()
    
    if not response["success"]:
        st.error(f"❌ {response['message']}")
        return
    
    parsed = APIResponse(response)
    all_positions = parsed.items
    
    # Filter active positions
    active_positions = []
    total_pnl = 0.0
    
    for pos in all_positions:
        qty = safe_int(pos.get("quantity", 0))
        if qty == 0:
            continue
        
        pos_type = detect_position_type(pos)
        avg_price = safe_float(pos.get("average_price", 0))
        ltp = safe_float(pos.get("ltp", avg_price))
        pnl = calculate_pnl(pos_type, avg_price, ltp, qty)
        
        total_pnl += pnl
        
        active_positions.append({
            "stock_code": pos.get("stock_code"),
            "display_name": C.api_code_to_display(pos.get("stock_code", "")),
            "exchange": pos.get("exchange_code"),
            "expiry": pos.get("expiry_date"),
            "strike": pos.get("strike_price"),
            "option_type": C.normalize_option_type(pos.get("right", "")),
            "position_type": pos_type,
            "quantity": abs(qty),
            "avg_price": avg_price,
            "ltp": ltp,
            "pnl": pnl,
            "raw": pos
        })
    
    if not active_positions:
        st.info("📭 No active positions")
        return
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    long_count = sum(1 for p in active_positions if p["position_type"] == "long")
    short_count = len(active_positions) - long_count
    
    col1.metric("Total Positions", len(active_positions))
    col2.metric("Long Positions", long_count)
    col3.metric("Short Positions", short_count)
    
    pnl_color = "normal" if total_pnl >= 0 else "inverse"
    col4.metric("Total P&L", format_currency(total_pnl), delta_color=pnl_color)
    
    # Positions table
    st.markdown("---")
    
    table_data = []
    for pos in active_positions:
        table_data.append({
            "Instrument": pos["display_name"],
            "Strike": pos["strike"],
            "Type": pos["option_type"],
            "Position": pos["position_type"].upper(),
            "Qty": pos["quantity"],
            "Avg Price": f"₹{pos['avg_price']:.2f}",
            "LTP": f"₹{pos['ltp']:.2f}",
            "P&L": f"₹{pos['pnl']:+,.2f}",
            "Close": get_closing_action(pos["position_type"]).upper()
        })
    
    st.dataframe(
        pd.DataFrame(table_data),
        use_container_width=True,
        hide_index=True
    )
    
    # Debug mode
    if st.session_state.get("debug_mode"):
        with st.expander("🔧 Raw Position Data"):
            for pos in active_positions:
                st.json(pos["raw"])
    
    # Individual position details
    st.markdown("---")
    st.markdown('<h2 class="section-header">Position Details</h2>', unsafe_allow_html=True)
    
    for pos in active_positions:
        pnl_emoji = "📈" if pos["pnl"] >= 0 else "📉"
        pos_badge = "🟢 LONG" if pos["position_type"] == "long" else "🔴 SHORT"
        
        with st.expander(
            f"{pnl_emoji} {pos['display_name']} {pos['strike']} {pos['option_type']} | "
            f"{pos_badge} | {format_currency(pos['pnl'])}"
        ):
            detail_col1, detail_col2, detail_col3 = st.columns(3)
            
            with detail_col1:
                st.write(f"**Stock Code:** {pos['stock_code']}")
                st.write(f"**Exchange:** {pos['exchange']}")
                st.write(f"**Expiry:** {format_expiry(pos['expiry'])}")
            
            with detail_col2:
                st.write(f"**Position:** {pos['position_type'].upper()}")
                st.write(f"**Quantity:** {pos['quantity']}")
                st.write(f"**Average Price:** ₹{pos['avg_price']:.2f}")
            
            with detail_col3:
                st.write(f"**Current LTP:** ₹{pos['ltp']:.2f}")
                
                pnl_class = "profit" if pos["pnl"] >= 0 else "loss"
                st.markdown(
                    f'<p class="{pnl_class}">P&L: {format_currency(pos["pnl"])}</p>',
                    unsafe_allow_html=True
                )
                
                st.write(f"**To Close:** {get_closing_action(pos['position_type']).upper()}")
            
            # Quick square off button
            if st.button(
                "🔄 Square Off This Position",
                key=f"sq_btn_{pos['stock_code']}_{pos['strike']}_{pos['option_type']}",
                use_container_width=True
            ):
                SessionState.navigate_to("Square Off")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════
# PAGE: STRATEGY BUILDER (NEW)
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_strategy_builder():
    """Multi-leg options strategy builder."""
    st.markdown('<h1 class="page-header">🎯 Strategy Builder</h1>', unsafe_allow_html=True)
    
    st.info("🚧 **Coming Soon:** Build and analyze multi-leg option strategies like Iron Condor, Butterfly, Straddle, etc.")
    
    # Placeholder for future implementation
    st.markdown("""
    ### Planned Features:
    
    - **Pre-built Strategies:**
      - Bull Call Spread
      - Bear Put Spread
      - Iron Condor
      - Butterfly
      - Straddle / Strangle
      - Calendar Spread
    
    - **Custom Strategy Builder:**
      - Add/remove legs
      - Visual payoff diagram
      - Risk/reward analysis
      - Breakeven calculation
    
    - **Strategy Analysis:**
      - Max profit/loss
      - Probability of profit
      - Greeks for entire strategy
      - Margin requirements
    
    - **One-Click Execution:**
      - Execute all legs together
      - Automatic order management
    """)


# ═══════════════════════════════════════════════════════════════════
# PAGE: ANALYTICS (NEW)
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_analytics():
    """Portfolio analytics and risk metrics."""
    st.markdown('<h1 class="page-header">📈 Analytics</h1>', unsafe_allow_html=True)
    
    st.info("🚧 **Coming Soon:** Advanced portfolio analytics and risk metrics")
    
    # Placeholder for future implementation
    st.markdown("""
    ### Planned Features:
    
    - **Portfolio Greeks:**
      - Aggregate Delta, Gamma, Theta, Vega
      - Greek exposure by instrument
      - Greeks over time
    
    - **Risk Metrics:**
      - Value at Risk (VaR)
      - Maximum Drawdown
      - Sharpe Ratio
      - Win Rate & Profit Factor
    
    - **Performance Analytics:**
      - P&L charts
      - Trade distribution
      - Return analysis
      - Benchmark comparison
    
    - **Trade Journal:**
      - Annotate trades
      - Tag strategies
      - Performance by strategy
      - Learning notes
    """)


# ═══════════════════════════════════════════════════════════════════
# MAIN APP ROUTER
# ═══════════════════════════════════════════════════════════════════

# Page router
PAGE_FUNCTIONS = {
    "Dashboard": page_dashboard,
    "Option Chain": page_option_chain,
    "Sell Options": page_sell_options,
    "Square Off": page_square_off,
    "Orders & Trades": page_orders_trades,
    "Positions": page_positions,
    "Strategy Builder": page_strategy_builder,
    "Analytics": page_analytics
}


def main():
    """Main application entry point."""
    # Initialize session state
    SessionState.initialize()
    
    # Render sidebar
    render_sidebar()
    
    # Render main header
    st.markdown(
        '<h1 class="main-header">📈 Breeze Options Trader</h1>',
        unsafe_allow_html=True
    )
    
    st.markdown("---")
    
    # Get current page
    current_page = SessionState.get_current_page()
    
    # Check authentication for protected pages
    if current_page in AUTH_REQUIRED_PAGES and not SessionState.is_authenticated():
        st.warning("🔒 Authentication required to access this page")
        st.info("👈 Please login using the sidebar")
        return
    
    # Check for session expiry
    if SessionState.is_authenticated() and SessionState.is_session_expired():
        st.error("🔴 Your session has expired. Please reconnect.")
        SessionState.set_authentication(False, None)
        SessionState.navigate_to("Dashboard")
        time.sleep(2)
        st.rerun()
        return
    
    # Render the current page
    page_function = PAGE_FUNCTIONS.get(current_page, page_dashboard)
    page_function()
    
    # Auto-refresh if enabled
    if st.session_state.get("auto_refresh", False) and SessionState.is_authenticated():
        time.sleep(30)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════
# RUN APP
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
