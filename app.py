"""
Breeze Options Trader v7.0 — Main Application
Streamlit 1.54+ fully compatible. Zero deprecation warnings.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from functools import wraps
import time, logging, traceback
from typing import Optional, Dict, List, Any, Callable

import app_config as C
from helpers import (
    APIResponse, safe_int, safe_float, safe_str, parse_funds,
    detect_position_type, get_closing_action, calculate_pnl,
    calculate_unrealized_pnl, process_option_chain, create_pivot_table,
    calculate_pcr, calculate_max_pain, estimate_atm_strike,
    add_greeks_to_chain, get_market_status, format_currency,
    format_expiry, calculate_days_to_expiry
)
from session_manager import Credentials, SessionState, CacheManager, Notifications
from breeze_api import BreezeAPIClient
from validators import OrderRequest, validate_date_range
from analytics import calculate_greeks, calculate_portfolio_greeks
from strategies import (
    StrategyLeg, PREDEFINED_STRATEGIES, generate_strategy_legs,
    calculate_strategy_metrics, generate_payoff_data
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Breeze Options Trader", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""<style>
    .main-header{font-size:2.5rem;font-weight:700;background:linear-gradient(135deg,#1f77b4,#2ecc71);-webkit-background-clip:text;-webkit-text-fill-color:transparent;text-align:center;padding:1rem 0}
    .page-header{font-size:2rem;font-weight:700;color:#1f77b4;border-bottom:4px solid #1f77b4;padding-bottom:.5rem;margin-bottom:1.5rem}
    .section-header{font-size:1.5rem;font-weight:600;color:#2c3e50;margin:1.5rem 0 1rem}
    .status-connected{background:#d4edda;color:#155724;padding:6px 14px;border-radius:16px;font-weight:600;display:inline-block}
    .market-open{color:#28a745;font-weight:700}.market-closed{color:#dc3545;font-weight:700}.market-pre{color:#ffc107;font-weight:700}
    .profit{color:#28a745!important;font-weight:700}.loss{color:#dc3545!important;font-weight:700}
    .info-box{background:#e7f3ff;border-left:5px solid #2196F3;padding:1rem;margin:1rem 0;border-radius:0 8px 8px 0}
    .success-box{background:#d4edda;border-left:5px solid #28a745;padding:1rem;margin:1rem 0;border-radius:0 8px 8px 0}
    .danger-box{background:#f8d7da;border-left:5px solid #dc3545;padding:1rem;margin:1rem 0;border-radius:0 8px 8px 0}
    .metric-card{background:#f8f9fa;padding:1.25rem;border-radius:8px;border:1px solid #dee2e6}
    .empty-state{text-align:center;padding:3rem 1rem;color:#6c757d}.empty-state-icon{font-size:4rem;margin-bottom:1rem;opacity:.5}
    .leg-card{background:#fff;border:2px solid #e0e0e0;border-radius:8px;padding:1rem;margin:.5rem 0}
    .leg-card.buy{border-left:4px solid #28a745}.leg-card.sell{border-left:4px solid #dc3545}
    #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
</style>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════

PAGES = ["Dashboard", "Option Chain", "Sell Options", "Square Off", "Orders & Trades", "Positions", "Strategy Builder", "Analytics"]
ICONS = {"Dashboard":"🏠","Option Chain":"📊","Sell Options":"💰","Square Off":"🔄","Orders & Trades":"📋","Positions":"📍","Strategy Builder":"🎯","Analytics":"📈"}
AUTH_PAGES = set(PAGES[1:])

# ═══════════════════════════════════════════════════════════════════
# DECORATORS
# ═══════════════════════════════════════════════════════════════════

def error_handler(f):
    @wraps(f)
    def w(*a, **k):
        try: return f(*a, **k)
        except Exception as e:
            log.error(f"{f.__name__}: {e}", exc_info=True)
            st.error(f"❌ {e}")
            if st.session_state.get("debug_mode"): st.exception(e)
    return w

def require_auth(f):
    @wraps(f)
    def w(*a, **k):
        if not SessionState.is_authenticated():
            st.warning("🔒 Please login"); return
        return f(*a, **k)
    return w

def check_session(f):
    @wraps(f)
    def w(*a, **k):
        if SessionState.is_authenticated() and SessionState.is_session_expired():
            st.error("🔴 Session expired")
            if st.button("🔄 Reconnect", type="primary"):
                SessionState.set_authentication(False, None); SessionState.navigate_to("Dashboard"); st.rerun()
            return
        return f(*a, **k)
    return w

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def empty_state(icon, msg, sub="", btn=None):
    st.markdown(f'<div class="empty-state"><div class="empty-state-icon">{icon}</div><h3>{msg}</h3><p>{sub}</p></div>', unsafe_allow_html=True)
    if btn:
        c1,c2,c3 = st.columns([1,2,1])
        with c2:
            if st.button(btn.get("label","Go"), type=btn.get("type","secondary")):
                SessionState.navigate_to(btn["page"]); st.rerun()

def get_client():
    c = SessionState.get_client()
    if not c or not c.connected:
        st.error("❌ Not connected"); return None
    return c

def get_cached_funds(client):
    """Fetch funds with caching."""
    cached = CacheManager.get("funds", "funds")
    if cached: return cached
    resp = client.get_funds()
    if resp["success"]:
        funds = parse_funds(resp)
        CacheManager.set("funds", funds, "funds", C.FUNDS_CACHE_TTL_SECONDS)
        return funds
    return None

def get_cached_positions(client):
    """Fetch positions with caching."""
    cached = CacheManager.get("positions", "positions")
    if cached is not None: return cached
    resp = client.get_positions()
    if resp["success"]:
        items = APIResponse(resp).items
        CacheManager.set("positions", items, "positions", C.POSITION_CACHE_TTL_SECONDS)
        return items
    return None

def split_positions(all_pos):
    """Split into option and equity positions."""
    options, equities = [], []
    for p in all_pos:
        qty = safe_int(p.get("quantity", 0))
        if qty == 0: continue
        if C.is_option_position(p): options.append(p)
        elif C.is_equity_position(p): equities.append(p)
    return options, equities

# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown("## 📈 Breeze Trader")
        st.markdown("---")
        # Navigation
        avail = PAGES if SessionState.is_authenticated() else ["Dashboard"]
        cur = SessionState.get_current_page()
        if cur not in avail: cur = "Dashboard"; SessionState.navigate_to(cur)
        try: idx = avail.index(cur)
        except ValueError: idx = 0
        sel = st.radio("Nav", avail, index=idx, format_func=lambda p: f"{ICONS.get(p,'')} {p}", label_visibility="collapsed", key="nav")
        if sel != cur: SessionState.navigate_to(sel); st.rerun()
        st.markdown("---")

        if SessionState.is_authenticated():
            st.markdown('<span class="status-connected">✅ Connected</span>', unsafe_allow_html=True)
            client = SessionState.get_client()
            if client:
                name = st.session_state.get("user_name", "Trader")
                st.markdown(f"**👤 {name}**")
                dur = SessionState.get_login_duration()
                if dur: st.caption(f"⏱️ {dur}")
            if SessionState.is_session_expired(): st.error("🔴 Expired")
            elif SessionState.is_session_stale(): st.warning("⚠️ Stale")
            st.markdown("---")
            ms = get_market_status()
            css = "market-open" if "Open" in ms else "market-pre" if "Pre" in ms else "market-closed"
            st.markdown(f'<p class="{css}">{ms}</p>', unsafe_allow_html=True)
            # Margin
            if client:
                funds = get_cached_funds(client)
                if funds: st.metric("Unallocated", format_currency(funds["unallocated"]))
            st.markdown("---")
            if st.button("🔓 Disconnect"):
                SessionState.set_authentication(False, None); Credentials.clear_runtime_credentials()
                CacheManager.clear_all(); SessionState.navigate_to("Dashboard"); st.rerun()
        else:
            has = Credentials.has_stored_credentials()
            if has:
                st.markdown("### 🔑 Daily Login")
                st.markdown('<div class="success-box">✅ API keys loaded. Enter session token.</div>', unsafe_allow_html=True)
                with st.form("quick_login"):
                    tok = st.text_input("Session Token", type="password", placeholder="Paste from ICICI")
                    if st.form_submit_button("🔑 Connect", type="primary"):
                        if tok and len(tok.strip()) >= 10:
                            k, s, _ = Credentials.get_all_credentials()
                            do_login(k, s, tok.strip())
                        else: st.warning("Enter valid token")
            else:
                st.markdown("### 🔐 Login")
                with st.form("full_login"):
                    k, s, _ = Credentials.get_all_credentials()
                    nk = st.text_input("API Key", value=k, type="password")
                    ns = st.text_input("API Secret", value=s, type="password")
                    tok = st.text_input("Session Token", type="password")
                    if st.form_submit_button("🔑 Connect", type="primary"):
                        if all([nk, ns, tok]): do_login(nk.strip(), ns.strip(), tok.strip())
                        else: st.warning("Fill all fields")

        st.markdown("---")
        with st.expander("⚙️ Settings"):
            st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="selected_instrument")
            st.session_state.debug_mode = st.checkbox("Debug", value=st.session_state.get("debug_mode", False))
        st.caption("v7.0.0")


def do_login(api_key, api_secret, token):
    with st.spinner("Connecting..."):
        try:
            client = BreezeAPIClient(api_key, api_secret)
            resp = client.connect(token)
            if resp["success"]:
                Credentials.save_runtime_credentials(api_key, api_secret, token)
                SessionState.set_authentication(True, client)
                SessionState.log_activity("Login", "Connected")
                st.session_state.user_name = "Trader"
                Notifications.success("Connected!"); time.sleep(0.5); st.rerun()
            else:
                st.error(f"❌ {resp.get('message')}")
        except Exception as e:
            st.error(f"❌ {e}")

# ═══════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@error_handler
def page_dashboard():
    st.markdown('<h1 class="page-header">🏠 Dashboard</h1>', unsafe_allow_html=True)
    if not SessionState.is_authenticated():
        st.markdown("### Welcome to Breeze Options Trader")
        c1,c2,c3 = st.columns(3)
        with c1: st.markdown("📊 **Market Data** — Option chains, Greeks, OI")
        with c2: st.markdown("💰 **Trading** — Sell options, strategies")
        with c3: st.markdown("🛡️ **Risk** — P&L, margin, analytics")
        st.markdown("---")
        data = [{"Name":n,"Desc":c.description,"Exchange":c.exchange,"Lot":c.lot_size,"Gap":c.strike_gap} for n,c in C.INSTRUMENTS.items()]
        st.dataframe(pd.DataFrame(data), hide_index=True)
        st.info("👈 Login to start"); return

    client = get_client()
    if not client: return

    # Funds
    st.markdown('<h2 class="section-header">💰 Account</h2>', unsafe_allow_html=True)
    funds = get_cached_funds(client)
    if funds:
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total Balance", format_currency(funds["total_balance"]))
        c2.metric("Allocated F&O", format_currency(funds["allocated_fno"]))
        c3.metric("Unallocated", format_currency(funds["unallocated"]))
        util = funds["allocated_fno"] / funds["total_balance"] * 100 if funds["total_balance"] > 0 else 0
        c4.metric("Utilization", f"{util:.1f}%")

    # Positions
    all_pos = get_cached_positions(client)
    if all_pos is None: st.error("❌ Cannot load positions"); return
    opt_pos, eq_pos = split_positions(all_pos)

    st.markdown("---")
    tab1, tab2 = st.tabs([f"📍 Options ({len(opt_pos)})", f"📦 Equity ({len(eq_pos)})"])

    with tab1:
        if not opt_pos:
            empty_state("📭", "No option positions", "Sell options to start", {"label":"💰 Sell Options","page":"Sell Options","type":"primary"})
        else:
            total_pnl = 0.0; rows = []
            for p in opt_pos:
                qty = safe_int(p.get("quantity",0)); pt = detect_position_type(p)
                avg = safe_float(p.get("average_price",0)); ltp = safe_float(p.get("ltp",avg))
                pnl = calculate_pnl(pt, avg, ltp, abs(qty)); total_pnl += pnl
                rows.append({"Instrument": C.api_code_to_display(p.get("stock_code","")),
                    "Strike": p.get("strike_price"), "Type": C.normalize_option_type(p.get("right","")),
                    "Pos": pt.upper(), "Qty": abs(qty), "Avg": f"₹{avg:.2f}", "LTP": f"₹{ltp:.2f}",
                    "P&L": f"₹{pnl:+,.2f}"})
            if rows:
                c1,c2 = st.columns([3,1])
                with c1: st.dataframe(pd.DataFrame(rows), hide_index=True)
                with c2:
                    cl = "profit" if total_pnl >= 0 else "loss"
                    st.markdown(f'<div class="metric-card"><h4>P&L</h4><h2 class="{cl}">{format_currency(total_pnl)}</h2></div>', unsafe_allow_html=True)

    with tab2:
        if not eq_pos:
            empty_state("📦", "No equity positions", "")
        else:
            eq_rows = []
            for p in eq_pos:
                pnl_val = safe_float(p.get("pnl", 0))
                eq_rows.append({
                    "Stock": p.get("stock_code",""), "Qty": safe_int(p.get("quantity",0)),
                    "Avg": f"₹{safe_float(p.get('average_price',0)):.2f}",
                    "LTP": f"₹{safe_float(p.get('ltp',0)):.2f}",
                    "P&L": f"₹{pnl_val:+,.2f}",
                    "Type": p.get("product_type","")
                })
            st.dataframe(pd.DataFrame(eq_rows), hide_index=True)
            total_eq = sum(safe_float(p.get("pnl",0)) for p in eq_pos)
            st.metric("Total Equity P&L", format_currency(total_eq))

    st.markdown("---")
    st.markdown('<h2 class="section-header">⚡ Quick Actions</h2>', unsafe_allow_html=True)
    c1,c2,c3,c4 = st.columns(4)
    for col, (label, page) in zip([c1,c2,c3,c4], [("📊 Chain","Option Chain"),("💰 Sell","Sell Options"),("🔄 Square Off","Square Off"),("📋 Orders","Orders & Trades")]):
        with col:
            if st.button(label):
                SessionState.navigate_to(page); st.rerun()

# ═══════════════════════════════════════════════════════════════════
# OPTION CHAIN
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session
def page_option_chain():
    st.markdown('<h1 class="page-header">📊 Option Chain</h1>', unsafe_allow_html=True)
    client = get_client()
    if not client: return

    c1,c2,c3 = st.columns([2,2,1])
    with c1: inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="oc_inst")
    cfg = C.get_instrument(inst)
    with c2:
        expiries = C.get_next_expiries(inst, 5)
        if not expiries: st.error("No expiries"); return
        expiry = st.selectbox("Expiry", expiries, format_func=format_expiry, key="oc_exp")
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh = st.button("🔄 Refresh", key="oc_ref")

    c1,c2,c3 = st.columns([2,1,1])
    with c1: view = st.radio("View", ["Traditional","Flat","Calls","Puts"], horizontal=True, key="oc_v")
    with c2: n_strikes = st.slider("Strikes±", 5, 50, 15, key="oc_n")
    with c3: greeks = st.checkbox("Greeks", True, key="oc_g")

    ck = f"oc_{cfg.api_code}_{expiry}"
    if refresh: CacheManager.invalidate(ck, "option_chain"); st.rerun()

    df = CacheManager.get(ck, "option_chain")
    if df is not None:
        st.caption("📦 Cached")
    else:
        with st.spinner(f"Loading {inst}..."):
            resp = client.get_option_chain(cfg.api_code, cfg.exchange, expiry)
        if not resp["success"]: st.error(f"❌ {resp.get('message')}"); return
        df = process_option_chain(resp.get("data", {}))
        if df.empty: st.warning("No data"); return
        CacheManager.set(ck, df, "option_chain", C.OC_CACHE_TTL_SECONDS)
        SessionState.log_activity("Chain", f"{inst} {format_expiry(expiry)}")

    atm = estimate_atm_strike(df)
    pcr = calculate_pcr(df)
    mp = calculate_max_pain(df)
    dte = calculate_days_to_expiry(expiry)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("PCR", f"{pcr:.2f}", "Bullish" if pcr > 1 else "Bearish")
    c2.metric("Max Pain", f"{mp:,.0f}")
    c3.metric("ATM", f"{atm:,.0f}")
    c4.metric("DTE", dte)
    st.markdown("---")

    # Filter
    if "strike_price" in df.columns and atm > 0:
        strikes = sorted(df["strike_price"].unique())
        if strikes:
            ai = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm))
            filt = strikes[max(0,ai-n_strikes):min(len(strikes),ai+n_strikes+1)]
            ddf = df[df["strike_price"].isin(filt)].copy()
        else: ddf = df.copy()
    else: ddf = df.copy()

    if greeks and not ddf.empty:
        try: ddf = add_greeks_to_chain(ddf, atm, expiry)
        except Exception: pass

    if view == "Traditional":
        pv = create_pivot_table(ddf)
        if not pv.empty: st.dataframe(pv, height=600, hide_index=True)
    elif view == "Calls":
        st.dataframe(ddf[ddf["right"]=="Call"] if "right" in ddf.columns else ddf, height=600, hide_index=True)
    elif view == "Puts":
        st.dataframe(ddf[ddf["right"]=="Put"] if "right" in ddf.columns else ddf, height=600, hide_index=True)
    else:
        st.dataframe(ddf, height=600, hide_index=True)

    # OI Chart
    if "right" in ddf.columns and "open_interest" in ddf.columns:
        st.markdown("---")
        try:
            co = ddf[ddf["right"]=="Call"][["strike_price","open_interest"]].rename(columns={"open_interest":"Call OI"})
            po = ddf[ddf["right"]=="Put"][["strike_price","open_interest"]].rename(columns={"open_interest":"Put OI"})
            oi = pd.merge(co, po, on="strike_price", how="outer").fillna(0).sort_values("strike_price").set_index("strike_price")
            st.bar_chart(oi)
        except Exception: pass

# ═══════════════════════════════════════════════════════════════════
# SELL OPTIONS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session
def page_sell_options():
    st.markdown('<h1 class="page-header">💰 Sell Options</h1>', unsafe_allow_html=True)
    client = get_client()
    if not client: return

    c1,c2 = st.columns(2)
    with c1:
        inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="s_i")
        cfg = C.get_instrument(inst)
        expiry = st.selectbox("Expiry", C.get_next_expiries(inst,5), format_func=format_expiry, key="s_e")
        ot = st.radio("Type", ["CE (Call)","PE (Put)"], horizontal=True, key="s_t")
        oc = "CE" if "CE" in ot else "PE"
        default_s = cfg.min_strike + 10 * cfg.strike_gap
        strike = st.number_input("Strike", min_value=cfg.min_strike, max_value=cfg.max_strike, value=default_s, step=cfg.strike_gap, key="s_s")
        valid = C.validate_strike(inst, strike)
        if not valid: st.warning(f"Must be multiple of {cfg.strike_gap}")
        lots = st.number_input("Lots", min_value=1, max_value=C.MAX_LOTS_PER_ORDER, value=1, key="s_l")
        qty = lots * cfg.lot_size
        st.info(f"**Qty:** {qty:,} ({lots}×{cfg.lot_size})")
        otp = st.radio("Order", ["Market","Limit"], horizontal=True, key="s_o")
        lp = 0.0
        if otp == "Limit": lp = st.number_input("Price", min_value=0.0, step=0.05, key="s_p")

    with c2:
        if st.button("📊 Quote", disabled=not valid):
            with st.spinner("..."):
                r = client.get_quotes(cfg.api_code, cfg.exchange, expiry, int(strike), oc)
                if r["success"]:
                    items = APIResponse(r).items
                    if items:
                        q = items[0]; ltp = safe_float(q.get("ltp",0))
                        st.success(f"LTP: ₹{ltp:.2f}")
                        st.info(f"Premium: {format_currency(ltp * qty)}")
        if st.button("💰 Margin", disabled=not valid):
            with st.spinner("..."):
                r = client.get_margin(cfg.api_code, cfg.exchange, expiry, int(strike), oc, "sell", qty)
                if r["success"]:
                    m = safe_float(APIResponse(r).get("required_margin", 0))
                    st.success(f"Margin: {format_currency(m)}")

    st.markdown("---")
    st.markdown('<div class="danger-box"><b>⚠️ RISK:</b> Option selling has unlimited risk. Use stop-losses.</div>', unsafe_allow_html=True)
    ack = st.checkbox("✅ I accept the risks", key="s_ack")
    can = ack and valid and strike > 0 and (otp == "Market" or lp > 0)

    if st.button(f"🔴 SELL {qty:,} {inst} {strike} {oc}", type="primary", disabled=not can):
        with st.spinner("Placing..."):
            r = client.sell_call(cfg.api_code,cfg.exchange,expiry,int(strike),qty,otp.lower(),lp) if oc=="CE" else client.sell_put(cfg.api_code,cfg.exchange,expiry,int(strike),qty,otp.lower(),lp)
            if r["success"]:
                st.success(f"✅ Placed! ID: {APIResponse(r).get('order_id','?')}"); st.balloons()
                SessionState.log_activity("Sell", f"{inst} {strike} {oc}"); CacheManager.clear_all(); time.sleep(2); st.rerun()
            else: st.error(f"❌ {r.get('message')}")

# ═══════════════════════════════════════════════════════════════════
# SQUARE OFF
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session
def page_square_off():
    st.markdown('<h1 class="page-header">🔄 Square Off</h1>', unsafe_allow_html=True)
    client = get_client()
    if not client: return
    if st.button("🔄 Refresh"): CacheManager.clear_all("positions"); st.rerun()

    all_pos = get_cached_positions(client)
    if all_pos is None: st.error("❌ Load failed"); return
    opt_pos, _ = split_positions(all_pos)

    # Enrich
    enriched = []
    for p in opt_pos:
        pt = detect_position_type(p); avg = safe_float(p.get("average_price",0)); ltp = safe_float(p.get("ltp",avg))
        q = abs(safe_int(p.get("quantity",0))); pnl = calculate_pnl(pt, avg, ltp, q)
        enriched.append({**p, "_pt":pt, "_q":q, "_close":get_closing_action(pt), "_pnl":pnl, "_avg":avg, "_ltp":ltp})

    if not enriched:
        empty_state("📭","No positions","",{"label":"💰 Sell","page":"Sell Options","type":"primary"}); return

    total = sum(e["_pnl"] for e in enriched)
    st.metric("Total P&L", format_currency(total))
    rows = [{"#":i+1, "Inst":C.api_code_to_display(e.get("stock_code","")), "Strike":e.get("strike_price"),
             "Type":C.normalize_option_type(e.get("right","")), "Pos":e["_pt"].upper(), "Qty":e["_q"],
             "P&L":f"₹{e['_pnl']:+,.2f}", "Action":e["_close"].upper()} for i,e in enumerate(enriched)]
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    st.markdown("---")
    labels = [f"{C.api_code_to_display(e.get('stock_code',''))} {e.get('strike_price')} {C.normalize_option_type(e.get('right',''))}" for e in enriched]
    si = st.selectbox("Position", range(len(labels)), format_func=lambda i: labels[i], key="sq_s")
    sel = enriched[si]

    ot = st.radio("Order", ["Market","Limit"], horizontal=True, key="sq_o")
    pr = 0.0
    if ot == "Limit": pr = st.number_input("Price", value=float(sel["_ltp"]), key="sq_p")
    sq = st.slider("Qty", 1, sel["_q"], sel["_q"], key="sq_q")

    if st.button(f"🔄 {sel['_close'].upper()} {sq}", type="primary"):
        with st.spinner("..."):
            r = client.square_off(sel.get("stock_code"), sel.get("exchange_code"), sel.get("expiry_date"),
                safe_int(sel.get("strike_price")), C.normalize_option_type(sel.get("right","")),
                sq, sel["_pt"], ot.lower(), pr if ot=="Limit" else 0.0)
            if r["success"]:
                st.success("✅ Done!"); SessionState.log_activity("SqOff", str(sel.get("strike_price")))
                CacheManager.clear_all(); time.sleep(1); st.rerun()
            else: st.error(f"❌ {r.get('message')}")

# ═══════════════════════════════════════════════════════════════════
# ORDERS & TRADES
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session
def page_orders_trades():
    st.markdown('<h1 class="page-header">📋 Orders & Trades</h1>', unsafe_allow_html=True)
    client = get_client()
    if not client: return

    t1,t2,t3 = st.tabs(["📋 Orders","📊 Trades","📝 Activity"])

    with t1:
        c1,c2,c3 = st.columns(3)
        with c1: exch = st.selectbox("Exchange", ["All","NFO","BFO"], key="o_e")
        with c2: fd = st.date_input("From", value=date.today()-timedelta(days=7), key="o_f")
        with c3: td = st.date_input("To", value=date.today(), key="o_t")
        try: validate_date_range(fd, td)
        except ValueError as e: st.error(str(e)); return
        with st.spinner("Loading..."):
            r = client.get_order_list("" if exch=="All" else exch, fd.strftime("%Y-%m-%d"), td.strftime("%Y-%m-%d"))
        if r["success"]:
            items = APIResponse(r).items
            if items: st.dataframe(pd.DataFrame(items), height=400, hide_index=True)
            else: empty_state("📭","No orders","")

    with t2:
        with st.spinner("Loading..."):
            r = client.get_trade_list(from_date=fd.strftime("%Y-%m-%d"), to_date=td.strftime("%Y-%m-%d"))
        if r["success"]:
            items = APIResponse(r).items
            if items: st.dataframe(pd.DataFrame(items), height=400, hide_index=True)
            else: empty_state("📭","No trades","")

    with t3:
        log_data = SessionState.get_activity_log()
        if log_data: st.dataframe(pd.DataFrame(log_data), hide_index=True)
        else: empty_state("📝","No activity","")

# ═══════════════════════════════════════════════════════════════════
# POSITIONS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session
def page_positions():
    st.markdown('<h1 class="page-header">📍 Positions</h1>', unsafe_allow_html=True)
    client = get_client()
    if not client: return
    if st.button("🔄 Refresh"): CacheManager.clear_all("positions"); st.rerun()

    all_pos = get_cached_positions(client)
    if all_pos is None: st.error("❌ Failed"); return
    opt_pos, eq_pos = split_positions(all_pos)

    t1, t2 = st.tabs([f"Options ({len(opt_pos)})", f"Equity ({len(eq_pos)})"])

    with t1:
        if not opt_pos:
            empty_state("📭","No option positions","")
        else:
            total = 0.0; rows = []
            for p in opt_pos:
                pt = detect_position_type(p); avg = safe_float(p.get("average_price",0)); ltp = safe_float(p.get("ltp",avg))
                q = abs(safe_int(p.get("quantity",0))); pnl = calculate_pnl(pt,avg,ltp,q); total += pnl
                rows.append({"Instrument":C.api_code_to_display(p.get("stock_code","")),"Strike":p.get("strike_price"),
                    "Type":C.normalize_option_type(p.get("right","")),"Position":pt.upper(),"Qty":q,
                    "Avg":f"₹{avg:.2f}","LTP":f"₹{ltp:.2f}","P&L":f"₹{pnl:+,.2f}",
                    "Expiry":format_expiry(p.get("expiry_date","")),"Close":get_closing_action(pt).upper()})
            st.metric("Options P&L", format_currency(total))
            st.dataframe(pd.DataFrame(rows), hide_index=True)

    with t2:
        if not eq_pos:
            empty_state("📦","No equity positions","")
        else:
            rows = []
            for p in eq_pos:
                rows.append({"Stock":p.get("stock_code",""), "Qty":safe_int(p.get("quantity",0)),
                    "Avg":f"₹{safe_float(p.get('average_price',0)):.2f}", "LTP":f"₹{safe_float(p.get('ltp',0)):.2f}",
                    "P&L":f"₹{safe_float(p.get('pnl',0)):+,.2f}", "Type":p.get("product_type","")})
            total_eq = sum(safe_float(p.get("pnl",0)) for p in eq_pos)
            st.metric("Equity P&L", format_currency(total_eq))
            st.dataframe(pd.DataFrame(rows), hide_index=True)

# ═══════════════════════════════════════════════════════════════════
# STRATEGY BUILDER
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session
def page_strategy_builder():
    st.markdown('<h1 class="page-header">🎯 Strategy Builder</h1>', unsafe_allow_html=True)
    client = get_client()
    if not client: return

    c1, c2 = st.columns([1, 2])

    with c1:
        st.markdown("### Configuration")
        sname = st.selectbox("Strategy", list(PREDEFINED_STRATEGIES.keys()), key="sb_s")
        inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="sb_i")
        cfg = C.get_instrument(inst)
        expiry = st.selectbox("Expiry", C.get_next_expiries(inst,5), format_func=format_expiry, key="sb_e")
        atm = st.number_input("ATM Strike", min_value=cfg.min_strike, max_value=cfg.max_strike,
            value=(cfg.min_strike+cfg.max_strike)//2, step=cfg.strike_gap, key="sb_a")
        lots = st.number_input("Lots/Leg", min_value=1, max_value=50, value=1, key="sb_l")

        build = st.button("🔧 Build Strategy", type="primary")

    with c2:
        info = PREDEFINED_STRATEGIES[sname]
        st.markdown(f"### {sname}")
        st.markdown(info["description"])
        st.markdown(f"**View:** {info['view']} | **Risk:** {info['risk']} | **Reward:** {info['reward']}")

        if build:
            try:
                legs = generate_strategy_legs(sname, atm, cfg.strike_gap, cfg.lot_size, lots)
                st.session_state.strat_legs = legs
                st.success(f"✅ Built {len(legs)} legs")
            except Exception as e:
                st.error(f"❌ {e}")

        if st.session_state.get("strat_legs"):
            legs = st.session_state.strat_legs
            st.markdown("### Legs")
            for i, leg in enumerate(legs):
                emoji = "🟢" if leg.action == "buy" else "🔴"
                cls = "buy" if leg.action == "buy" else "sell"
                st.markdown(f'<div class="leg-card {cls}"><b>Leg {i+1}:</b> {emoji} {leg.action.upper()} {leg.strike} {leg.option_type} × {leg.quantity}</div>', unsafe_allow_html=True)

            st.markdown("---")
            if st.button("📊 Fetch Quotes & Analyze"):
                with st.spinner("Fetching quotes..."):
                    for leg in legs:
                        try:
                            r = client.get_quotes(cfg.api_code, cfg.exchange, expiry, leg.strike, leg.option_type)
                            if r["success"]:
                                items = APIResponse(r).items
                                if items: leg.premium = safe_float(items[0].get("ltp", 0))
                        except Exception: pass

                    st.session_state.strat_legs = legs

                    # Metrics
                    metrics = calculate_strategy_metrics(legs)
                    st.markdown("### Analysis")
                    mc1,mc2,mc3 = st.columns(3)
                    mc1.metric("Net Premium", format_currency(metrics["net_premium"]))
                    mc2.metric("Max Profit", format_currency(metrics["max_profit"]))
                    mc3.metric("Max Loss", format_currency(metrics["max_loss"]))
                    if metrics["breakevens"]:
                        st.info(f"Breakevens: {', '.join(str(int(b)) for b in metrics['breakevens'])}")

                    # Payoff
                    payoff_df = generate_payoff_data(legs, atm, cfg.strike_gap)
                    if payoff_df is not None:
                        st.markdown("### Payoff Diagram")
                        chart_df = payoff_df.set_index("Underlying")
                        st.line_chart(chart_df)

# ═══════════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════════

@error_handler
@require_auth
@check_session
def page_analytics():
    st.markdown('<h1 class="page-header">📈 Analytics</h1>', unsafe_allow_html=True)
    client = get_client()
    if not client: return

    t1,t2,t3 = st.tabs(["📊 Portfolio Greeks","💰 Margin","📈 Performance"])

    with t1:
        all_pos = get_cached_positions(client)
        if all_pos is None: st.error("❌ Failed"); return
        opt_pos, _ = split_positions(all_pos)
        if not opt_pos:
            empty_state("📊","No options for Greeks",""); return

        # Build position dataframe with estimated Greeks
        rows = []
        for p in opt_pos:
            pt = detect_position_type(p)
            qty = abs(safe_int(p.get("quantity",0)))
            strike = safe_float(p.get("strike_price",0))
            ltp = safe_float(p.get("ltp",0))
            ot = C.normalize_option_type(p.get("right",""))
            exp = p.get("expiry_date","")
            multiplier = -1 if pt == "short" else 1

            # Estimate Greeks
            try:
                dte = calculate_days_to_expiry(exp) if exp else 30
                tte = max(dte / 365, 0.001)
                # Rough spot estimate from strike and premium
                spot_est = strike  # crude approximation
                iv = 0.20  # default
                if ltp > 0 and strike > 0:
                    try: iv = max(0.05, min(1.0, estimate_implied_volatility(ltp, spot_est, strike, tte, ot)))
                    except Exception: iv = 0.20
                g = calculate_greeks(spot_est, strike, tte, iv, ot)
                for k in g: g[k] = g[k] * multiplier * qty
            except Exception:
                g = {'delta':0,'gamma':0,'theta':0,'vega':0,'rho':0}

            rows.append({
                "Position": C.api_code_to_display(p.get("stock_code","")),
                "Strike": strike, "Type": ot, "Dir": pt.upper(), "Qty": qty,
                "Delta": f"{g['delta']:+.2f}", "Gamma": f"{g['gamma']:+.4f}",
                "Theta": f"{g['theta']:+.2f}", "Vega": f"{g['vega']:+.2f}"
            })

        if rows:
            # Aggregate
            from analytics import estimate_implied_volatility
            st.markdown("### Position Greeks")
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            st.caption("⚠️ Greeks are approximate estimates. Spot price assumed ≈ strike for deep OTM.")

    with t2:
        st.markdown("### Margin Analysis")
        funds = get_cached_funds(client)
        if funds:
            c1,c2 = st.columns(2)
            with c1:
                st.metric("Total Balance", format_currency(funds["total_balance"]))
                st.metric("F&O Allocated", format_currency(funds["allocated_fno"]))
                st.metric("Equity Allocated", format_currency(funds["allocated_equity"]))
            with c2:
                st.metric("Unallocated", format_currency(funds["unallocated"]))
                st.metric("Blocked F&O", format_currency(funds["block_fno"]))
                util = funds["allocated_fno"]/funds["total_balance"]*100 if funds["total_balance"]>0 else 0
                st.metric("Utilization", f"{util:.1f}%")
                if util > 80: st.warning("⚠️ High utilization!")

            # Chart
            chart_data = pd.DataFrame({
                "Category": ["F&O", "Equity", "Unallocated", "Blocked"],
                "Amount": [funds["allocated_fno"], funds["allocated_equity"], funds["unallocated"], funds["block_fno"]]
            })
            chart_data = chart_data[chart_data["Amount"] > 0]
            if not chart_data.empty:
                st.bar_chart(chart_data.set_index("Category"))

    with t3:
        st.markdown("### Performance")
        activity = SessionState.get_activity_log()
        if activity:
            st.write(f"**Session actions:** {len(activity)}")
            trades = [a for a in activity if a["action"] in ("Sell","Order","SqOff","Square Off")]
            st.write(f"**Trade actions:** {len(trades)}")
            if activity:
                st.dataframe(pd.DataFrame(activity[:20]), hide_index=True)
        else:
            empty_state("📈","No activity data yet","Trade to see analytics")

# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

PAGE_FN = {
    "Dashboard": page_dashboard, "Option Chain": page_option_chain,
    "Sell Options": page_sell_options, "Square Off": page_square_off,
    "Orders & Trades": page_orders_trades, "Positions": page_positions,
    "Strategy Builder": page_strategy_builder, "Analytics": page_analytics,
}

def main():
    try:
        SessionState.initialize()
        render_sidebar()
        st.markdown('<h1 class="main-header">📈 Breeze Options Trader</h1>', unsafe_allow_html=True)
        st.markdown("---")
        page = SessionState.get_current_page()
        if page in AUTH_PAGES and not SessionState.is_authenticated():
            st.warning("🔒 Login required"); st.info("👈 Use the sidebar"); return
        if SessionState.is_authenticated() and SessionState.is_session_expired():
            st.error("🔴 Session expired")
            if st.button("🔄 Reconnect", type="primary"):
                SessionState.set_authentication(False, None); SessionState.navigate_to("Dashboard"); st.rerun()
            return
        PAGE_FN.get(page, page_dashboard)()
    except Exception as e:
        log.critical(f"Fatal: {e}", exc_info=True)
        st.error("❌ Critical error. Refresh the page.")
        if st.session_state.get("debug_mode"): st.exception(e)

if __name__ == "__main__":
    main()
