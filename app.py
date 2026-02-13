"""
Breeze Options Trader v8.0 — Main Application
Fixes: UnboundLocalError in sidebar, retry logic, real spot prices,
       persistent trade logging, background risk monitoring.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from functools import wraps
import time
import logging
from typing import Dict, List, Optional

import app_config as C
from helpers import (
    APIResponse, safe_int, safe_float, safe_str, parse_funds,
    detect_position_type, get_closing_action, calculate_pnl,
    process_option_chain, create_pivot_table,
    calculate_pcr, calculate_max_pain, estimate_atm_strike,
    add_greeks_to_chain, get_market_status, format_currency,
    format_expiry, calculate_days_to_expiry
)
from analytics import calculate_greeks, estimate_implied_volatility
from session_manager import (
    Credentials, SessionState, CacheManager, Notifications
)
from breeze_api import BreezeAPIClient
from validators import validate_date_range
from strategies import (
    StrategyLeg, PREDEFINED_STRATEGIES, generate_strategy_legs,
    calculate_strategy_metrics, generate_payoff_data
)
from persistence import TradeDB
from risk_monitor import RiskMonitor, Alert

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

_db = TradeDB()


# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG & CSS
# ═══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Breeze Options Trader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""<style>
.page-header {font-size: 2rem; font-weight: 700; color: #1f77b4; border-bottom: 4px solid #1f77b4; padding-bottom: 0.5rem; margin-bottom: 1.5rem;}
.section-header {font-size: 1.5rem; font-weight: 600; color: #2c3e50; margin: 1.5rem 0 1rem;}
.status-connected {background: #d4edda; color: #155724; padding: 6px 14px; border-radius: 16px; font-weight: 600; display: inline-block;}
.profit {color: #28a745 !important; font-weight: 700;}
.loss {color: #dc3545 !important; font-weight: 700;}
.info-box {background: #e7f3ff; border-left: 5px solid #2196F3; padding: 1rem; margin: 1rem 0; border-radius: 0 8px 8px 0;}
.danger-box {background: #f8d7da; border-left: 5px solid #dc3545; padding: 1rem; margin: 1rem 0; border-radius: 0 8px 8px 0;}
.metric-card {background: #f8f9fa; padding: 1.25rem; border-radius: 8px; border: 1px solid #dee2e6;}
.empty-state {text-align: center; padding: 3rem 1rem; color: #6c757d;}
.empty-state-icon {font-size: 4rem; margin-bottom: 1rem; opacity: 0.5;}
#MainMenu {visibility: hidden}
footer {visibility: hidden}
header {visibility: hidden}
</style>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════

PAGES = [
    "Dashboard", "Option Chain", "Sell Options", "Square Off",
    "Orders & Trades", "Positions", "Strategy Builder",
    "Analytics", "Risk Monitor"
]

ICONS = {
    "Dashboard": "🏠", "Option Chain": "📊",
    "Sell Options": "💰", "Square Off": "🔄",
    "Orders & Trades": "📋", "Positions": "📍",
    "Strategy Builder": "🎯", "Analytics": "📈",
    "Risk Monitor": "🛡️"
}

AUTH_PAGES = set(PAGES[1:])


# ═══════════════════════════════════════════════════════════════
# DECORATORS
# ═══════════════════════════════════════════════════════════════

def error_handler(f):
    @wraps(f)
    def w(*a, **k):
        try:
            return f(*a, **k)
        except Exception as e:
            log.error(f"{f.__name__}: {e}", exc_info=True)
            st.error(f"❌ {e}")
            if st.session_state.get("debug_mode"):
                st.exception(e)
    return w


def require_auth(f):
    @wraps(f)
    def w(*a, **k):
        if not SessionState.is_authenticated():
            st.warning("🔒 Please login")
            return
        return f(*a, **k)
    return w


# ═══════════════════════════════════════════════════════════════
# COMMON HELPERS
# ═══════════════════════════════════════════════════════════════

def empty_state(icon, msg, sub=""):
    st.markdown(
        f'<div class="empty-state">'
        f'<div class="empty-state-icon">{icon}</div>'
        f'<h3>{msg}</h3><p>{sub}</p></div>',
        unsafe_allow_html=True
    )


def get_client():
    c = SessionState.get_client()
    if not c or not c.is_connected():
        st.error("❌ Not connected")
        return None
    return c


def get_cached_funds(client):
    cached = CacheManager.get("funds", "funds")
    if cached:
        return cached
    resp = client.get_funds()
    if resp["success"]:
        funds = parse_funds(resp)
        CacheManager.set("funds", funds, "funds", C.FUNDS_CACHE_TTL_SECONDS)
        return funds
    return None


def get_cached_positions(client):
    cached = CacheManager.get("positions", "positions")
    if cached is not None:
        return cached
    resp = client.get_positions()
    if resp["success"]:
        items = APIResponse(resp).items
        CacheManager.set(
            "positions", items, "positions",
            C.POSITION_CACHE_TTL_SECONDS
        )
        return items
    return None


def split_positions(all_pos):
    options, equities = [], []
    for p in (all_pos or []):
        qty = safe_int(p.get("quantity", 0))
        if qty == 0:
            continue
        if C.is_option_position(p):
            options.append(p)
        elif C.is_equity_position(p):
            equities.append(p)
    return options, equities


def invalidate_trading_caches():
    CacheManager.invalidate("positions", "positions")
    CacheManager.invalidate("funds", "funds")


def fetch_spot_prices(client, positions):
    stock_codes = set()
    for p in positions:
        if C.is_option_position(p):
            stock_codes.add(p.get("stock_code", ""))

    spot_prices = {}
    for code in stock_codes:
        if not code:
            continue
        ck = f"spot_{code}"
        cached = CacheManager.get(ck, "spot")
        if cached:
            spot_prices[code] = cached
            continue

        cfg = None
        for n, c in C.INSTRUMENTS.items():
            if c.api_code == code:
                cfg = c
                break
        if not cfg:
            continue

        try:
            resp = client.get_spot_price(code, cfg.exchange)
            if resp["success"]:
                items = APIResponse(resp).items
                if items:
                    ltp = safe_float(items[0].get("ltp", 0))
                    if ltp > 0:
                        spot_prices[code] = ltp
                        CacheManager.set(
                            ck, ltp, "spot",
                            C.SPOT_CACHE_TTL_SECONDS
                        )
        except Exception:
            pass
    return spot_prices


def render_alert_banner():
    monitor = st.session_state.get("risk_monitor")
    if not monitor or not monitor.is_running():
        return
    for alert in monitor.get_alerts():
        if alert.level == "CRITICAL":
            st.error(f"🚨 {alert.message}")
        elif alert.level == "WARNING":
            st.warning(f"⚠️ {alert.message}")
        else:
            st.info(f"ℹ️ {alert.message}")


# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown("## 📈 Breeze Trader")
        st.markdown("---")
        
        # Check secrets availability immediately at top level scope
        has_secrets = Credentials.has_stored_credentials()

        avail = PAGES if SessionState.is_authenticated() else ["Dashboard"]
        cur = SessionState.get_current_page()
        if cur not in avail:
            cur = "Dashboard"
            SessionState.navigate_to(cur)

        try:
            idx = avail.index(cur)
        except ValueError:
            idx = 0

        sel = st.radio(
            "Nav", avail, index=idx,
            format_func=lambda p: f"{ICONS.get(p, '')} {p}",
            label_visibility="collapsed", key="nav"
        )
        if sel != cur:
            SessionState.navigate_to(sel)
            st.rerun()

        st.markdown("---")

        if SessionState.is_authenticated():
            st.markdown(
                '<span class="status-connected">✅ Connected</span>',
                unsafe_allow_html=True
            )
            name = st.session_state.get("user_name", "Trader")
            st.markdown(f"**👤 {name}**")
            dur = SessionState.get_login_duration()
            if dur:
                st.caption(f"⏱️ {dur}")

            if SessionState.is_session_expired():
                st.error("🔴 Expired")
            elif SessionState.is_session_stale():
                st.warning("⚠️ Session aging")

            st.markdown("---")
            ms = get_market_status()
            st.markdown(f"**{ms}**")

            client = get_client()
            if client:
                funds = get_cached_funds(client)
                if funds:
                    st.metric(
                        "Unallocated",
                        format_currency(funds["unallocated"])
                    )

            st.markdown("---")
            if st.button("🔓 Disconnect"):
                monitor = st.session_state.get("risk_monitor")
                if monitor:
                    monitor.stop()
                SessionState.set_authentication(False, None)
                Credentials.clear_runtime_credentials()
                CacheManager.clear_all()
                SessionState.navigate_to("Dashboard")
                st.rerun()

        else:
            if has_secrets:
                st.markdown("### 🔑 Daily Login")
                st.success("✅ API Keys loaded from secrets")
                
                with st.form("quick_login"):
                    tok = st.text_input(
                        "Session Token", type="password",
                        placeholder="Paste from ICICI (8 digits)"
                    )
                    
                    if st.form_submit_button("🔑 Connect", type="primary"):
                        if tok and len(tok.strip()) >= 4:
                            k, s, _ = Credentials.get_all_credentials()
                            do_login(k, s, tok.strip())
                        else:
                            st.warning("Enter valid token")
            else:
                st.markdown("### 🔐 Login")
                st.warning("⚠️ No secrets found. Enter keys manually.")
                with st.form("full_login"):
                    k, s, _ = Credentials.get_all_credentials()
                    nk = st.text_input("API Key", value=k, type="password")
                    ns = st.text_input("API Secret", value=s, type="password")
                    tok = st.text_input("Session Token", type="password")
                    if st.form_submit_button("🔑 Connect", type="primary"):
                        if all([nk, ns, tok]):
                            do_login(nk.strip(), ns.strip(), tok.strip())
                        else:
                            st.warning("Fill all fields")

        st.markdown("---")
        with st.expander("⚙️ Settings"):
            st.selectbox(
                "Instrument",
                list(C.INSTRUMENTS.keys()),
                key="selected_instrument"
            )
            st.session_state.debug_mode = st.checkbox(
                "Debug",
                value=st.session_state.get("debug_mode", False)
            )
            
            # DEBUGGER: Show loaded keys status (safe)
            if has_secrets:
                k, s, _ = Credentials.get_all_credentials()
                st.caption(f"Key loaded: {k[:4]}...{k[-4:] if len(k)>8 else ''}")
                
        st.caption("v8.0.2")


def do_login(api_key, api_secret, token):
    if not api_key or not api_secret:
        st.error("❌ Missing API Keys. Check secrets.toml or enter manually.")
        return

    with st.spinner("Connecting..."):
        try:
            client = BreezeAPIClient(api_key, api_secret)
            resp = client.connect(token)
            
            if resp["success"]:
                Credentials.save_runtime_credentials(
                    api_key, api_secret, token
                )
                SessionState.set_authentication(True, client)
                st.session_state.user_name = "Trader"
                SessionState.log_activity("Login", "Connected")
                _db.log_activity("LOGIN", "Session started")

                monitor = RiskMonitor(
                    api_client=client, poll_interval=15.0
                )
                st.session_state.risk_monitor = monitor

                Notifications.success("Connected!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(f"❌ Connection Failed: {resp.get('message', 'Unknown error')}")
                if 'session' in resp.get('message', '').lower():
                    st.info("💡 Hint: Session tokens expire daily. Login to ICICI Breeze to get a new one.")
                
                if st.session_state.get("debug_mode"):
                    st.json(resp)
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            if st.session_state.get("debug_mode"):
                st.exception(e)


# ═══════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ═══════════════════════════════════════════════════════════════

@error_handler
def page_dashboard():
    st.markdown(
        '<h1 class="page-header">🏠 Dashboard</h1>',
        unsafe_allow_html=True
    )

    if not SessionState.is_authenticated():
        st.markdown("### Welcome to Breeze Options Trader")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("📊 **Market Data** — Option chains, Greeks, OI")
        with c2:
            st.markdown("💰 **Trading** — Sell options, strategies")
        with c3:
            st.markdown("🛡️ **Risk** — P&L, margin, stop-loss alerts")
        st.markdown("---")
        data = [
            {
                "Name": n, "Desc": c.description,
                "Exchange": c.exchange, "Lot": c.lot_size,
                "Gap": c.strike_gap
            }
            for n, c in C.INSTRUMENTS.items()
        ]
        st.dataframe(pd.DataFrame(data), hide_index=True)
        st.info("👈 Login to start")
        return

    client = get_client()
    if not client:
        return

    # ── Funds ─────────────────────────────────────────────
    st.markdown(
        '<h2 class="section-header">💰 Account</h2>',
        unsafe_allow_html=True
    )
    funds = get_cached_funds(client)
    if funds:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Balance", format_currency(funds["total_balance"]))
        c2.metric("Allocated F&O", format_currency(funds["allocated_fno"]))
        c3.metric("Unallocated", format_currency(funds["unallocated"]))
        util = (
            funds["allocated_fno"] / funds["total_balance"] * 100
            if funds["total_balance"] > 0 else 0
        )
        c4.metric("Utilization", f"{util:.1f}%")

    # ── Positions ─────────────────────────────────────────
    all_pos = get_cached_positions(client)
    if all_pos is None:
        st.error("❌ Cannot load positions")
        return
    opt_pos, eq_pos = split_positions(all_pos)

    st.markdown("---")
    tab1, tab2 = st.tabs([
        f"📍 Options ({len(opt_pos)})",
        f"📦 Equity ({len(eq_pos)})"
    ])

    with tab1:
        if not opt_pos:
            empty_state(
                "📭", "No option positions",
                "Sell options to get started"
            )
            if st.button("💰 Go to Sell Options"):
                SessionState.navigate_to("Sell Options")
                st.rerun()
        else:
            total_pnl = 0.0
            rows = []
            for p in opt_pos:
                qty = safe_int(p.get("quantity", 0))
                pt = detect_position_type(p)
                avg = safe_float(p.get("average_price", 0))
                ltp = safe_float(p.get("ltp", avg))
                pnl = calculate_pnl(pt, avg, ltp, abs(qty))
                total_pnl += pnl
                rows.append({
                    "Instrument": C.api_code_to_display(
                        p.get("stock_code", "")
                    ),
                    "Strike": p.get("strike_price"),
                    "Type": C.normalize_option_type(p.get("right", "")),
                    "Pos": pt.upper(),
                    "Qty": abs(qty),
                    "Avg": f"₹{avg:.2f}",
                    "LTP": f"₹{ltp:.2f}",
                    "P&L": f"₹{pnl:+,.2f}"
                })
            if rows:
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.dataframe(pd.DataFrame(rows), hide_index=True)
                with c2:
                    cl = "profit" if total_pnl >= 0 else "loss"
                    st.markdown(
                        f'<div class="metric-card">'
                        f'<h4>Total P&L</h4>'
                        f'<h2 class="{cl}">'
                        f'{format_currency(total_pnl)}</h2></div>',
                        unsafe_allow_html=True
                    )

    with tab2:
        if not eq_pos:
            empty_state("📦", "No equity positions")
        else:
            eq_rows = []
            for p in eq_pos:
                pnl_val = safe_float(p.get("pnl", 0))
                eq_rows.append({
                    "Stock": p.get("stock_code", ""),
                    "Qty": safe_int(p.get("quantity", 0)),
                    "Avg": f"₹{safe_float(p.get('average_price', 0)):.2f}",
                    "LTP": f"₹{safe_float(p.get('ltp', 0)):.2f}",
                    "P&L": f"₹{pnl_val:+,.2f}",
                    "Type": p.get("product_type", "")
                })
            st.dataframe(pd.DataFrame(eq_rows), hide_index=True)
            total_eq = sum(
                safe_float(p.get("pnl", 0)) for p in eq_pos
            )
            st.metric("Total Equity P&L", format_currency(total_eq))

    # ── Quick Actions ─────────────────────────────────────
    st.markdown("---")
    st.markdown(
        '<h2 class="section-header">⚡ Quick Actions</h2>',
        unsafe_allow_html=True
    )
    c1, c2, c3, c4 = st.columns(4)
    actions = [
        ("📊 Chain", "Option Chain"),
        ("💰 Sell", "Sell Options"),
        ("🔄 Square Off", "Square Off"),
        ("🛡️ Risk", "Risk Monitor")
    ]
    for col, (label, page) in zip([c1, c2, c3, c4], actions):
        with col:
            if st.button(label):
                SessionState.navigate_to(page)
                st.rerun()

    # ── Persistent Trade Summary ──────────────────────────
    summary = _db.get_trade_summary()
    if summary and summary.get("total", 0) > 0:
        st.markdown("---")
        st.markdown(
            '<h2 class="section-header">'
            '📊 Session Stats (Persistent)</h2>',
            unsafe_allow_html=True
        )
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Total Trades", summary.get("total", 0))
        sc2.metric(
            "Premium Sold",
            format_currency(summary.get("sold", 0))
        )
        sc3.metric(
            "Premium Bought",
            format_currency(summary.get("bought", 0))
        )


# ═══════════════════════════════════════════════════════════════
# PAGE: OPTION CHAIN
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_option_chain():
    st.markdown(
        '<h1 class="page-header">📊 Option Chain</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        inst = st.selectbox(
            "Instrument", list(C.INSTRUMENTS.keys()), key="oc_inst"
        )
    cfg = C.get_instrument(inst)
    with c2:
        expiries = C.get_next_expiries(inst, 5)
        if not expiries:
            st.error("No expiries")
            return
        expiry = st.selectbox(
            "Expiry", expiries,
            format_func=format_expiry, key="oc_exp"
        )
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh = st.button("🔄 Refresh", key="oc_ref")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        view = st.radio(
            "View", ["Traditional", "Flat", "Calls", "Puts"],
            horizontal=True, key="oc_v"
        )
    with c2:
        n_strikes = st.slider("Strikes±", 5, 50, 15, key="oc_n")
    with c3:
        show_greeks = st.checkbox("Greeks", True, key="oc_g")

    ck = f"oc_{cfg.api_code}_{expiry}"
    if refresh:
        CacheManager.invalidate(ck, "option_chain")
        st.rerun()

    df = CacheManager.get(ck, "option_chain")
    if df is not None:
        st.caption("📦 Cached data")
    else:
        with st.spinner(f"Loading {inst}..."):
            resp = client.get_option_chain(
                cfg.api_code, cfg.exchange, expiry
            )
        if not resp["success"]:
            st.error(f"❌ {resp.get('message')}")
            return
        df = process_option_chain(resp.get("data", {}))
        if df.empty:
            st.warning("No data returned")
            return
        CacheManager.set(ck, df, "option_chain", C.OC_CACHE_TTL_SECONDS)
        SessionState.log_activity(
            "Chain", f"{inst} {format_expiry(expiry)}"
        )

    atm = estimate_atm_strike(df)
    pcr = calculate_pcr(df)
    mp = calculate_max_pain(df)
    dte = calculate_days_to_expiry(expiry)

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("PCR", f"{pcr:.2f}", "Bullish" if pcr > 1 else "Bearish")
    mc2.metric("Max Pain", f"{mp:,.0f}")
    mc3.metric("ATM ≈", f"{atm:,.0f}")
    mc4.metric("DTE", dte)
    st.markdown("---")

    # Filter around ATM
    if "strike_price" in df.columns and atm > 0:
        strikes = sorted(df["strike_price"].unique())
        if strikes:
            ai = min(
                range(len(strikes)),
                key=lambda i: abs(strikes[i] - atm)
            )
            start = max(0, ai - n_strikes)
            end = min(len(strikes), ai + n_strikes + 1)
            filt = strikes[start:end]
            ddf = df[df["strike_price"].isin(filt)].copy()
        else:
            ddf = df.copy()
    else:
        ddf = df.copy()

    spot_for_greeks = atm if atm > 0 else (
        ddf["strike_price"].median()
        if "strike_price" in ddf.columns else 0
    )

    if show_greeks and not ddf.empty and spot_for_greeks > 0:
        try:
            ddf = add_greeks_to_chain(ddf, spot_for_greeks, expiry)
        except Exception:
            pass

    if view == "Traditional":
        pv = create_pivot_table(ddf)
        if not pv.empty:
            st.dataframe(pv, height=600, hide_index=True)
        else:
            st.dataframe(ddf, height=600, hide_index=True)
    elif view == "Calls":
        display = (
            ddf[ddf["right"] == "Call"]
            if "right" in ddf.columns else ddf
        )
        st.dataframe(display, height=600, hide_index=True)
    elif view == "Puts":
        display = (
            ddf[ddf["right"] == "Put"]
            if "right" in ddf.columns else ddf
        )
        st.dataframe(display, height=600, hide_index=True)
    else:
        st.dataframe(ddf, height=600, hide_index=True)

    # OI Chart
    if "right" in ddf.columns and "open_interest" in ddf.columns:
        st.markdown("---")
        st.markdown("### Open Interest")
        try:
            co = ddf[ddf["right"] == "Call"][
                ["strike_price", "open_interest"]
            ].rename(columns={"open_interest": "Call OI"})
            po = ddf[ddf["right"] == "Put"][
                ["strike_price", "open_interest"]
            ].rename(columns={"open_interest": "Put OI"})
            oi = (
                pd.merge(co, po, on="strike_price", how="outer")
                .fillna(0)
                .sort_values("strike_price")
                .set_index("strike_price")
            )
            st.bar_chart(oi)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# PAGE: SELL OPTIONS
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_sell_options():
    st.markdown(
        '<h1 class="page-header">💰 Sell Options</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return

    c1, c2 = st.columns(2)

    with c1:
        inst = st.selectbox(
            "Instrument", list(C.INSTRUMENTS.keys()), key="s_i"
        )
        cfg = C.get_instrument(inst)
        expiries = C.get_next_expiries(inst, 5)
        if not expiries:
            st.error("No expiries")
            return
        expiry = st.selectbox(
            "Expiry", expiries,
            format_func=format_expiry, key="s_e"
        )
        ot = st.radio(
            "Type", ["CE (Call)", "PE (Put)"],
            horizontal=True, key="s_t"
        )
        oc = "CE" if "CE" in ot else "PE"
        default_s = cfg.min_strike + 10 * cfg.strike_gap
        strike = st.number_input(
            "Strike",
            min_value=cfg.min_strike,
            max_value=cfg.max_strike,
            value=default_s,
            step=cfg.strike_gap,
            key="s_s"
        )
        valid = C.validate_strike(inst, strike)
        if not valid:
            st.warning(f"Must be multiple of {cfg.strike_gap}")
        lots = st.number_input(
            "Lots", min_value=1,
            max_value=C.MAX_LOTS_PER_ORDER,
            value=1, key="s_l"
        )
        qty = lots * cfg.lot_size
        st.info(f"**Qty:** {qty:,} ({lots} × {cfg.lot_size})")
        otp = st.radio(
            "Order", ["Market", "Limit"],
            horizontal=True, key="s_o"
        )
        lp = 0.0
        if otp == "Limit":
            lp = st.number_input(
                "Price", min_value=0.0, step=0.05, key="s_p"
            )

    with c2:
        st.markdown("### Preview")
        if st.button("📊 Get Quote", disabled=not valid):
            with st.spinner("Fetching..."):
                r = client.get_quotes(
                    cfg.api_code, cfg.exchange,
                    expiry, int(strike), oc
                )
                if r["success"]:
                    items = APIResponse(r).items
                    if items:
                        q_ltp = safe_float(items[0].get("ltp", 0))
                        st.success(f"LTP: ₹{q_ltp:.2f}")
                        st.info(
                            f"Premium receivable: "
                            f"{format_currency(q_ltp * qty)}"
                        )
                    else:
                        st.warning("No quote data")
                else:
                    st.error(f"❌ {r.get('message')}")

        if st.button("💰 Check Margin", disabled=not valid):
            with st.spinner("Calculating..."):
                r = client.get_margin(
                    cfg.api_code, cfg.exchange, expiry,
                    int(strike), oc, "sell", qty
                )
                if r["success"]:
                    m = safe_float(
                        APIResponse(r).get("required_margin", 0)
                    )
                    st.success(
                        f"Required Margin: {format_currency(m)}"
                    )
                else:
                    st.error(f"❌ {r.get('message')}")

    st.markdown("---")
    st.markdown(
        '<div class="danger-box">'
        '<b>⚠️ RISK:</b> Option selling has unlimited risk. '
        'Use stop-losses.</div>',
        unsafe_allow_html=True
    )

    ack = st.checkbox(
        "✅ I understand and accept the risks", key="s_ack"
    )
    order_in_progress = st.session_state.get(
        "_order_in_progress", False
    )
    can_place = (
        ack and valid and strike > 0
        and (otp == "Market" or lp > 0)
        and not order_in_progress
    )

    if order_in_progress:
        st.warning("⏳ Order in progress, please wait...")

    if st.button(
        f"🔴 SELL {qty:,} {inst} {int(strike)} {oc}",
        type="primary",
        disabled=not can_place
    ):
        st.session_state._order_in_progress = True
        try:
            with st.spinner("Placing order..."):
                if oc == "CE":
                    r = client.sell_call(
                        cfg.api_code, cfg.exchange, expiry,
                        int(strike), qty, otp.lower(), lp
                    )
                else:
                    r = client.sell_put(
                        cfg.api_code, cfg.exchange, expiry,
                        int(strike), qty, otp.lower(), lp
                    )

                if r["success"]:
                    order_id = APIResponse(r).get("order_id", "?")
                    st.success(f"✅ Order placed! ID: {order_id}")
                    st.balloons()

                    _db.log_trade(
                        stock_code=cfg.api_code,
                        exchange=cfg.exchange,
                        strike=int(strike),
                        option_type=oc,
                        expiry=expiry,
                        action="sell",
                        quantity=qty,
                        price=lp,
                        order_type=otp.lower(),
                        trade_id=str(order_id),
                        notes=f"Sold via {inst}"
                    )
                    _db.log_activity(
                        "SELL_ORDER",
                        f"SELL {inst} {int(strike)} {oc} x{qty}"
                    )
                    SessionState.log_activity(
                        "Sell", f"{inst} {int(strike)} {oc}"
                    )
                    invalidate_trading_caches()
                    time.sleep(1.5)
                    st.session_state._order_in_progress = False
                    st.rerun()

                elif r.get("error_code") == "DUPLICATE_ORDER":
                    st.warning(f"⚠️ {r['message']}")
                else:
                    st.error(f"❌ {r.get('message')}")
        finally:
            st.session_state._order_in_progress = False


# ═══════════════════════════════════════════════════════════════
# PAGE: SQUARE OFF
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_square_off():
    st.markdown(
        '<h1 class="page-header">🔄 Square Off</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return
    if st.button("🔄 Refresh Positions"):
        invalidate_trading_caches()
        st.rerun()

    all_pos = get_cached_positions(client)
    if all_pos is None:
        st.error("❌ Load failed")
        return
    opt_pos, _ = split_positions(all_pos)

    enriched = []
    for p in opt_pos:
        pt = detect_position_type(p)
        avg = safe_float(p.get("average_price", 0))
        ltp = safe_float(p.get("ltp", avg))
        q = abs(safe_int(p.get("quantity", 0)))
        pnl = calculate_pnl(pt, avg, ltp, q)
        enriched.append({
            **p,
            "_pt": pt, "_q": q,
            "_close": get_closing_action(pt),
            "_pnl": pnl, "_avg": avg, "_ltp": ltp
        })

    if not enriched:
        empty_state("📭", "No positions to square off")
        if st.button("💰 Go to Sell Options"):
            SessionState.navigate_to("Sell Options")
            st.rerun()
        return

    total = sum(e["_pnl"] for e in enriched)
    st.metric("Total Options P&L", format_currency(total))

    rows = [{
        "#": i + 1,
        "Inst": C.api_code_to_display(e.get("stock_code", "")),
        "Strike": e.get("strike_price"),
        "Type": C.normalize_option_type(e.get("right", "")),
        "Pos": e["_pt"].upper(),
        "Qty": e["_q"],
        "P&L": f"₹{e['_pnl']:+,.2f}",
        "Action": e["_close"].upper()
    } for i, e in enumerate(enriched)]
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    st.markdown("---")
    st.markdown("### Square Off a Position")

    labels = [
        f"{C.api_code_to_display(e.get('stock_code', ''))} "
        f"{e.get('strike_price')} "
        f"{C.normalize_option_type(e.get('right', ''))}"
        for e in enriched
    ]
    si = st.selectbox(
        "Select Position", range(len(labels)),
        format_func=lambda i: labels[i], key="sq_s"
    )
    sel = enriched[si]

    ot = st.radio(
        "Order Type", ["Market", "Limit"],
        horizontal=True, key="sq_o"
    )
    pr = 0.0
    if ot == "Limit":
        pr = st.number_input(
            "Limit Price", value=float(sel["_ltp"]),
            min_value=0.0, step=0.05, key="sq_p"
        )
    sq = st.slider("Quantity", 1, sel["_q"], sel["_q"], key="sq_q")

    order_in_progress = st.session_state.get(
        "_order_in_progress", False
    )

    if st.button(
        f"🔄 {sel['_close'].upper()} {sq} units",
        type="primary",
        disabled=order_in_progress
    ):
        st.session_state._order_in_progress = True
        try:
            with st.spinner("Squaring off..."):
                r = client.square_off(
                    sel.get("stock_code"),
                    sel.get("exchange_code"),
                    sel.get("expiry_date"),
                    safe_int(sel.get("strike_price")),
                    C.normalize_option_type(sel.get("right", "")),
                    sq, sel["_pt"], ot.lower(),
                    pr if ot == "Limit" else 0.0
                )
                if r["success"]:
                    st.success("✅ Squared off!")
                    order_id = APIResponse(r).get("order_id", "?")

                    _db.log_trade(
                        stock_code=sel.get("stock_code", ""),
                        exchange=sel.get("exchange_code", ""),
                        strike=safe_int(sel.get("strike_price", 0)),
                        option_type=C.normalize_option_type(
                            sel.get("right", "")
                        ),
                        expiry=sel.get("expiry_date", ""),
                        action=sel["_close"],
                        quantity=sq,
                        price=pr,
                        order_type=ot.lower(),
                        trade_id=str(order_id),
                        notes="Square off"
                    )
                    _db.log_activity(
                        "SQUARE_OFF",
                        f"{sel.get('stock_code')} "
                        f"{sel.get('strike_price')}"
                    )
                    SessionState.log_activity(
                        "SqOff", str(sel.get("strike_price"))
                    )

                    monitor = st.session_state.get("risk_monitor")
                    if monitor:
                        pid = (
                            f"{sel.get('stock_code')}_"
                            f"{sel.get('strike_price')}_"
                            f"{C.normalize_option_type(sel.get('right', ''))}"
                        )
                        monitor.remove_position(pid)

                    invalidate_trading_caches()
                    time.sleep(1)
                    st.session_state._order_in_progress = False
                    st.rerun()

                elif r.get("error_code") == "DUPLICATE_ORDER":
                    st.warning(f"⚠️ {r['message']}")
                else:
                    st.error(f"❌ {r.get('message')}")
        finally:
            st.session_state._order_in_progress = False


# ═══════════════════════════════════════════════════════════════
# PAGE: ORDERS & TRADES
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_orders_trades():
    st.markdown(
        '<h1 class="page-header">📋 Orders & Trades</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return

    t1, t2, t3, t4 = st.tabs([
        "📋 Orders", "📊 Trades",
        "📝 Activity", "💾 Trade History"
    ])

    with t1:
        c1, c2, c3 = st.columns(3)
        with c1:
            exch = st.selectbox(
                "Exchange", ["All", "NFO", "BFO"], key="o_e"
            )
        with c2:
            fd = st.date_input(
                "From",
                value=date.today() - timedelta(days=7),
                key="o_f"
            )
        with c3:
            td = st.date_input("To", value=date.today(), key="o_t")
        try:
            validate_date_range(fd, td)
        except ValueError as e:
            st.error(str(e))
            return

        with st.spinner("Loading orders..."):
            r = client.get_order_list(
                "" if exch == "All" else exch,
                fd.strftime("%Y-%m-%d"),
                td.strftime("%Y-%m-%d")
            )
        if r["success"]:
            items = APIResponse(r).items
            if items:
                st.dataframe(
                    pd.DataFrame(items),
                    height=400, hide_index=True
                )
            else:
                empty_state("📭", "No orders found")
        else:
            st.error(f"❌ {r.get('message')}")

    with t2:
        with st.spinner("Loading trades..."):
            r = client.get_trade_list(
                from_date=fd.strftime("%Y-%m-%d"),
                to_date=td.strftime("%Y-%m-%d")
            )
        if r["success"]:
            items = APIResponse(r).items
            if items:
                st.dataframe(
                    pd.DataFrame(items),
                    height=400, hide_index=True
                )
            else:
                empty_state("📭", "No trades found")
        else:
            st.error(f"❌ {r.get('message')}")

    with t3:
        session_log = SessionState.get_activity_log()
        db_log = _db.get_activities(limit=50)
        merged = []
        seen = set()
        for entry in session_log:
            key = (
                f"{entry.get('time', '')}_"
                f"{entry.get('action', '')}"
            )
            if key not in seen:
                seen.add(key)
                merged.append(entry)
        for entry in db_log:
            key = (
                f"{entry.get('timestamp', '')[:8]}_"
                f"{entry.get('action', '')}"
            )
            if key not in seen:
                seen.add(key)
                merged.append({
                    "time": entry.get("timestamp", "")[:19],
                    "action": entry.get("action", ""),
                    "detail": entry.get("detail", "")
                })
        if merged:
            st.dataframe(
                pd.DataFrame(merged[:50]), hide_index=True
            )
        else:
            empty_state("📝", "No activity yet")

    with t4:
        st.markdown("### Persistent Trade History")
        trades = _db.get_trades(limit=100)
        if trades:
            st.dataframe(pd.DataFrame(trades), hide_index=True)
        else:
            empty_state(
                "💾", "No trades recorded yet",
                "Trades are saved automatically when you place orders"
            )


# ═══════════════════════════════════════════════════════════════
# PAGE: POSITIONS
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_positions():
    st.markdown(
        '<h1 class="page-header">📍 Positions</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return
    if st.button("🔄 Refresh"):
        invalidate_trading_caches()
        st.rerun()

    all_pos = get_cached_positions(client)
    if all_pos is None:
        st.error("❌ Failed to load positions")
        return
    opt_pos, eq_pos = split_positions(all_pos)

    t1, t2 = st.tabs([
        f"Options ({len(opt_pos)})",
        f"Equity ({len(eq_pos)})"
    ])

    with t1:
        if not opt_pos:
            empty_state("📭", "No option positions")
        else:
            total = 0.0
            rows = []
            for p in opt_pos:
                pt = detect_position_type(p)
                avg = safe_float(p.get("average_price", 0))
                ltp = safe_float(p.get("ltp", avg))
                q = abs(safe_int(p.get("quantity", 0)))
                pnl = calculate_pnl(pt, avg, ltp, q)
                total += pnl
                rows.append({
                    "Instrument": C.api_code_to_display(
                        p.get("stock_code", "")
                    ),
                    "Strike": p.get("strike_price"),
                    "Type": C.normalize_option_type(
                        p.get("right", "")
                    ),
                    "Position": pt.upper(),
                    "Qty": q,
                    "Avg": f"₹{avg:.2f}",
                    "LTP": f"₹{ltp:.2f}",
                    "P&L": f"₹{pnl:+,.2f}",
                    "Expiry": format_expiry(
                        p.get("expiry_date", "")
                    ),
                    "Close": get_closing_action(pt).upper()
                })
            st.metric("Options P&L", format_currency(total))
            st.dataframe(pd.DataFrame(rows), hide_index=True)

    with t2:
        if not eq_pos:
            empty_state("📦", "No equity positions")
        else:
            eq_rows = []
            for p in eq_pos:
                eq_rows.append({
                    "Stock": p.get("stock_code", ""),
                    "Qty": safe_int(p.get("quantity", 0)),
                    "Avg": f"₹{safe_float(p.get('average_price', 0)):.2f}",
                    "LTP": f"₹{safe_float(p.get('ltp', 0)):.2f}",
                    "P&L": f"₹{safe_float(p.get('pnl', 0)):+,.2f}",
                    "Type": p.get("product_type", "")
                })
            total_eq = sum(
                safe_float(p.get("pnl", 0)) for p in eq_pos
            )
            st.metric("Equity P&L", format_currency(total_eq))
            st.dataframe(pd.DataFrame(eq_rows), hide_index=True)


# ═══════════════════════════════════════════════════════════════
# PAGE: STRATEGY BUILDER
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_strategy_builder():
    st.markdown(
        '<h1 class="page-header">🎯 Strategy Builder</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return

    c1, c2 = st.columns([1, 2])

    with c1:
        st.markdown("### Configuration")
        sname = st.selectbox(
            "Strategy",
            list(PREDEFINED_STRATEGIES.keys()),
            key="sb_s"
        )
        inst = st.selectbox(
            "Instrument",
            list(C.INSTRUMENTS.keys()),
            key="sb_i"
        )
        cfg = C.get_instrument(inst)
        expiry = st.selectbox(
            "Expiry", C.get_next_expiries(inst, 5),
            format_func=format_expiry, key="sb_e"
        )
        mid = (cfg.min_strike + cfg.max_strike) // 2
        mid = round(mid / cfg.strike_gap) * cfg.strike_gap
        atm = st.number_input(
            "ATM Strike",
            min_value=cfg.min_strike,
            max_value=cfg.max_strike,
            value=mid,
            step=cfg.strike_gap,
            key="sb_a"
        )
        lots = st.number_input(
            "Lots/Leg", min_value=1, max_value=50,
            value=1, key="sb_l"
        )
        build = st.button("🔧 Build Strategy", type="primary")

    with c2:
        info = PREDEFINED_STRATEGIES[sname]
        st.markdown(f"### {sname}")
        st.markdown(info["description"])
        st.markdown(
            f"**View:** {info['view']} | "
            f"**Risk:** {info['risk']} | "
            f"**Reward:** {info['reward']}"
        )

        if build:
            try:
                legs = generate_strategy_legs(
                    sname, atm, cfg.strike_gap,
                    cfg.lot_size, lots
                )
                st.session_state.strat_legs = legs
                st.session_state.strat_cfg = cfg
                st.session_state.strat_expiry = expiry
                st.success(f"✅ Built {len(legs)} legs")
            except Exception as e:
                st.error(f"❌ {e}")

        if st.session_state.get("strat_legs"):
            legs = st.session_state.strat_legs
            st.markdown("### Legs")
            for i, leg in enumerate(legs):
                emoji = "🟢" if leg.action == "buy" else "🔴"
                st.markdown(
                    f"**Leg {i + 1}:** {emoji} "
                    f"{leg.action.upper()} {leg.strike} "
                    f"{leg.option_type} × {leg.quantity}"
                )

            st.markdown("---")
            if st.button("📊 Fetch Quotes & Analyze"):
                scfg = st.session_state.get("strat_cfg", cfg)
                sexpiry = st.session_state.get(
                    "strat_expiry", expiry
                )
                with st.spinner("Fetching quotes for all legs..."):
                    for leg in legs:
                        try:
                            r = client.get_quotes(
                                scfg.api_code, scfg.exchange,
                                sexpiry, leg.strike,
                                leg.option_type
                            )
                            if r["success"]:
                                items = APIResponse(r).items
                                if items:
                                    leg.premium = safe_float(
                                        items[0].get("ltp", 0)
                                    )
                        except Exception:
                            pass
                    st.session_state.strat_legs = legs

                metrics = calculate_strategy_metrics(legs)
                st.markdown("### Analysis")
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric(
                    "Net Premium",
                    format_currency(metrics["net_premium"])
                )
                mc2.metric(
                    "Max Profit",
                    format_currency(metrics["max_profit"])
                )
                mc3.metric(
                    "Max Loss",
                    format_currency(metrics["max_loss"])
                )
                if metrics["breakevens"]:
                    st.info(
                        f"Breakevens: "
                        f"{', '.join(str(int(b)) for b in metrics['breakevens'])}"
                    )

                payoff_df = generate_payoff_data(
                    legs, atm, scfg.strike_gap
                )
                if payoff_df is not None:
                    st.markdown("### Payoff Diagram")
                    st.line_chart(
                        payoff_df.set_index("Underlying")
                    )


# ═══════════════════════════════════════════════════════════════
# PAGE: ANALYTICS
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_analytics():
    st.markdown(
        '<h1 class="page-header">📈 Analytics</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return

    t1, t2, t3 = st.tabs([
        "📊 Portfolio Greeks", "💰 Margin", "📈 Performance"
    ])

    with t1:
        all_pos = get_cached_positions(client)
        if all_pos is None:
            st.error("❌ Failed")
            return
        opt_pos, _ = split_positions(all_pos)
        if not opt_pos:
            empty_state(
                "📊", "No options for Greeks calculation"
            )
            return

        st.markdown("### Portfolio Greeks")
        spot_prices = fetch_spot_prices(client, opt_pos)

        if spot_prices:
            spot_display = ", ".join(
                f"{C.api_code_to_display(k)}: ₹{v:,.0f}"
                for k, v in spot_prices.items()
            )
            st.caption(f"Spot prices: {spot_display}")
        else:
            st.warning(
                "⚠️ Could not fetch spot prices. "
                "Greeks will use ATM estimates."
            )

        rows = []
        for p in opt_pos:
            pt = detect_position_type(p)
            qty = abs(safe_int(p.get("quantity", 0)))
            strike = safe_float(p.get("strike_price", 0))
            ltp = safe_float(p.get("ltp", 0))
            ot = C.normalize_option_type(p.get("right", ""))
            exp = p.get("expiry_date", "")
            stock = p.get("stock_code", "")
            multiplier = -1 if pt == "short" else 1

            spot = spot_prices.get(stock, 0)
            spot_source = "API"
            if spot <= 0:
                spot = strike
                spot_source = "≈strike"

            try:
                dte = (
                    calculate_days_to_expiry(exp)
                    if exp else 30
                )
                tte = max(dte / C.DAYS_PER_YEAR, 0.001)
                if ltp > 0 and spot > 0:
                    iv = estimate_implied_volatility(
                        ltp, spot, strike, tte, ot
                    )
                else:
                    iv = 0.20
                g = calculate_greeks(spot, strike, tte, iv, ot)
                for k in g:
                    g[k] = g[k] * multiplier * qty
            except Exception:
                g = {
                    'delta': 0, 'gamma': 0,
                    'theta': 0, 'vega': 0, 'rho': 0
                }
                iv = 0.0

            pnl = calculate_pnl(
                pt,
                safe_float(p.get("average_price", 0)),
                ltp, qty
            )

            rows.append({
                "Position": C.api_code_to_display(stock),
                "Strike": int(strike),
                "Type": ot,
                "Dir": pt.upper(),
                "Qty": qty,
                "Spot": f"₹{spot:,.0f} ({spot_source})",
                "IV": f"{iv * 100:.1f}%",
                "Delta": f"{g['delta']:+.2f}",
                "Gamma": f"{g['gamma']:+.4f}",
                "Theta": f"{g['theta']:+.2f}",
                "Vega": f"{g['vega']:+.2f}",
                "P&L": f"₹{pnl:+,.2f}"
            })

        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True)

            agg = {k: 0.0 for k in ['delta', 'gamma', 'theta', 'vega']}
            for r in rows:
                for k in agg:
                    col_name = k.capitalize()
                    try:
                        agg[k] += float(
                            r[col_name].replace('+', '')
                        )
                    except (ValueError, KeyError):
                        pass

            ac1, ac2, ac3, ac4 = st.columns(4)
            ac1.metric("Net Delta", f"{agg['delta']:+.2f}")
            ac2.metric("Net Gamma", f"{agg['gamma']:+.4f}")
            ac3.metric(
                "Net Theta", f"{agg['theta']:+.2f}/day"
            )
            ac4.metric("Net Vega", f"{agg['vega']:+.2f}")

    with t2:
        st.markdown("### Margin Analysis")
        funds = get_cached_funds(client)
        if funds:
            c1, c2 = st.columns(2)
            with c1:
                st.metric(
                    "Total Balance",
                    format_currency(funds["total_balance"])
                )
                st.metric(
                    "F&O Allocated",
                    format_currency(funds["allocated_fno"])
                )
                st.metric(
                    "Equity Allocated",
                    format_currency(funds["allocated_equity"])
                )
            with c2:
                st.metric(
                    "Unallocated",
                    format_currency(funds["unallocated"])
                )
                st.metric(
                    "Blocked F&O",
                    format_currency(funds["block_fno"])
                )
                util = (
                    funds["allocated_fno"]
                    / funds["total_balance"] * 100
                    if funds["total_balance"] > 0 else 0
                )
                st.metric("Utilization", f"{util:.1f}%")
                if util > 80:
                    st.warning("⚠️ High margin utilization!")

            chart_data = pd.DataFrame({
                "Category": [
                    "F&O", "Equity", "Unallocated", "Blocked"
                ],
                "Amount": [
                    funds["allocated_fno"],
                    funds["allocated_equity"],
                    funds["unallocated"],
                    funds["block_fno"]
                ]
            })
            chart_data = chart_data[chart_data["Amount"] > 0]
            if not chart_data.empty:
                st.bar_chart(chart_data.set_index("Category"))

    with t3:
        st.markdown("### Performance")
        activity = SessionState.get_activity_log()
        trades_session = [
            a for a in activity
            if a["action"] in ("Sell", "SqOff")
        ]
        st.write(f"**Session actions:** {len(activity)}")
        st.write(f"**Session trades:** {len(trades_session)}")

        summary = _db.get_trade_summary()
        if summary and summary.get("total", 0) > 0:
            st.markdown("---")
            st.markdown("#### All-Time (Persistent)")
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("Total Trades", summary.get("total", 0))
            pc2.metric(
                "Premium Sold",
                format_currency(summary.get("sold", 0))
            )
            pc3.metric(
                "Premium Bought",
                format_currency(summary.get("bought", 0))
            )
            net = (
                (summary.get("sold", 0) or 0)
                - (summary.get("bought", 0) or 0)
            )
            st.metric("Net Premium", format_currency(net))

        recent = _db.get_activities(limit=20)
        if recent:
            st.markdown("---")
            st.markdown("#### Recent Activity (Persistent)")
            st.dataframe(
                pd.DataFrame(recent), hide_index=True
            )


# ═══════════════════════════════════════════════════════════════
# PAGE: RISK MONITOR
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_risk_monitor():
    st.markdown(
        '<h1 class="page-header">🛡️ Risk Monitor</h1>',
        unsafe_allow_html=True
    )
    client = get_client()
    if not client:
        return

    if "risk_monitor" not in st.session_state:
        st.session_state.risk_monitor = RiskMonitor(
            api_client=client, poll_interval=15.0
        )
    monitor: RiskMonitor = st.session_state.risk_monitor

    # ── Controls ──────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        if monitor.is_running():
            st.success("🟢 Monitor Running")
            if st.button("⏹️ Stop Monitor"):
                monitor.stop()
                st.rerun()
        else:
            st.warning("🔴 Monitor Stopped")
            if st.button("▶️ Start Monitor", type="primary"):
                monitor.start()
                st.rerun()
    with c2:
        st.metric(
            "Monitored Positions",
            len(monitor.get_monitored_summary())
        )
    with c3:
        st.metric(
            "Alert History",
            len(monitor.get_alert_history())
        )

    st.markdown("---")
    tab1, tab2, tab3 = st.tabs([
        "📍 Add Positions",
        "⚙️ Configure Stops",
        "🚨 Alert History"
    ])

    # ── Tab 1: Add Positions ──────────────────────────────
    with tab1:
        st.markdown("### Register Positions for Monitoring")
        all_pos = get_cached_positions(client)
        if all_pos is None:
            st.error("❌ Cannot load positions")
            return
        opt_pos, _ = split_positions(all_pos)

        if not opt_pos:
            empty_state("📭", "No option positions to monitor")
        else:
            already = {
                m["id"] for m in monitor.get_monitored_summary()
            }

            for p in opt_pos:
                stock = p.get("stock_code", "")
                strike_val = safe_int(p.get("strike_price", 0))
                ot = C.normalize_option_type(p.get("right", ""))
                pt = detect_position_type(p)
                qty = abs(safe_int(p.get("quantity", 0)))
                avg = safe_float(p.get("average_price", 0))
                pid = f"{stock}_{strike_val}_{ot}"

                label = (
                    f"{C.api_code_to_display(stock)} "
                    f"{strike_val} {ot} "
                    f"({pt.upper()} x{qty})"
                )

                if pid in already:
                    st.markdown(
                        f"✅ **{label}** — already monitored"
                    )
                else:
                    if st.button(
                        f"➕ Monitor: {label}",
                        key=f"add_{pid}"
                    ):
                        monitor.add_position(
                            position_id=pid,
                            stock_code=stock,
                            exchange=p.get("exchange_code", ""),
                            expiry=p.get("expiry_date", ""),
                            strike=strike_val,
                            option_type=ot,
                            position_type=pt,
                            quantity=qty,
                            avg_price=avg
                        )
                        _db.log_activity(
                            "MONITOR_ADD",
                            f"Added {pid} to risk monitor"
                        )
                        st.success(f"✅ Now monitoring {label}")
                        st.rerun()

    # ── Tab 2: Configure Stops ────────────────────────────
    with tab2:
        st.markdown("### Configure Stop-Losses")
        monitored = monitor.get_monitored_summary()

        if not monitored:
            empty_state(
                "⚙️", "No positions being monitored",
                "Add positions in the first tab"
            )
        else:
            for m in monitored:
                status_icon = (
                    "🔴" if m["triggered"] else "🟢"
                )
                expander_label = (
                    f"{status_icon} "
                    f"{C.api_code_to_display(m['stock'])} "
                    f"{m['strike']} {m['type']} "
                    f"({m['pos'].upper()}) — "
                    f"Current: ₹{m['current']:.2f}"
                )

                with st.expander(expander_label):
                    sc1, sc2 = st.columns(2)

                    with sc1:
                        st.markdown("**Fixed Stop-Loss**")
                        current_stop = m.get("stop")
                        default_stop = (
                            current_stop
                            if current_stop
                            else m["avg"] * 1.5
                        )
                        stop_price = st.number_input(
                            "Stop Price",
                            value=float(default_stop),
                            min_value=0.01,
                            step=0.5,
                            key=f"stop_{m['id']}"
                        )
                        if st.button(
                            "Set Fixed Stop",
                            key=f"set_stop_{m['id']}"
                        ):
                            monitor.set_stop_loss(
                                m["id"], stop_price
                            )
                            _db.log_activity(
                                "STOP_SET",
                                f"Fixed stop ₹{stop_price:.2f} "
                                f"on {m['id']}"
                            )
                            st.success(
                                f"✅ Stop set at "
                                f"₹{stop_price:.2f}"
                            )

                    with sc2:
                        st.markdown("**Trailing Stop-Loss**")
                        trail_pct = st.slider(
                            "Trail %",
                            min_value=10,
                            max_value=200,
                            value=50,
                            step=5,
                            key=f"trail_{m['id']}"
                        )
                        if st.button(
                            "Set Trailing Stop",
                            key=f"set_trail_{m['id']}"
                        ):
                            monitor.set_trailing_stop(
                                m["id"],
                                trail_pct / 100.0
                            )
                            _db.log_activity(
                                "TRAIL_SET",
                                f"Trail {trail_pct}% "
                                f"on {m['id']}"
                            )
                            st.success(
                                f"✅ Trailing stop set "
                                f"at {trail_pct}%"
                            )

                    st.markdown("---")
                    if m.get("stop"):
                        st.caption(
                            f"Current fixed stop: "
                            f"₹{m['stop']:.2f}"
                        )
                    if m.get("trail_pct"):
                        st.caption(
                            f"Current trailing: "
                            f"{m['trail_pct'] * 100:.0f}%"
                        )
                    if m.get("triggered"):
                        st.error(
                            "🚨 STOP HAS BEEN TRIGGERED"
                        )

                    if st.button(
                        "🗑️ Remove from Monitor",
                        key=f"rm_{m['id']}"
                    ):
                        monitor.remove_position(m["id"])
                        st.rerun()

    # ── Tab 3: Alert History ──────────────────────────────
    with tab3:
        st.markdown("### Alert History")
        history = monitor.get_alert_history()
        if history:
            alert_rows = [{
                "Time": a.timestamp,
                "Level": a.level,
                "Category": a.category,
                "Message": a.message,
                "Position": a.position_id
            } for a in history]
            st.dataframe(
                pd.DataFrame(alert_rows), hide_index=True
            )
        else:
            empty_state(
                "🔔", "No alerts yet",
                "Alerts appear here when stop-losses "
                "are triggered"
            )

        db_alerts = _db.get_activities(limit=20)
        alert_activities = [
            a for a in db_alerts
            if a.get("action", "").startswith(
                ("STOP_", "TRAIL_", "MONITOR_")
            )
        ]
        if alert_activities:
            st.markdown("---")
            st.markdown(
                "#### Risk Activity Log (Persistent)"
            )
            st.dataframe(
                pd.DataFrame(alert_activities),
                hide_index=True
            )


# ═══════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════

PAGE_FN = {
    "Dashboard": page_dashboard,
    "Option Chain": page_option_chain,
    "Sell Options": page_sell_options,
    "Square Off": page_square_off,
    "Orders & Trades": page_orders_trades,
    "Positions": page_positions,
    "Strategy Builder": page_strategy_builder,
    "Analytics": page_analytics,
    "Risk Monitor": page_risk_monitor,
}


def main():
    try:
        SessionState.initialize()
        render_sidebar()
        render_alert_banner()
        st.markdown("---")

        page = SessionState.get_current_page()

        if page in AUTH_PAGES and not SessionState.is_authenticated():
            st.warning("🔒 Login required")
            st.info("👈 Use the sidebar to connect")
            return

        if (
            SessionState.is_authenticated()
            and SessionState.is_session_expired()
        ):
            st.error("🔴 Session expired. Please reconnect.")
            if st.button("🔄 Reconnect", type="primary"):
                monitor = st.session_state.get("risk_monitor")
                if monitor:
                    monitor.stop()
                SessionState.set_authentication(False, None)
                SessionState.navigate_to("Dashboard")
                st.rerun()
            return

        PAGE_FN.get(page, page_dashboard)()

    except Exception as e:
        log.critical(f"Fatal: {e}", exc_info=True)
        st.error(
            "❌ Critical error. Please refresh the page."
        )
        if st.session_state.get("debug_mode"):
            st.exception(e)


if __name__ == "__main__":
    main()
